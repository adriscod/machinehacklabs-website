from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from mhl_quote.models import (
    FeatureRisk,
    FeatureRiskConfig,
    MachineConfig,
    MaterialSpec,
    QuoteConfig,
    ShopConfig,
    ToleranceClass,
    ToleranceConfig,
    Turnaround,
    TurnaroundTier,
    Vec3,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "quote.yaml"

PLACEHOLDER_TOKEN = "TODO_REPLACE"


class ConfigError(ValueError):
    """Invalid or missing quote configuration."""


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path

    candidates = [
        Path.cwd() / "config" / "quote.yaml",
        Path.cwd() / "quote.yaml",
        DEFAULT_CONFIG_PATH,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigError(
        "no config file found; pass --config or keep config/quote.yaml next to the package"
    )


def load_config(path: str | Path | None = None) -> QuoteConfig:
    resolved = resolve_config_path(path)
    raw = _read_mapping(resolved)
    try:
        shop_raw = raw["shop"]
        machine_raw = raw["machine"]
        materials_raw = raw["materials"]
    except KeyError as exc:
        raise ConfigError(f"{resolved}: missing top-level key {exc}") from exc

    shop = ShopConfig(
        rate_usd_per_hr=_require_positive(shop_raw, "rate_usd_per_hr", resolved),
        setup_hours=_require_non_negative(shop_raw, "setup_hours", resolved),
        min_charge_usd=_require_non_negative(shop_raw, "min_charge_usd", resolved),
        band_low=_require_positive(shop_raw, "band_low", resolved),
        band_high=_require_positive(shop_raw, "band_high", resolved),
    )
    if shop.band_low >= shop.band_high:
        raise ConfigError(f"{resolved}: shop.band_low must be < shop.band_high")

    envelope = _require_vec3(machine_raw.get("envelope_in"), "machine.envelope_in", resolved)
    margin = _require_vec3(
        machine_raw.get("fixture_margin_in"), "machine.fixture_margin_in", resolved
    )
    machine = MachineConfig(
        name=str(machine_raw.get("name") or "Tormach 1500MX"),
        axes=int(machine_raw.get("axes") or 3),
        envelope_in=envelope,
        fixture_margin_in=margin,
    )
    usable = machine.usable_in
    if usable.x <= 0 or usable.y <= 0 or usable.z <= 0:
        raise ConfigError(f"{resolved}: fixture margin leaves no usable travel")

    if not isinstance(materials_raw, Mapping) or not materials_raw:
        raise ConfigError(f"{resolved}: materials catalog is empty")

    materials: dict[str, MaterialSpec] = {}
    for key, spec in materials_raw.items():
        if not isinstance(spec, Mapping):
            raise ConfigError(f"{resolved}: material {key!r} must be a mapping")
        aliases = tuple(str(a).strip().lower() for a in spec.get("aliases") or ())
        materials[str(key).lower()] = MaterialSpec(
            key=str(key).lower(),
            label=str(spec.get("label") or key),
            family=str(spec.get("family") or key).lower(),
            aliases=aliases,
            mrr_eff_in3_per_hr=_require_positive(spec, "mrr_eff_in3_per_hr", resolved, key),
            mrr_typical_low_in3_per_hr=float(spec.get("mrr_typical_low_in3_per_hr") or 0.0),
            mrr_typical_high_in3_per_hr=float(spec.get("mrr_typical_high_in3_per_hr") or 0.0),
            cost_usd_per_in3=_require_non_negative(spec, "cost_usd_per_in3", resolved, key),
            enabled=bool(spec.get("enabled", True)),
            cost_is_placeholder=_is_placeholder(spec.get("cost_placeholder")),
            mrr_is_placeholder=_is_placeholder(spec.get("mrr_placeholder")),
        )

    turnaround = _load_turnaround(raw.get("turnaround"), resolved)
    tolerance = _load_tolerance(raw.get("tolerance"), resolved)
    feature_risks = _load_feature_risks(raw.get("feature_risks"), resolved)
    meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}

    return QuoteConfig(
        shop=shop,
        machine=machine,
        materials=materials,
        turnaround=turnaround,
        tolerance=tolerance,
        feature_risks=feature_risks,
        source_path=str(resolved),
        meta=dict(meta),
    )


def find_material(config: QuoteConfig, name: str, *, allow_disabled: bool = False) -> MaterialSpec:
    needle = name.strip().lower()
    if needle in config.materials:
        spec = config.materials[needle]
        if spec.enabled or allow_disabled:
            return spec
        raise ConfigError(f"material {name!r} is disabled in the catalog")

    alias_hits = [
        spec
        for spec in config.materials.values()
        if needle in spec.aliases and (spec.enabled or allow_disabled)
    ]
    if len(alias_hits) == 1:
        return alias_hits[0]
    if len(alias_hits) > 1:
        keys = ", ".join(sorted(s.key for s in alias_hits))
        raise ConfigError(f"material alias {name!r} is ambiguous; matches {keys}")

    family_hits = [
        spec
        for spec in config.materials.values()
        if needle == spec.family and (spec.enabled or allow_disabled)
    ]
    if len(family_hits) == 1:
        return family_hits[0]
    if len(family_hits) > 1:
        keys = ", ".join(sorted(s.key for s in family_hits))
        raise ConfigError(
            f"material family {name!r} is ambiguous; pick a catalog key: {keys}"
        )

    known = ", ".join(sorted(k for k, s in config.materials.items() if s.enabled or allow_disabled))
    raise ConfigError(f"unknown material {name!r}; catalog: {known}")


def enabled_materials(config: QuoteConfig) -> list[MaterialSpec]:
    return [spec for spec in config.materials.values() if spec.enabled]


def _load_turnaround(raw: Any, source: Path) -> dict[Turnaround, TurnaroundTier]:
    defaults: dict[Turnaround, tuple[float, float, int]] = {
        Turnaround.STANDARD: (1.0, 1.0, 10),
        Turnaround.RUSH: (1.5, 1.25, 4),
        Turnaround.EMERGENCY: (2.0, 1.5, 1),
    }
    data = raw if isinstance(raw, Mapping) else {}
    tiers: dict[Turnaround, TurnaroundTier] = {}
    for key in Turnaround:
        row = data.get(key.value) if isinstance(data.get(key.value), Mapping) else {}
        labor_default, setup_default, days_default = defaults[key]
        labor = float(row.get("labor_mult", labor_default))
        setup = float(row.get("setup_mult", setup_default))
        days = int(row.get("min_business_days", days_default))
        if labor <= 0 or setup <= 0:
            raise ConfigError(f"{source}: turnaround.{key.value} multipliers must be > 0")
        if days < 0:
            raise ConfigError(f"{source}: turnaround.{key.value}.min_business_days must be >= 0")
        tiers[key] = TurnaroundTier(
            key=key,
            labor_mult=labor,
            setup_mult=setup,
            min_business_days=days,
        )
    return tiers


def _load_tolerance(raw: Any, source: Path) -> ToleranceConfig:
    data = raw if isinstance(raw, Mapping) else {}
    defaults = {
        ToleranceClass.STANDARD: 1.0,
        ToleranceClass.TIGHT: 1.25,
        ToleranceClass.PRECISION: 1.5,
    }
    multipliers: dict[ToleranceClass, float] = {}
    for key in ToleranceClass:
        value = float(data.get(key.value, defaults[key]))
        if value <= 0:
            raise ConfigError(f"{source}: tolerance.{key.value} must be > 0")
        multipliers[key] = value
    review = bool(data.get("precision_requires_shop_review", True))
    return ToleranceConfig(multipliers=multipliers, precision_requires_shop_review=review)


def _load_feature_risks(raw: Any, source: Path) -> FeatureRiskConfig:
    data = raw if isinstance(raw, Mapping) else {}
    keys_raw = data.get("keys") or [item.value for item in FeatureRisk]
    keys: list[FeatureRisk] = []
    for item in keys_raw:
        needle = str(item).strip().lower()
        match = next((r for r in FeatureRisk if r.value == needle), None)
        if match is None:
            raise ConfigError(f"{source}: unknown feature_risks key {item!r}")
        if match not in keys:
            keys.append(match)
    each = float(data.get("mult_each", 0.15))
    cap = float(data.get("mult_cap", 1.75))
    if each < 0:
        raise ConfigError(f"{source}: feature_risks.mult_each must be >= 0")
    if cap <= 0:
        raise ConfigError(f"{source}: feature_risks.mult_cap must be > 0")
    return FeatureRiskConfig(keys=tuple(keys), mult_each=each, mult_cap=cap)


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() == PLACEHOLDER_TOKEN


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ConfigError(f"config must be .yaml, .yml, or .json (got {path.name})")
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: root must be a mapping")
    return data


def _require_vec3(raw: Any, label: str, source: Path) -> Vec3:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{source}: {label} must be {{x, y, z}}")
    try:
        vec = Vec3(x=float(raw["x"]), y=float(raw["y"]), z=float(raw["z"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{source}: {label} must include numeric x, y, z") from exc
    if vec.x <= 0 or vec.y <= 0 or vec.z <= 0:
        raise ConfigError(f"{source}: {label} dimensions must be > 0")
    return vec


def _require_positive(
    raw: Mapping[str, Any], key: str, source: Path, prefix: str | None = None
) -> float:
    value = _require_float(raw, key, source, prefix)
    if value <= 0:
        where = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{source}: {where} must be > 0")
    return value


def _require_non_negative(
    raw: Mapping[str, Any], key: str, source: Path, prefix: str | None = None
) -> float:
    value = _require_float(raw, key, source, prefix)
    if value < 0:
        where = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{source}: {where} must be >= 0")
    return value


def _require_float(
    raw: Mapping[str, Any], key: str, source: Path, prefix: str | None = None
) -> float:
    if key not in raw:
        where = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{source}: missing {where}")
    try:
        return float(raw[key])
    except (TypeError, ValueError) as exc:
        where = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{source}: {where} must be numeric") from exc
