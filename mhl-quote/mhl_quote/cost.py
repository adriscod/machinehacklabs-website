from __future__ import annotations

from mhl_quote.models import (
    CostBreakdown,
    JobOverrides,
    MaterialSpec,
    QuoteConfig,
    Timeline,
    Vec3,
)
from mhl_quote.time_estimator import (
    DEFAULT_TIME_ESTIMATOR,
    TimeEstimator,
    TimeInputs,
)


def money(value: float) -> float:
    """Round USD to cents for display and the published range."""
    return round(value + 0.0, 2)


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
    """MHL-CF-001 cost model with rush, tight-tolerance, and quantity rules.

    Geometry proxy (via the pluggable :class:`TimeEstimator`):
        stock_vol = bbox_x*bbox_y*bbox_z (or overridden stock dims)
        removal_vol = max(0, stock_vol - part_vol)
        cut_hours = removal_vol / MRR_eff ; setup_hours from config/override

    Labor rate:
        standard $rate; rush jobs bill every hour at $rush_rate. A whole-part-tight
        job also bills every hour at $rush_rate (and per-callout adders drop out).

    Tight tolerance (labor only; materials still pass through):
        whole_part_tight -> all labor @ rush rate, no per-callout adders.
        else N>=1 callouts -> tol_labor = first_hour_rate + (rate*(1+uplift%))*(N-1).

    Quantity (amortize setup + guardrails):
        per_part_labor = (setup/effective_qty + cut)*labor_rate + tol_labor
        effective_qty = min(quantity, max_amortization_qty)
        per_part_raw = max(per_part_material + per_part_labor, min_charge_per_part)
        batch_total = quantity * per_part_raw
        A capped divisor or a binding per-part floor raises an operator callout.
    """
    overrides = overrides or JobOverrides()
    estimator = time_estimator or DEFAULT_TIME_ESTIMATOR
    shop = config.shop
    tol = config.tolerances

    stock_dims = overrides.stock_dims_in or bbox_in
    stock_vol = max(0.0, stock_dims.volume())
    part_vol = max(0.0, part_volume_in3)
    removal_vol = max(0.0, stock_vol - part_vol)

    mrr = overrides.mrr_eff_in3_per_hr or material.mrr_eff_in3_per_hr
    if mrr <= 0:
        raise ValueError("MRR_eff must be > 0")

    default_setup = shop.setup_hours if overrides.setup_hours is None else overrides.setup_hours
    if default_setup < 0:
        raise ValueError("setup_hours must be >= 0")

    time = estimator.estimate(
        TimeInputs(
            removal_volume_in3=removal_vol,
            mrr_eff_in3_per_hr=mrr,
            part_volume_in3=part_vol,
            stock_volume_in3=stock_vol,
            default_setup_hours=default_setup,
        )
    )
    setup = time.setup_hours
    cut = time.cut_hours

    quantity = max(1, int(overrides.quantity))
    max_amort = max(1, int(shop.max_amortization_qty))
    effective_qty = min(quantity, max_amort)
    amortization_capped = quantity > max_amort

    rush_applied = overrides.timeline is Timeline.RUSH
    whole_tight = bool(overrides.whole_part_tight)
    tight_n = max(0, int(overrides.tight_callouts))

    # Rush OR whole-part-tight elevate every labor hour to the rush rate.
    labor_rate = (
        shop.rush_rate_usd_per_hr
        if (rush_applied or whole_tight)
        else shop.rate_usd_per_hr
    )

    tolerance_labor = _tolerance_labor(
        shop_rate=shop.rate_usd_per_hr,
        first_hour_rate=tol.tight_first_hour_rate_usd,
        uplift_pct=tol.additional_uplift_pct,
        hours_per_callout=tol.hours_per_callout,
        n=tight_n,
        whole_part_tight=whole_tight,
    )

    per_part_labor_hours = setup / effective_qty + cut
    per_part_labor = per_part_labor_hours * labor_rate + tolerance_labor

    if overrides.stock_purchase_cost_usd is not None:
        per_part_material = overrides.stock_purchase_cost_usd
        catalog_estimate = False
    else:
        per_part_material = stock_vol * material.cost_usd_per_in3
        catalog_estimate = True

    per_part_uncapped = per_part_material + per_part_labor
    floor = shop.min_charge_per_part_usd
    min_charge_per_part_applied = per_part_uncapped < floor
    per_part_raw = max(per_part_uncapped, floor)
    batch_total = quantity * per_part_raw

    guardrail = _guardrail_callout(
        amortization_capped=amortization_capped,
        min_charge_applied=min_charge_per_part_applied,
        max_amort=max_amort,
        floor=floor,
    )

    raw = money(batch_total)
    return CostBreakdown(
        material_key=material.key,
        material_label=material.label,
        stock_volume_in3=volume(stock_vol),
        part_volume_in3=volume(part_vol),
        removal_volume_in3=volume(removal_vol),
        setup_hours=hours(setup),
        cut_hours=hours(cut),
        mrr_eff_in3_per_hr=mrr,
        shop_rate_usd_per_hr=labor_rate,
        labor_usd=money(per_part_labor),
        material_usd=money(per_part_material),
        material_cost_is_catalog_estimate=catalog_estimate,
        raw_quote_usd=raw,
        quote_low_usd=money(raw * shop.band_low),
        quote_high_usd=money(raw * shop.band_high),
        min_charge_applied=min_charge_per_part_applied,
        quantity=quantity,
        effective_qty=effective_qty,
        rush_applied=rush_applied,
        tight_callouts=tight_n,
        whole_part_tight=whole_tight,
        tolerance_labor_usd=money(tolerance_labor),
        per_part_labor_usd=money(per_part_labor),
        per_part_material_usd=money(per_part_material),
        per_part_raw_usd=money(per_part_raw),
        per_part_low_usd=money(per_part_raw * shop.band_low),
        per_part_high_usd=money(per_part_raw * shop.band_high),
        batch_total_usd=money(batch_total),
        amortization_capped=amortization_capped,
        material_on_shelf=bool(overrides.material_on_shelf),
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
