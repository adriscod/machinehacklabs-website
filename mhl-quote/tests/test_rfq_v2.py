from __future__ import annotations

from datetime import date
from pathlib import Path

from mhl_quote.config import enabled_materials, find_material, load_config
from mhl_quote.cost import compute_cost
from mhl_quote.job_inputs import business_days_until, shop_payload_from_cost
from mhl_quote.models import (
    FeatureRisk,
    JobOverrides,
    MaterialSource,
    ToleranceClass,
    Turnaround,
    Vec3,
)

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"
BBOX = Vec3(4, 3, 1)
PART = 4.0


def _al6061():
    config = load_config(CONFIG)
    return config, config.materials["al_6061"]


def test_catalog_has_required_grades_and_placeholder_flags() -> None:
    config = load_config(CONFIG)
    required = {
        "al_6061",
        "al_7075",
        "steel_1018",
        "steel_4340",
        "steel_4140",
        "ss_303",
        "ss_304",
        "ss_316",
        "delrin",
        "nylon",
        "uhmw",
        "acrylic",
        "pvc",
    }
    assert required <= set(config.materials)
    for spec in enabled_materials(config):
        assert spec.label
        assert spec.family
        assert spec.cost_usd_per_in3 >= 0
        assert spec.mrr_eff_in3_per_hr > 0
        assert spec.cost_is_placeholder is True
        assert spec.mrr_is_placeholder is True
        assert spec.enabled is True
    assert find_material(config, "ss").key == "ss_304"
    assert find_material(config, "4340").key == "steel_4340"


def test_rush_vs_standard_hand_calc() -> None:
    config, material = _al6061()
    standard = compute_cost(config=config, material=material, bbox_in=BBOX, part_volume_in3=PART)
    rush = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(turnaround=Turnaround.RUSH),
    )
    # standard: cut 8/12, setup 1, labor 125, mat 4.20, raw 129.20
    assert standard.cut_hours == 0.6667
    assert standard.setup_hours == 1.0
    assert standard.rush_labor_mult == 1.0
    assert standard.rush_setup_mult == 1.0
    assert standard.labor_usd == 125.00
    assert standard.material_usd == 4.20
    assert standard.raw_quote_usd == 129.20

    # rush: setup 1*1*1.25=1.25; cut 0.6666…; labor (1.25+8/12)*75*1.5 = 215.63
    assert rush.setup_hours == 1.25
    assert rush.cut_hours == 0.6667
    assert rush.rush_labor_mult == 1.5
    assert rush.rush_setup_mult == 1.25
    assert rush.labor_usd == 215.63
    assert rush.material_usd == 4.20
    assert rush.raw_quote_usd == 219.83
    assert rush.quote_low_usd == 186.86
    assert rush.quote_high_usd == 274.79
    assert rush.raw_quote_usd > standard.raw_quote_usd


def test_customer_supplied_material_is_zero() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(material_source=MaterialSource.CUSTOMER_SUPPLIED),
    )
    assert cost.material_usd == 0.0
    assert cost.material_cost_is_catalog_estimate is False
    assert cost.labor_usd == 125.00
    assert cost.raw_quote_usd == 125.00
    assert cost.quote_low_usd == 106.25
    assert cost.quote_high_usd == 156.25


def test_qty_times_setups_scales_cut_and_setup() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(qty=3, setups=2),
    )
    # cut (8/12)*3*1.0 = 2.0; setup 1*2*1.0 = 2.0; labor 300; mat 12.60; raw 312.60
    assert cost.cut_hours == 2.0
    assert cost.setup_hours == 2.0
    assert cost.labor_usd == 300.00
    assert cost.material_usd == 12.60
    assert cost.raw_quote_usd == 312.60


def test_tight_tolerance_scales_cut_hours() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(tolerance_class=ToleranceClass.TIGHT),
    )
    assert cost.complexity_mult == 1.25
    assert cost.cut_hours == 0.8333
    assert cost.setup_hours == 1.0
    assert cost.labor_usd == 137.50
    assert cost.material_usd == 4.20
    assert cost.raw_quote_usd == 141.70
    assert cost.shop_review_required is False


def test_precision_and_feature_risks_cap_and_review() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(
            tolerance_class=ToleranceClass.PRECISION,
            feature_risks=(
                FeatureRisk.DEEP_POCKETS,
                FeatureRisk.THIN_WALLS,
                FeatureRisk.FINE_ENGRAVING,
                FeatureRisk.MANY_HOLES,
            ),
        ),
    )
    # 1.5 + 4*0.15 = 2.1 → cap 1.75
    assert cost.complexity_mult == 1.75
    assert cost.shop_review_required is True
    assert any("precision" in r for r in cost.shop_review_reasons)


def test_due_date_bumps_standard_to_rush() -> None:
    config, material = _al6061()
    as_of = date(2026, 9, 8)  # Tuesday
    due = date(2026, 9, 14)  # Monday → 4 business days
    assert business_days_until(as_of, due) == 4
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(
            turnaround=Turnaround.STANDARD,
            due_date=due,
            as_of_date=as_of,
        ),
    )
    assert cost.turnaround_requested is Turnaround.STANDARD
    assert cost.turnaround_applied is Turnaround.RUSH
    assert cost.turnaround_bumped is True
    assert cost.rush_labor_mult == 1.5
    assert cost.shop_review_required is True
    assert cost.due_date_warning is not None


def test_due_date_standard_lead_is_not_bumped() -> None:
    config, material = _al6061()
    as_of = date(2026, 9, 8)
    due = date(2026, 9, 22)  # 10 business days
    assert business_days_until(as_of, due) == 10
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(
            turnaround=Turnaround.STANDARD,
            due_date=due,
            as_of_date=as_of,
        ),
    )
    assert cost.turnaround_applied is Turnaround.STANDARD
    assert cost.turnaround_bumped is False
    assert cost.rush_labor_mult == 1.0


def test_stock_override_replaces_aabb() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(stock_dims_in=Vec3(5, 4, 2)),
    )
    assert cost.stock_volume_in3 == 40.0
    assert cost.removal_volume_in3 == 36.0


def test_shop_payload_includes_v2_keys() -> None:
    config, material = _al6061()
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=BBOX,
        part_volume_in3=PART,
        overrides=JobOverrides(
            material_source=MaterialSource.CUSTOMER_SUPPLIED,
            turnaround=Turnaround.EMERGENCY,
            setups=2,
            tolerance_class=ToleranceClass.TIGHT,
            feature_risks=(FeatureRisk.THIN_WALLS,),
        ),
    )
    payload = shop_payload_from_cost(cost)
    assert payload["material_key"] == "al_6061"
    assert payload["material_family"] == "aluminum"
    assert payload["material_source"] == "customer_supplied"
    assert payload["turnaround"] == "emergency"
    assert payload["setups"] == 2
    assert payload["tolerance_class"] == "tight"
    assert payload["feature_risks"] == "thin_walls"
    assert payload["complexity_mult"] == 1.4
    assert payload["catalog_values_are_placeholders"] == "yes"
