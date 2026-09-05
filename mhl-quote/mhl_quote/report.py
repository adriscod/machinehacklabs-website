from __future__ import annotations

import json
from typing import Any, assert_never

from mhl_quote.models import CostBreakdown, EnvelopeCheck, GeometryResult, QuoteResult, QuoteStatus


def render_text(result: QuoteResult, *, material_name: str | None = None) -> str:
    lines = [
        "Machine Hack Labs — LOCAL rough quote (not a formal quote)",
        "==========================================================",
        "Machining-only 3-axis · Tormach 1500MX · no finishes / turning / 5-axis",
        "",
    ]
    if result.geometry is not None:
        lines.extend(_geometry_lines(result.geometry))
        lines.append("")
    if result.envelope is not None:
        lines.extend(_envelope_lines(result.envelope))
        lines.append("")

    if result.status is QuoteStatus.REJECTED:
        lines.append("STATUS: REJECTED — no customer quote range emitted")
        for reason in result.rejection_reasons:
            lines.append(f"  • {reason}")
        lines.append("")
    elif result.status is QuoteStatus.OK:
        lines.append("STATUS: OK — rough range only")
        lines.append("")
    else:
        assert_never(result.status)

    if result.cost is not None:
        lines.extend(_cost_lines(result.cost))
        lines.append("")

    if result.callouts:
        lines.append("CALLOUTS")
        for note in result.callouts:
            lines.append(f"  • {note}")
        lines.append("")

    if result.overrides_applied:
        lines.append("OVERRIDES")
        for key, value in result.overrides_applied.items():
            lines.append(f"  {key}: {value}")
        lines.append("")

    if material_name:
        lines.append(f"(material lookup: {material_name})")

    return "\n".join(lines).rstrip() + "\n"


def result_to_jsonable(result: QuoteResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status.value,
        "rejection_reasons": list(result.rejection_reasons),
        "callouts": list(result.callouts),
        "overrides": result.overrides_applied,
        "geometry": None,
        "envelope": None,
        "cost": None,
    }
    if result.geometry is not None:
        payload["geometry"] = _geometry_json(result.geometry)
    if result.envelope is not None:
        payload["envelope"] = _envelope_json(result.envelope)
    if result.cost is not None:
        payload["cost"] = _cost_json(result.cost)
    return payload


def render_json(result: QuoteResult) -> str:
    return json.dumps(result_to_jsonable(result), indent=2) + "\n"


def _geometry_lines(geo: GeometryResult) -> list[str]:
    b = geo.bbox_in
    return [
        "GEOMETRY",
        f"  File:      {geo.source_path}",
        f"  Format:    {geo.cad_format.value.upper()}  (input units: {geo.input_unit.value})",
        f"  BBox (in): {b.x:.4f} × {b.y:.4f} × {b.z:.4f}",
        f"  Part vol:  {geo.part_volume_in3:.4f} in³",
    ]


def _envelope_lines(env: EnvelopeCheck) -> list[str]:
    u = env.usable_in
    s = env.stock_in
    status = "FITS" if env.fits else "OVER-TRAVEL"
    axes = ",".join(a.value.upper() for a in env.over_travel_axes) or "none"
    return [
        "ENVELOPE  (Tormach 1500MX usable = travel − fixture margin)",
        f"  Stock (in):  {s.x:.4f} × {s.y:.4f} × {s.z:.4f}",
        f"  Usable (in): {u.x:.4f} × {u.y:.4f} × {u.z:.4f}",
        f"  Status:      {status}  (over-travel axes: {axes})",
    ]


def _cost_lines(cost: CostBreakdown) -> list[str]:
    source = "catalog estimate" if cost.material_cost_is_catalog_estimate else "invoice override"
    return [
        "COST MODEL  ($75/hr default · materials pass-through · no scrap adder)",
        f"  Material:   {cost.material_label}  ({source})",
        f"  Stock vol:  {cost.stock_volume_in3:.4f} in³",
        f"  Part vol:   {cost.part_volume_in3:.4f} in³",
        f"  Removal:    {cost.removal_volume_in3:.4f} in³",
        f"  MRR_eff:    {cost.mrr_eff_in3_per_hr:g} in³/hr",
        f"  Setup:      {cost.setup_hours:.4f} hr",
        f"  Cut:        {cost.cut_hours:.4f} hr",
        f"  Labor:      ({cost.setup_hours:.4f} + {cost.cut_hours:.4f}) × "
        f"${cost.shop_rate_usd_per_hr:g}/hr = ${cost.labor_usd:.2f}",
        f"  Materials:  ${cost.material_usd:.2f}",
        f"  Raw:        ${cost.raw_quote_usd:.2f}"
        + ("  (min charge applied)" if cost.min_charge_applied else ""),
        f"  RANGE:      ${cost.quote_low_usd:.2f}  –  ${cost.quote_high_usd:.2f}",
    ]


def _geometry_json(geo: GeometryResult) -> dict[str, Any]:
    return {
        "source": geo.source_path,
        "format": geo.cad_format.value,
        "input_unit": geo.input_unit.value,
        "bbox_in": geo.bbox_in.to_mapping(),
        "part_volume_in3": geo.part_volume_in3,
        "watertight_assumed": geo.watertight_assumed,
        "notes": list(geo.notes),
    }


def _envelope_json(env: EnvelopeCheck) -> dict[str, Any]:
    return {
        "fits": env.fits,
        "usable_in": env.usable_in.to_mapping(),
        "stock_in": env.stock_in.to_mapping(),
        "over_travel_axes": [a.value for a in env.over_travel_axes],
        "rotation_would_fit": env.rotation_would_fit,
        "rotation_note": env.rotation_note,
    }


def _cost_json(cost: CostBreakdown) -> dict[str, Any]:
    return {
        "material_key": cost.material_key,
        "material_label": cost.material_label,
        "stock_volume_in3": cost.stock_volume_in3,
        "part_volume_in3": cost.part_volume_in3,
        "removal_volume_in3": cost.removal_volume_in3,
        "setup_hours": cost.setup_hours,
        "cut_hours": cost.cut_hours,
        "mrr_eff_in3_per_hr": cost.mrr_eff_in3_per_hr,
        "shop_rate_usd_per_hr": cost.shop_rate_usd_per_hr,
        "labor_usd": cost.labor_usd,
        "material_usd": cost.material_usd,
        "material_cost_is_catalog_estimate": cost.material_cost_is_catalog_estimate,
        "raw_quote_usd": cost.raw_quote_usd,
        "quote_low_usd": cost.quote_low_usd,
        "quote_high_usd": cost.quote_high_usd,
        "min_charge_applied": cost.min_charge_applied,
    }
