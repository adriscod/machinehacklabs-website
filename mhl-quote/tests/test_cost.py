from __future__ import annotations

from pathlib import Path

from mhl_quote.config import load_config
from mhl_quote.cost import compute_cost, money
from mhl_quote.models import JobOverrides, MaterialClass, Turnaround, Vec3
from mhl_quote.time_estimator import GeometryProxyTimeEstimator, TimeEstimate, TimeInputs

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"

# Clean geometry: stock 4×2×2 = 16 in³, part 4 in³, removal 12 in³ at
# aluminum MRR 12 → cut 1.0 hr, plus 1.0 setup hr.
CLEAN_BBOX = Vec3(4, 2, 2)
CLEAN_PART = 4.0


def test_locked_cost_model_aluminum_hand_calc() -> None:
    config = load_config(CONFIG)
    material = config.materials["al_6061"]
    # stock 4×3×1 = 12 in³; part 4 in³; removal 8
    # MRR 12 → cut 8/12 = 0.6667 hr
    # labor (1 + 0.666666...) * 75 = 125
    # materials 12 * 0.35 = 4.20
    # raw 129.20; low 109.82; high 161.50
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(4, 3, 1),
        part_volume_in3=4.0,
    )
    assert cost.stock_volume_in3 == 12.0
    assert cost.part_volume_in3 == 4.0
    assert cost.removal_volume_in3 == 8.0
    assert cost.cut_hours == 0.6667
    assert cost.setup_hours == 1.0
    assert cost.shop_rate_usd_per_hr == 75
    assert cost.labor_usd == 125.00
    assert cost.material_usd == 4.20
    assert cost.material_cost_is_catalog_estimate is True
    assert cost.raw_quote_usd == 129.20
    assert cost.quote_low_usd == 109.82
    assert cost.quote_high_usd == 161.50
    assert cost.min_charge_applied is False
    assert cost.quote_low_usd < cost.raw_quote_usd < cost.quote_high_usd


def test_min_charge_and_zero_removal() -> None:
    config = load_config(CONFIG)
    material = config.materials["al_6061"]
    # 0.5×0.5×0.5 solid = stock 0.125; part 0.125; removal 0
    # labor = 1 * 75 = 75; materials = 0.125 * 0.35 = 0.04375 → 0.04
    # raw = max(75.04, 75) = 75.04
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(0.5, 0.5, 0.5),
        part_volume_in3=0.125,
    )
    assert cost.removal_volume_in3 == 0.0
    assert cost.cut_hours == 0.0
    assert cost.min_charge_applied is False
    assert cost.raw_quote_usd == 75.04

    # Force a below-minimum job via zero setup and free stock.
    cheap = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(0.2, 0.2, 0.2),
        part_volume_in3=0.008,
        overrides=JobOverrides(setup_hours=0.0, stock_purchase_cost_usd=0.0),
    )
    assert cheap.min_charge_applied is True
    assert cheap.raw_quote_usd == 75.00
    assert cheap.quote_low_usd == 63.75
    assert cheap.quote_high_usd == 93.75


def test_overrides_stock_mrr_setup_and_invoice() -> None:
    config = load_config(CONFIG)
    material = config.materials["steel_1018"]
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(2, 2, 1),
        part_volume_in3=1.0,
        overrides=JobOverrides(
            setup_hours=2.0,
            mrr_eff_in3_per_hr=4.0,
            stock_dims_in=Vec3(3, 2, 1),
            stock_purchase_cost_usd=18.50,
        ),
    )
    # stock 6 in³, part 1, removal 5, cut 5/4 = 1.25
    # labor (2 + 1.25) * 75 = 243.75
    # materials 18.50 (invoice, not catalog)
    # raw 262.25; low 222.91; high 327.81
    assert cost.stock_volume_in3 == 6.0
    assert cost.removal_volume_in3 == 5.0
    assert cost.cut_hours == 1.25
    assert cost.labor_usd == 243.75
    assert cost.material_usd == 18.50
    assert cost.material_cost_is_catalog_estimate is False
    assert cost.raw_quote_usd == 262.25
    assert cost.quote_low_usd == 222.91
    assert cost.quote_high_usd == 327.81


def test_qty_scales_cut_and_catalog_material_not_setup() -> None:
    config = load_config(CONFIG)
    material = config.materials["al_6061"]
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(4, 3, 1),
        part_volume_in3=4.0,
        overrides=JobOverrides(qty=3),
    )
    # one setup; cut 8/12 * 3 = 2.0 hr; labor 225; mat 12.60; raw 237.60
    assert cost.cut_hours == 2.0
    assert cost.setup_hours == 1.0
    assert cost.labor_usd == 225.00
    assert cost.material_usd == 12.60
    assert cost.raw_quote_usd == 237.60
    assert cost.quote_low_usd == 201.96
    assert cost.quote_high_usd == 297.00


def test_money_rounds_half_away_from_zero() -> None:
    # Matches JS Math.round; Python banker's rounding would yield 215.62.
    assert money(215.625) == 215.63
    assert money(129.20) == 129.20


def test_no_scrap_multiplier() -> None:
    config = load_config(CONFIG)
    material = config.materials["al_6061"]
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=Vec3(2, 1, 1),
        part_volume_in3=1.0,
    )
    assert cost.material_usd == 0.70  # 2 in³ * 0.35, nothing extra for chips


def _clean(config, material, **override_kwargs):
    return compute_cost(
        config=config,
        material=material,
        bbox_in=CLEAN_BBOX,
        part_volume_in3=CLEAN_PART,
        overrides=JobOverrides(**override_kwargs) if override_kwargs else None,
    )


def test_rush_rate_elevates_all_labor() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]
    std = _clean(config, aluminum)
    assert std.rush_applied is False
    assert std.shop_rate_usd_per_hr == 75
    assert std.labor_usd == 150.00  # 2.0 hr * 75
    assert std.per_part_raw_usd == 155.60

    rush = _clean(config, aluminum, turnaround=Turnaround.RUSH)
    assert rush.rush_applied is True
    assert rush.shop_rate_usd_per_hr == 125
    assert rush.setup_hours == 1.25
    assert rush.labor_usd == 281.25  # (1.25 + 1.0) * 125
    assert rush.per_part_raw_usd == 286.85
    assert rush.quote_high_usd > std.quote_high_usd


def test_tight_tolerance_callout_adders() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]
    one = _clean(config, aluminum, tight_callouts=1)
    assert one.tight_callouts == 1
    assert one.tolerance_labor_usd == 125.00  # 1st callout = 1 hr @ 125
    assert one.labor_usd == 275.00  # 150 base + 125 tolerance
    assert one.shop_rate_usd_per_hr == 75  # base labor still standard

    three = _clean(config, aluminum, tight_callouts=3)
    assert three.tolerance_labor_usd == 312.50  # 125 + 93.75 * 2
    assert three.labor_usd == 462.50


def test_whole_part_tight_bills_all_labor_at_rush() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]
    whole = _clean(config, aluminum, whole_part_tight=True, tight_callouts=5)
    assert whole.whole_part_tight is True
    assert whole.shop_rate_usd_per_hr == 125
    assert whole.tolerance_labor_usd == 0.0
    assert whole.labor_usd == 250.00  # 2.0 hr * 125


def test_quantity_cap_guardrail_fires() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]
    capped = _clean(config, aluminum, qty=150)
    assert capped.effective_qty == 100
    assert capped.amortization_capped is True
    assert capped.guardrail_callout is not None
    assert "capped" in capped.guardrail_callout


def test_min_charge_floor_guardrail_fires() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]
    tiny = compute_cost(
        config=config,
        material=aluminum,
        bbox_in=Vec3(0.2, 0.2, 0.2),
        part_volume_in3=0.008,
        overrides=JobOverrides(setup_hours=0.0, stock_purchase_cost_usd=0.0, qty=5),
    )
    assert tiny.min_charge_applied is True
    assert tiny.per_part_raw_usd == 75.00
    assert tiny.raw_quote_usd == 375.00
    assert tiny.guardrail_callout is not None
    assert "floor" in tiny.guardrail_callout


def test_material_class_thresholds_and_plastic_catalog() -> None:
    config = load_config(CONFIG)
    assert config.tolerances.standard_for(MaterialClass.METAL) == 0.005
    assert config.tolerances.standard_for(MaterialClass.PLASTIC) == 0.010
    assert config.materials["al_6061"].material_class is MaterialClass.METAL
    assert config.materials["delrin"].material_class is MaterialClass.PLASTIC


def test_time_estimator_seam_is_pluggable() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["al_6061"]

    class FixedTime:
        def estimate(self, inputs: TimeInputs) -> TimeEstimate:
            assert inputs.mrr_eff_in3_per_hr > 0
            return TimeEstimate(setup_hours=2.0, cut_hours=0.5)

    cost = compute_cost(
        config=config,
        material=aluminum,
        bbox_in=CLEAN_BBOX,
        part_volume_in3=CLEAN_PART,
        time_estimator=FixedTime(),
    )
    assert cost.setup_hours == 2.0
    assert cost.cut_hours == 0.5
    assert cost.labor_usd == 187.50  # 2.5 hr * 75
    assert isinstance(GeometryProxyTimeEstimator(), GeometryProxyTimeEstimator)
