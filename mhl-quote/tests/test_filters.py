from __future__ import annotations

from pathlib import Path

from mhl_quote.config import load_config
from mhl_quote.filters import check_envelope, envelope_rejection_reasons, reject_unsupported_processes
from mhl_quote.models import Axis, UnsupportedProcess, Vec3

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"


def test_over_travel_hard_reject() -> None:
    config = load_config(CONFIG)
    check = check_envelope(config.machine, Vec3(20.0, 1.0, 1.0))
    assert check.fits is False
    assert check.over_travel_axes == (Axis.X,)
    reasons = envelope_rejection_reasons(config.machine, check)
    assert reasons
    assert "REJECTED" in reasons[0]
    assert "X stock" in reasons[0]


def test_fits_inside_usable_travel() -> None:
    config = load_config(CONFIG)
    usable = config.machine.usable_in
    check = check_envelope(config.machine, Vec3(usable.x, usable.y, usable.z))
    assert check.fits is True
    assert envelope_rejection_reasons(config.machine, check) == []


def test_fixture_margin_shrinks_usable() -> None:
    config = load_config(CONFIG)
    # Envelope X is 19.7; margin 0.5 → usable 19.2. A 19.5 in bar fails.
    check = check_envelope(config.machine, Vec3(19.5, 1.0, 1.0))
    assert check.fits is False
    assert Axis.X in check.over_travel_axes


def test_rotation_note_when_remap_would_fit() -> None:
    config = load_config(CONFIG)
    # 15 in exceeds usable Z (13.5) and Y (13.3) but fits usable X (19.2).
    check = check_envelope(config.machine, Vec3(1.0, 1.0, 15.0))
    assert check.fits is False
    assert Axis.Z in check.over_travel_axes
    assert check.rotation_would_fit is True
    assert check.rotation_note is not None
    assert "90°" in check.rotation_note


def test_unsupported_processes_are_rejected() -> None:
    reasons = reject_unsupported_processes(
        [
            UnsupportedProcess.FINISH,
            UnsupportedProcess.FIVE_AXIS,
            UnsupportedProcess.TURNING,
        ]
    )
    assert len(reasons) == 3
    joined = " ".join(reasons).lower()
    assert "finish" in joined
    assert "5-axis" in joined
    assert "turning" in joined
