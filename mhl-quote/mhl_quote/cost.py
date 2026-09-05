from __future__ import annotations

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
    Vec3,
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
) -> CostBreakdown:
    """RFQ v2 cost model (MHL-CF-001).

    stock_vol = bbox (or stock override) volume in³
    part_vol = solid volume in³
    removal_vol = max(0, stock_vol − part_vol)
    cut_hours = (removal_vol / MRR_eff) × qty × complexity_mult
    setup_hours = base_setup_hours × setups × rush_setup_mult
    labor_$ = (setup_hours + cut_hours) × shop_rate × rush_labor_mult
    material_$ = material_cost_model(qty, stock, who_supplies)
    raw_$ = max(material_$ + labor_$, min_charge × rush_labor_mult)
    range = raw_$ × band_low … raw_$ × band_high
    """
    overrides = overrides or JobOverrides()
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

    base_setup = (
        config.shop.setup_hours if overrides.setup_hours is None else overrides.setup_hours
    )
    if base_setup < 0:
        raise ValueError("setup_hours must be >= 0")
    setup = base_setup * setups * rush_setup

    complexity = complexity_mult(
        tolerance=config.tolerance,
        feature_risks_cfg=config.feature_risks,
        tolerance_class=overrides.tolerance_class,
        feature_risks=overrides.feature_risks,
    )
    cut_each = 0.0 if removal_vol == 0 else removal_vol / mrr
    cut = cut_each * qty * complexity
    labor = (setup + cut) * config.shop.rate_usd_per_hr * rush_labor

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

    min_charge = config.shop.min_charge_usd * rush_labor
    raw = money(max(material_usd + labor, min_charge))
    review_required, review_reasons = resolve_shop_review(
        config=config,
        tolerance_class=overrides.tolerance_class,
        schedule_reasons=schedule_reasons,
    )
    placeholders = material.cost_is_placeholder or material.mrr_is_placeholder

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
        shop_rate_usd_per_hr=config.shop.rate_usd_per_hr,
        labor_usd=money(labor),
        material_usd=money(material_usd),
        material_cost_is_catalog_estimate=catalog_estimate,
        catalog_values_are_placeholders=placeholders,
        raw_quote_usd=raw,
        quote_low_usd=money(raw * config.shop.band_low),
        quote_high_usd=money(raw * config.shop.band_high),
        min_charge_applied=(material_usd + labor) < min_charge,
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
    )
