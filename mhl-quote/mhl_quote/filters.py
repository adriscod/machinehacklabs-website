from __future__ import annotations

from itertools import permutations
from typing import Iterable, assert_never

from mhl_quote.models import (
    Axis,
    EnvelopeCheck,
    MachineConfig,
    UnsupportedProcess,
    Vec3,
)

PROCESS_REJECTION = {
    UnsupportedProcess.FINISH: (
        "Finish services (anodize, paint, plating, bead blast, etc.) are out of scope. "
        "This estimator is machining-only."
    ),
    UnsupportedProcess.FIVE_AXIS: (
        "5-axis work is out of scope. Shop machine is a 3-axis mill."
    ),
    UnsupportedProcess.TURNING: (
        "Turning / lathe work is out of scope. This estimator is 3-axis mill only."
    ),
}


def reject_unsupported_processes(requested: Iterable[UnsupportedProcess]) -> list[str]:
    reasons: list[str] = []
    for process in requested:
        if process is UnsupportedProcess.FINISH:
            reasons.append(PROCESS_REJECTION[process])
        elif process is UnsupportedProcess.FIVE_AXIS:
            reasons.append(PROCESS_REJECTION[process])
        elif process is UnsupportedProcess.TURNING:
            reasons.append(PROCESS_REJECTION[process])
        else:
            assert_never(process)
    return reasons


def check_envelope(machine: MachineConfig, stock_in: Vec3) -> EnvelopeCheck:
    """Hard-flag stock that exceeds usable travel (envelope − fixture margin).

    As-imported AABB is the acceptance check. A 90° axis permutation note is
    informational only — it does not auto-reorient the quote.
    """
    usable = machine.usable_in
    over: list[Axis] = []
    if stock_in.x > usable.x + 1e-9:
        over.append(Axis.X)
    if stock_in.y > usable.y + 1e-9:
        over.append(Axis.Y)
    if stock_in.z > usable.z + 1e-9:
        over.append(Axis.Z)

    rotation_would_fit = False
    rotation_note = None
    if over:
        for perm in permutations(stock_in.as_tuple()):
            if perm[0] <= usable.x + 1e-9 and perm[1] <= usable.y + 1e-9 and perm[2] <= usable.z + 1e-9:
                rotation_would_fit = True
                rotation_note = (
                    f"As-imported stock is over travel, but a 90° axis remapping "
                    f"({perm[0]:.3f} × {perm[1]:.3f} × {perm[2]:.3f} in) would fit "
                    f"usable {usable.x:.3f} × {usable.y:.3f} × {usable.z:.3f} in. "
                    "Re-export or override --stock-* after confirming a fixture plan. "
                    "Quote is still rejected for the as-imported orientation."
                )
                break
        if not rotation_would_fit:
            rotation_note = (
                "No 90° axis remapping fits the mill usable travel. "
                "This job is outside the machine envelope."
            )

    return EnvelopeCheck(
        fits=not over,
        usable_in=usable,
        stock_in=stock_in,
        over_travel_axes=tuple(over),
        rotation_would_fit=rotation_would_fit,
        rotation_note=rotation_note,
    )


def envelope_rejection_reasons(machine: MachineConfig, check: EnvelopeCheck) -> list[str]:
    if check.fits:
        return []
    usable = check.usable_in
    stock = check.stock_in
    bits = []
    for axis in check.over_travel_axes:
        if axis is Axis.X:
            bits.append(f"X stock {stock.x:.3f} in > usable {usable.x:.3f} in")
        elif axis is Axis.Y:
            bits.append(f"Y stock {stock.y:.3f} in > usable {usable.y:.3f} in")
        elif axis is Axis.Z:
            bits.append(f"Z stock {stock.z:.3f} in > usable {usable.z:.3f} in")
        else:
            assert_never(axis)
    detail = "; ".join(bits)
    return [
        f"REJECTED: stock exceeds {machine.name} usable travel "
        f"(envelope minus fixture margin): {detail}."
    ]
