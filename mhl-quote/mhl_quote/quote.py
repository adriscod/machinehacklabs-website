from __future__ import annotations

from pathlib import Path

from mhl_quote.config import QuoteConfig, find_material
from mhl_quote.cost import compute_cost
from mhl_quote.filters import (
    check_envelope,
    envelope_rejection_reasons,
    reject_unsupported_processes,
)
from mhl_quote.geometry import measure_file
from mhl_quote.models import (
    JobOverrides,
    LengthUnit,
    QuoteResult,
    QuoteStatus,
    UnsupportedProcess,
    Vec3,
)

STANDING_CALLOUTS = (
    "Machining-only 3-axis mill (Tormach 1500MX). No finishes, turning, or 5-axis.",
    "Materials are pass-through at shop cost. Scrap is absorbed by the shop — not billed.",
    "This is a range, not a single-dollar quote. Calibrate MRR_eff from completed jobs.",
)


def estimate_quote(
    *,
    cad_path: str | Path,
    config: QuoteConfig,
    material_name: str,
    unit: LengthUnit = LengthUnit.INCH,
    overrides: JobOverrides | None = None,
    requested_processes: list[UnsupportedProcess] | None = None,
) -> QuoteResult:
    overrides = overrides or JobOverrides()
    process_reasons = reject_unsupported_processes(requested_processes or [])
    if process_reasons:
        return QuoteResult(
            status=QuoteStatus.REJECTED,
            geometry=None,
            envelope=None,
            cost=None,
            callouts=list(STANDING_CALLOUTS),
            rejection_reasons=process_reasons,
            overrides_applied=_overrides_dict(overrides),
        )

    geometry = measure_file(cad_path, unit)
    stock_dims = overrides.stock_dims_in or geometry.bbox_in
    envelope = check_envelope(config.machine, stock_dims)
    material = find_material(config, material_name)
    cost = compute_cost(
        config=config,
        material=material,
        bbox_in=geometry.bbox_in,
        part_volume_in3=geometry.part_volume_in3,
        overrides=overrides,
    )

    callouts = list(STANDING_CALLOUTS)
    callouts.extend(geometry.notes)
    if overrides.stock_dims_in is None:
        callouts.append(
            "Stock is the part's axis-aligned bounding box (no extra allowance). "
            "Override --stock-x/y/z if buying a larger plate."
        )
    else:
        callouts.append("Stock dimensions were overridden on the command line.")
        if (
            overrides.stock_dims_in.x + 1e-9 < geometry.bbox_in.x
            or overrides.stock_dims_in.y + 1e-9 < geometry.bbox_in.y
            or overrides.stock_dims_in.z + 1e-9 < geometry.bbox_in.z
        ):
            callouts.append(
                "WARNING: overridden stock is smaller than the part AABB on at least one axis."
            )
    if cost.material_cost_is_catalog_estimate:
        callouts.append(
            f"Material $ is a catalog estimate ({material.cost_usd_per_in3:.4f} USD/in³). "
            "Pass --stock-cost with Andrew's actual purchase to pass through the real invoice."
        )
    if overrides.mrr_eff_in3_per_hr is not None:
        callouts.append(f"MRR_eff overridden to {overrides.mrr_eff_in3_per_hr:g} in³/hr.")
    elif material.mrr_typical_low_in3_per_hr and material.mrr_typical_high_in3_per_hr:
        callouts.append(
            f"MRR_eff {material.mrr_eff_in3_per_hr:g} in³/hr is tunable "
            f"(typical {material.family} band "
            f"{material.mrr_typical_low_in3_per_hr:g}–{material.mrr_typical_high_in3_per_hr:g})."
        )
    if overrides.setup_hours is not None:
        callouts.append(f"Setup hours overridden to {overrides.setup_hours:g}.")
    if cost.removal_volume_in3 <= 1e-9:
        callouts.append(
            "Removal volume is ~0 (part fills the stock box). Cut hours will be near zero; "
            "quote is mostly setup + material."
        )
    if envelope.rotation_note:
        callouts.append(envelope.rotation_note)

    rejection = envelope_rejection_reasons(config.machine, envelope)
    status = QuoteStatus.OK if not rejection else QuoteStatus.REJECTED
    return QuoteResult(
        status=status,
        geometry=geometry,
        envelope=envelope,
        cost=None if rejection else cost,
        callouts=callouts,
        rejection_reasons=rejection,
        overrides_applied=_overrides_dict(overrides),
    )


def _overrides_dict(overrides: JobOverrides) -> dict[str, object]:
    applied: dict[str, object] = {}
    if overrides.setup_hours is not None:
        applied["setup_hours"] = overrides.setup_hours
    if overrides.mrr_eff_in3_per_hr is not None:
        applied["mrr_eff_in3_per_hr"] = overrides.mrr_eff_in3_per_hr
    if overrides.stock_dims_in is not None:
        applied["stock_dims_in"] = overrides.stock_dims_in.to_mapping()
    if overrides.stock_purchase_cost_usd is not None:
        applied["stock_purchase_cost_usd"] = overrides.stock_purchase_cost_usd
    return applied
