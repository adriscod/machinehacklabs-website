from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

from mhl_quote.models import (
    TURNAROUND_RANK,
    CostBreakdown,
    FeatureRisk,
    FeatureRiskConfig,
    JobOverrides,
    MaterialSource,
    QuoteConfig,
    ToleranceClass,
    ToleranceConfig,
    Turnaround,
    TurnaroundTier,
)


class JobInputError(ValueError):
    """Invalid RFQ v2 job input."""


def parse_material_source(value: str | MaterialSource | None) -> MaterialSource:
    if value is None or value == "":
        return MaterialSource.SHOP_BUYS
    if isinstance(value, MaterialSource):
        return value
    needle = str(value).strip().lower()
    for item in MaterialSource:
        if item.value == needle:
            return item
    known = ", ".join(item.value for item in MaterialSource)
    raise JobInputError(f"unknown material_source {value!r}; expected {known}")


def parse_turnaround(value: str | Turnaround | None) -> Turnaround:
    if value is None or value == "":
        return Turnaround.STANDARD
    if isinstance(value, Turnaround):
        return value
    needle = str(value).strip().lower()
    for item in Turnaround:
        if item.value == needle:
            return item
    known = ", ".join(item.value for item in Turnaround)
    raise JobInputError(f"unknown turnaround {value!r}; expected {known}")


def parse_tolerance_class(value: str | ToleranceClass | None) -> ToleranceClass:
    if value is None or value == "":
        return ToleranceClass.STANDARD
    if isinstance(value, ToleranceClass):
        return value
    needle = str(value).strip().lower()
    for item in ToleranceClass:
        if item.value == needle:
            return item
    known = ", ".join(item.value for item in ToleranceClass)
    raise JobInputError(f"unknown tolerance_class {value!r}; expected {known}")


def parse_feature_risks(
    values: Iterable[str | FeatureRisk] | None,
    *,
    allowed: Iterable[FeatureRisk] | None = None,
) -> tuple[FeatureRisk, ...]:
    if not values:
        return ()
    allowed_set = {item for item in (allowed or FeatureRisk)}
    parsed: list[FeatureRisk] = []
    seen: set[FeatureRisk] = set()
    for raw in values:
        item = raw if isinstance(raw, FeatureRisk) else _parse_one_risk(raw)
        if item not in allowed_set:
            raise JobInputError(f"unknown feature_risk {item.value!r}")
        if item not in seen:
            parsed.append(item)
            seen.add(item)
    return tuple(parsed)


def _parse_one_risk(value: str) -> FeatureRisk:
    needle = str(value).strip().lower()
    for item in FeatureRisk:
        if item.value == needle:
            return item
    known = ", ".join(item.value for item in FeatureRisk)
    raise JobInputError(f"unknown feature_risk {value!r}; expected {known}")


def parse_iso_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise JobInputError(f"invalid ISO date {value!r}") from exc


def business_days_until(as_of: date, due: date) -> int:
    """Mon–Fri days from the day after as_of through due inclusive.

    Same-day or past due returns 0. Weekends are skipped. Holidays are not
    excluded (Andrew can replace this with a shop calendar later).
    """
    if due <= as_of:
        return 0
    days = 0
    cursor = as_of + timedelta(days=1)
    while cursor <= due:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def implied_turnaround(
    business_days: int, tiers: Mapping[Turnaround, TurnaroundTier]
) -> Turnaround:
    """Tightest tier whose min_business_days is still satisfied.

    Fewer calendar days → tighter (more expensive) tier.
    """
    if business_days >= tiers[Turnaround.STANDARD].min_business_days:
        return Turnaround.STANDARD
    if business_days >= tiers[Turnaround.RUSH].min_business_days:
        return Turnaround.RUSH
    return Turnaround.EMERGENCY


def resolve_turnaround(
    *,
    config: QuoteConfig,
    requested: Turnaround,
    due_date: date | None,
    as_of_date: date | None,
) -> tuple[Turnaround, bool, int | None, str | None, tuple[str, ...]]:
    """Return applied tier, bumped?, business days, warning, review reasons."""
    review: list[str] = []
    if due_date is None:
        return requested, False, None, None, ()

    as_of = as_of_date or date.today()
    days = business_days_until(as_of, due_date)
    implied = implied_turnaround(days, config.turnaround)
    warning = None
    bumped = False
    applied = requested

    if due_date <= as_of:
        warning = (
            f"due_date {due_date.isoformat()} is on or before as-of "
            f"{as_of.isoformat()}; treating as emergency and requiring shop review."
        )
        if TURNAROUND_RANK[requested] < TURNAROUND_RANK[Turnaround.EMERGENCY]:
            applied = Turnaround.EMERGENCY
            bumped = True
        review.append(warning)
        return applied, bumped, days, warning, tuple(review)

    if TURNAROUND_RANK[implied] > TURNAROUND_RANK[requested]:
        applied = implied
        bumped = True
        warning = (
            f"due_date {due_date.isoformat()} is {days} business day(s) from "
            f"{as_of.isoformat()}, which is tighter than turnaround "
            f"{requested.value} (min {config.turnaround[requested].min_business_days} "
            f"business days). Auto-bumped to {applied.value}."
        )
        review.append(warning)
    return applied, bumped, days, warning, tuple(review)


def complexity_mult(
    *,
    tolerance: ToleranceConfig,
    feature_risks_cfg: FeatureRiskConfig,
    tolerance_class: ToleranceClass,
    feature_risks: Iterable[FeatureRisk],
) -> float:
    try:
        tol_mult = float(tolerance.multipliers[tolerance_class])
    except KeyError as exc:
        raise JobInputError(f"tolerance_class {tolerance_class.value!r} has no multiplier") from exc
    n_risks = len(tuple(feature_risks))
    raw = tol_mult + n_risks * feature_risks_cfg.mult_each
    return min(feature_risks_cfg.mult_cap, raw)


def resolve_shop_review(
    *,
    config: QuoteConfig,
    tolerance_class: ToleranceClass,
    schedule_reasons: Iterable[str],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = list(schedule_reasons)
    if tolerance_class is ToleranceClass.PRECISION and config.tolerance.precision_requires_shop_review:
        reasons.append("precision tolerance class requires shop review before any customer reply.")
    elif tolerance_class is ToleranceClass.STANDARD:
        pass
    elif tolerance_class is ToleranceClass.TIGHT:
        pass
    else:
        raise JobInputError(f"unhandled tolerance_class {tolerance_class}")
    return (bool(reasons), tuple(reasons))


def material_cost_usd(
    *,
    stock_vol: float,
    qty: int,
    cost_usd_per_in3: float,
    source: MaterialSource,
    invoice_override_usd: float | None,
) -> tuple[float, bool]:
    """Return (material_usd, is_catalog_estimate)."""
    if source is MaterialSource.CUSTOMER_SUPPLIED:
        return 0.0, False
    if source is MaterialSource.SHOP_BUYS:
        if invoice_override_usd is not None:
            return float(invoice_override_usd), False
        return stock_vol * cost_usd_per_in3 * qty, True
    raise JobInputError(f"unhandled material_source {source}")


def shop_payload_from_cost(cost: CostBreakdown) -> dict[str, object]:
    """Hidden-field payload keys for the /quote/ UI teammate to wire."""
    return {
        "material_key": cost.material_key,
        "material_family": cost.material_family,
        "material_source": cost.material_source.value,
        "turnaround": cost.turnaround_applied.value,
        "turnaround_requested": cost.turnaround_requested.value,
        "turnaround_bumped": "yes" if cost.turnaround_bumped else "no",
        "rush_labor_mult": cost.rush_labor_mult,
        "rush_setup_mult": cost.rush_setup_mult,
        "setups": cost.setups,
        "qty": cost.qty,
        "tolerance_class": cost.tolerance_class.value,
        "complexity_mult": cost.complexity_mult,
        "feature_risks": ",".join(r.value for r in cost.feature_risks),
        "due_date": cost.due_date.isoformat() if cost.due_date else "",
        "due_date_business_days": (
            "" if cost.due_date_business_days is None else cost.due_date_business_days
        ),
        "due_date_warning": cost.due_date_warning or "",
        "shop_review_required": "yes" if cost.shop_review_required else "no",
        "shop_review_reasons": " | ".join(cost.shop_review_reasons),
        "catalog_values_are_placeholders": (
            "yes" if cost.catalog_values_are_placeholders else "no"
        ),
        "quote_low_usd": cost.quote_low_usd,
        "quote_high_usd": cost.quote_high_usd,
        "raw_quote_usd": cost.raw_quote_usd,
        "labor_usd": cost.labor_usd,
        "material_usd": cost.material_usd,
        "removal_volume_in3": cost.removal_volume_in3,
        "cut_hours": cost.cut_hours,
        "setup_hours": cost.setup_hours,
    }
