from __future__ import annotations

from pathlib import Path

from mhl_quote.config import load_config
from mhl_quote.cost import compute_cost
from mhl_quote.models import JobOverrides, MaterialClass, Timeline, Vec3

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"

# Clean geometry used across the driver tests: stock 4×2×2 = 16 in³, part 4 in³,
# removal 12 in³ at aluminum MRR 12 → cut 1.0 hr, plus 1.0 setup hr.
CLEAN_BBOX = Vec3(4, 2, 2)
CLEAN_PART = 4.0


def test_locked_cost_model_aluminum_hand_calc() -> None:
    config = load_config(CONFIG)
    material = config.materials["aluminum"]
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
    material = config.materials["aluminum"]
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
    material = config.materials["steel"]
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


def test_no_scrap_multiplier() -> None:
    config = load_config(CONFIG)
    material = config.materials["aluminum"]
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
    aluminum = config.materials["aluminum"]
    # 2.0 labor hr, material 16*0.35 = 5.60.
    std = _clean(config, aluminum)
    assert std.rush_applied is False
    assert std.shop_rate_usd_per_hr == 75
    assert std.labor_usd == 150.00  # 2.0 hr * 75
    assert std.per_part_raw_usd == 155.60

    rush = _clean(config, aluminum, timeline=Timeline.RUSH)
    assert rush.rush_applied is True
    assert rush.shop_rate_usd_per_hr == 125
    assert rush.labor_usd == 250.00  # 2.0 hr * 125
    assert rush.per_part_raw_usd == 255.60
    assert rush.quote_high_usd == 319.50
    assert rush.quote_high_usd > std.quote_high_usd


def test_tight_tolerance_callout_adders() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["aluminum"]
    one = _clean(config, aluminum, tight_callouts=1)
    assert one.tight_callouts == 1
    assert one.tolerance_labor_usd == 125.00  # 1st callout = 1 hr @ 125
    assert one.labor_usd == 275.00  # 150 base + 125 tolerance
    assert one.shop_rate_usd_per_hr == 75  # base labor still standard

    three = _clean(config, aluminum, tight_callouts=3)
    # 125 + 93.75 * 2 = 312.50
    assert three.tolerance_labor_usd == 312.50
    assert three.labor_usd == 462.50


def test_whole_part_tight_bills_all_labor_at_rush() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["aluminum"]
    whole = _clean(config, aluminum, whole_part_tight=True, tight_callouts=5)
    assert whole.whole_part_tight is True
    assert whole.shop_rate_usd_per_hr == 125
    assert whole.tolerance_labor_usd == 0.0  # per-callout adders drop out
    assert whole.labor_usd == 250.00  # 2.0 hr * 125


def test_quantity_amortizes_setup() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["aluminum"]
    batch = _clean(config, aluminum, quantity=4)
    assert batch.quantity == 4
    assert batch.effective_qty == 4
    # per-part hours = 1/4 setup + 1 cut = 1.25 → labor 93.75; +5.60 material.
    assert batch.per_part_labor_usd == 93.75
    assert batch.per_part_raw_usd == 99.35
    assert batch.batch_total_usd == 397.40
    assert batch.raw_quote_usd == 397.40
    # Per-part price must fall versus a single part (155.60).
    assert batch.per_part_raw_usd < 155.60
    assert batch.guardrail_callout is None


def test_quantity_cap_guardrail_fires() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["aluminum"]
    capped = _clean(config, aluminum, quantity=150)  # default max_amortization_qty = 100
    assert capped.effective_qty == 100
    assert capped.amortization_capped is True
    assert capped.guardrail_callout is not None
    assert "capped" in capped.guardrail_callout


def test_min_charge_floor_guardrail_fires() -> None:
    config = load_config(CONFIG)
    aluminum = config.materials["aluminum"]
    tiny = compute_cost(
        config=config,
        material=aluminum,
        bbox_in=Vec3(0.2, 0.2, 0.2),
        part_volume_in3=0.008,
        overrides=JobOverrides(setup_hours=0.0, stock_purchase_cost_usd=0.0, quantity=5),
    )
    assert tiny.min_charge_applied is True
    assert tiny.per_part_raw_usd == 75.00
    assert tiny.batch_total_usd == 375.00
    assert tiny.guardrail_callout is not None
    assert "floor" in tiny.guardrail_callout


def test_material_class_thresholds_and_plastic_catalog() -> None:
    config = load_config(CONFIG)
    assert config.tolerances.standard_for(MaterialClass.METAL) == 0.005
    assert config.tolerances.standard_for(MaterialClass.PLASTIC) == 0.010
    assert config.materials["aluminum"].material_class is MaterialClass.METAL
    assert config.materials["delrin"].material_class is MaterialClass.PLASTIC
