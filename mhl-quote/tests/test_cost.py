from __future__ import annotations

from pathlib import Path

from mhl_quote.config import load_config
from mhl_quote.cost import compute_cost
from mhl_quote.models import JobOverrides, Vec3

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"


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


def test_qty_scales_cut_and_catalog_material_not_setup() -> None:
    config = load_config(CONFIG)
    material = config.materials["aluminum"]
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
