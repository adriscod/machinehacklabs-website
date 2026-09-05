from __future__ import annotations

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
    """Locked v1 cost model from MHL-CF-001.

    stock_vol = bbox_x * bbox_y * bbox_z   (or overridden stock dims)
    part_vol = solid volume
    removal_vol = max(0, stock_vol - part_vol)
    cut_hours = removal_vol / MRR_eff
    labor = (setup_hours + cut_hours) * shop_rate
    materials = stock_purchase_cost (pass-through; no scrap adder)
    raw_quote = max(materials + labor, min_charge)
    quote_low = raw_quote * band_low
    quote_high = raw_quote * band_high
    """
    overrides = overrides or JobOverrides()
    stock_dims = overrides.stock_dims_in or bbox_in
    stock_vol = max(0.0, stock_dims.volume())
    part_vol = max(0.0, part_volume_in3)
    removal_vol = max(0.0, stock_vol - part_vol)

    mrr = overrides.mrr_eff_in3_per_hr or material.mrr_eff_in3_per_hr
    if mrr <= 0:
        raise ValueError("MRR_eff must be > 0")

    setup = (
        config.shop.setup_hours if overrides.setup_hours is None else overrides.setup_hours
    )
    if setup < 0:
        raise ValueError("setup_hours must be >= 0")

    cut = 0.0 if removal_vol == 0 else removal_vol / mrr
    labor = (setup + cut) * config.shop.rate_usd_per_hr

    if overrides.stock_purchase_cost_usd is not None:
        material_usd = overrides.stock_purchase_cost_usd
        catalog_estimate = False
    else:
        material_usd = stock_vol * material.cost_usd_per_in3
        catalog_estimate = True

    raw = money(max(material_usd + labor, config.shop.min_charge_usd))
    return CostBreakdown(
        material_key=material.key,
        material_label=material.label,
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
        raw_quote_usd=raw,
        quote_low_usd=money(raw * config.shop.band_low),
        quote_high_usd=money(raw * config.shop.band_high),
        min_charge_applied=(material_usd + labor) < config.shop.min_charge_usd,
    )
