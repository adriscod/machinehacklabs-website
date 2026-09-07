from __future__ import annotations

import math

from mhl_quote.job_inputs import (
    JobInputError,
    complexity_mult,
    material_cost_usd,
    resolve_shop_review,
    resolve_turnaround,
)
from mhl_quote.models import (
    CostBreakdown,
    JobOverrides,
    MaterialSpec,
    QuoteConfig,
    Turnaround,
    Vec3,
)
from mhl_quote.time_estimator import (
    DEFAULT_TIME_ESTIMATOR,
    TimeEstimator,
    TimeInputs,
)


def money(value: float) -> float:
    """Round USD to cents, half away from zero (matches JS Math.round)."""
    scaled = value * 100.0
    if scaled >= 0:
        return round(math.floor(scaled + 0.5) / 100.0, 2)
    return round(math.ceil(scaled - 0.5) / 100.0, 2)


def hours(value: float) -> float:
    return round(value, 4)


def volume(value: float) -> float:
    return round(value, 4)


def compute_cost(
    *,
    config: QuoteConfig,
    material: MaterialSpec,
    bbox_in: Vec3,
    part_volume_in3: float,
    overrides: JobOverrides | None = None,
    time_estimator: TimeEstimator | None = None,
) -> CostBreakdown:
    """RFQ v2 cost model (MHL-CF-001) plus pipeline rush/tight/qty seams.

    stock_vol = bbox (or stock override) volume in³
    part_vol = solid volume in³
    removal_vol = max(0, stock_vol − part_vol)
    cut_each = TimeEstimator (default: removal_vol / MRR_eff)
    cut_hours = cut_each × qty × complexity_mult
    setup_hours = base_setup × setups × rush_setup_mult × (qty / effective_qty)
    hourly_rate = rush_rate if rush/emergency/whole-part-tight else shop_rate
    tolerance_$ = 0 if whole-part-tight else first_hour + additional*(N-1)
    labor_$ = (setup_hours + cut_hours) × hourly_rate + tolerance_$ × qty
    material_$ = material_cost_model(qty, stock, who_supplies)
    per_part_raw = max((material_$ + labor_$)/qty, min_charge_per_part)
    raw_$ = max(per_part_raw × qty, min_charge × rush_labor_mult)
    range = raw_$ × band_low … raw_$ × band_high
    """
    overrides = overrides or JobOverrides()
    estimator = time_estimator or DEFAULT_TIME_ESTIMATOR
    qty = overrides.qty if overrides.qty is not None else 1
    if qty < 1:
        raise ValueError("qty must be >= 1")
    setups = overrides.setups if overrides.setups is not None else 1
    if setups < 1:
        raise ValueError("setups must be >= 1")

    stock_dims = overrides.stock_dims_in or bbox_in
    stock_vol = max(0.0, stock_dims.volume())
    part_vol = max(0.0, part_volume_in3)
    removal_vol = max(0.0, stock_vol - part_vol)

    mrr = overrides.mrr_eff_in3_per_hr or material.mrr_eff_in3_per_hr
    if mrr <= 0:
        raise ValueError("MRR_eff must be > 0")

    applied, bumped, days, warning, schedule_reasons = resolve_turnaround(
        config=config,
        requested=overrides.turnaround,
        due_date=overrides.due_date,
        as_of_date=overrides.as_of_date,
    )
    tier = config.turnaround[applied]
    rush_labor = tier.labor_mult
    rush_setup = tier.setup_mult
    rush_applied = applied is not Turnaround.STANDARD
    whole_tight = bool(overrides.whole_part_tight)
    tight_n = max(0, int(overrides.tight_callouts))

    base_setup = (
        config.shop.setup_hours if overrides.setup_hours is None else overrides.setup_hours
    )
    if base_setup < 0:
        raise ValueError("setup_hours must be >= 0")

    time = estimator.estimate(
        TimeInputs(
            removal_volume_in3=removal_vol,
            mrr_eff_in3_per_hr=mrr,
            part_volume_in3=part_vol,
            stock_volume_in3=stock_vol,
            default_setup_hours=base_setup,
        )
    )

    max_amort = max(1, int(config.shop.max_amortization_qty))
    effective_qty = min(qty, max_amort)
    amortization_capped = qty > max_amort
    amort_mult = qty / effective_qty
    setup = time.setup_hours * setups * rush_setup * amort_mult

    complexity = complexity_mult(
        tolerance=config.tolerance,
        feature_risks_cfg=config.feature_risks,
        tolerance_class=overrides.tolerance_class,
        feature_risks=overrides.feature_risks,
    )
    cut = time.cut_hours * qty * complexity

    applied_rate = (
        config.shop.rush_rate_usd_per_hr
        if (rush_applied or whole_tight)
        else config.shop.rate_usd_per_hr
    )
    tolerance_labor = _tolerance_labor(
        shop_rate=config.shop.rate_usd_per_hr,
        first_hour_rate=config.tolerances.tight_first_hour_rate_usd,
        uplift_pct=config.tolerances.additional_uplift_pct,
        hours_per_callout=config.tolerances.hours_per_callout,
        n=tight_n,
        whole_part_tight=whole_tight,
    )
    labor = (setup + cut) * applied_rate + tolerance_labor * qty

    try:
        material_usd, catalog_estimate = material_cost_usd(
            stock_vol=stock_vol,
            qty=qty,
            cost_usd_per_in3=material.cost_usd_per_in3,
            source=overrides.material_source,
            invoice_override_usd=overrides.stock_purchase_cost_usd,
        )
    except JobInputError as exc:
        raise ValueError(str(exc)) from exc

    per_part_labor = labor / qty
    per_part_material = material_usd / qty
    per_part_uncapped = per_part_labor + per_part_material
    part_floor = config.shop.min_charge_per_part_usd
    min_charge_per_part_applied = per_part_uncapped < part_floor
    per_part_raw = max(per_part_uncapped, part_floor)
    batch = per_part_raw * qty
    legacy_floor = config.shop.min_charge_usd * rush_labor
    raw = money(max(batch, legacy_floor))
    min_charge_applied = (material_usd + labor) < max(legacy_floor, part_floor * qty)
    review_required, review_reasons = resolve_shop_review(
        config=config,
        tolerance_class=overrides.tolerance_class,
        schedule_reasons=schedule_reasons,
    )
    placeholders = material.cost_is_placeholder or material.mrr_is_placeholder
    guardrail = _guardrail_callout(
        amortization_capped=amortization_capped,
        min_charge_applied=min_charge_per_part_applied,
        max_amort=max_amort,
        floor=part_floor,
    )

    return CostBreakdown(
        material_key=material.key,
        material_label=material.label,
        material_family=material.family,
        material_source=overrides.material_source,
        qty=qty,
        setups=setups,
        stock_volume_in3=volume(stock_vol),
        part_volume_in3=volume(part_vol),
        removal_volume_in3=volume(removal_vol),
        setup_hours=hours(setup),
        cut_hours=hours(cut),
        mrr_eff_in3_per_hr=mrr,
        shop_rate_usd_per_hr=applied_rate,
        labor_usd=money(labor),
        material_usd=money(material_usd),
        material_cost_is_catalog_estimate=catalog_estimate,
        catalog_values_are_placeholders=placeholders,
        raw_quote_usd=raw,
        quote_low_usd=money(raw * config.shop.band_low),
        quote_high_usd=money(raw * config.shop.band_high),
        min_charge_applied=min_charge_applied,
        turnaround_requested=overrides.turnaround,
        turnaround_applied=applied,
        turnaround_bumped=bumped,
        rush_labor_mult=rush_labor,
        rush_setup_mult=rush_setup,
        tolerance_class=overrides.tolerance_class,
        feature_risks=overrides.feature_risks,
        complexity_mult=complexity,
        due_date=overrides.due_date,
        as_of_date=overrides.as_of_date,
        due_date_business_days=days,
        due_date_warning=warning,
        shop_review_required=review_required,
        shop_review_reasons=review_reasons,
        material_class=material.material_class,
        rush_applied=rush_applied or whole_tight,
        applied_rate_usd_per_hr=applied_rate,
        tight_callouts=tight_n,
        whole_part_tight=whole_tight,
        tolerance_labor_usd=money(tolerance_labor),
        effective_qty=effective_qty,
        amortization_capped=amortization_capped,
        per_part_labor_usd=money(per_part_labor),
        per_part_material_usd=money(per_part_material),
        per_part_raw_usd=money(per_part_raw),
        per_part_low_usd=money(per_part_raw * config.shop.band_low),
        per_part_high_usd=money(per_part_raw * config.shop.band_high),
        guardrail_callout=guardrail,
    )


def _tolerance_labor(
    *,
    shop_rate: float,
    first_hour_rate: float,
    uplift_pct: float,
    hours_per_callout: float,
    n: int,
    whole_part_tight: bool,
) -> float:
    if whole_part_tight or n <= 0:
        return 0.0
    additional_rate = shop_rate * (1.0 + uplift_pct / 100.0)
    first = first_hour_rate * hours_per_callout
    additional = additional_rate * hours_per_callout * (n - 1)
    return first + additional


def _guardrail_callout(
    *,
    amortization_capped: bool,
    min_charge_applied: bool,
    max_amort: int,
    floor: float,
) -> str | None:
    reasons: list[str] = []
    if amortization_capped:
        reasons.append(f"setup amortization is capped at qty {max_amort}")
    if min_charge_applied:
        reasons.append(f"per-part price hit the ${floor:g} floor")
    if not reasons:
        return None
    return (
        "Batch pricing — operator review: "
        + "; ".join(reasons)
        + ". Amortization is no longer advantageous; revisit the setup/quantity split."
    )
