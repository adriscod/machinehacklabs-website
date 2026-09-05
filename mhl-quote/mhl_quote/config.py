from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from mhl_quote.models import (
    MachineConfig,
    MaterialSpec,
    QuoteConfig,
    ShopConfig,
    Vec3,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "quote.yaml"


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
        )

    return QuoteConfig(shop=shop, machine=machine, materials=materials, source_path=str(resolved))


def find_material(config: QuoteConfig, name: str) -> MaterialSpec:
    needle = name.strip().lower()
    if needle in config.materials:
        return config.materials[needle]
    for spec in config.materials.values():
        if needle in spec.aliases or needle == spec.family:
            return spec
    known = ", ".join(sorted(config.materials))
    raise ConfigError(f"unknown material {name!r}; catalog: {known}")


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
