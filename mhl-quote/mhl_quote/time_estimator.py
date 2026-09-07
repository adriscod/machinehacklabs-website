"""Pluggable machining-time estimator seam.

Today the shop estimates cut time from a geometry proxy (removal volume divided
by an effective material-removal rate). This module isolates *how time is
produced* behind a small protocol so a future, higher-fidelity source — e.g. a
Fusion tool library / CAM program that reports real cycle time — can be dropped
in without touching the cost model, quote pipeline, or web app.

`compute_cost` depends only on :class:`TimeEstimator`; swap the implementation and
the rest of the model is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TimeInputs:
    """Everything a time source may want; proxy uses only volume + MRR + setup."""

    removal_volume_in3: float
    mrr_eff_in3_per_hr: float
    part_volume_in3: float
    stock_volume_in3: float
    default_setup_hours: float


@dataclass(frozen=True)
class TimeEstimate:
    setup_hours: float
    cut_hours: float


@runtime_checkable
class TimeEstimator(Protocol):
    def estimate(self, inputs: TimeInputs) -> TimeEstimate:  # pragma: no cover - protocol
        ...


class GeometryProxyTimeEstimator:
    """Default v1 estimator: cut_hours = removal_volume / MRR_eff, flat setup.

    This is the locked MHL-CF-001 proxy. It intentionally ignores tool paths and
    feeds/speeds; calibrate ``mrr_eff_in3_per_hr`` from finished jobs.
    """

    def estimate(self, inputs: TimeInputs) -> TimeEstimate:
        if inputs.mrr_eff_in3_per_hr <= 0:
            raise ValueError("MRR_eff must be > 0")
        removal = max(0.0, inputs.removal_volume_in3)
        cut_hours = 0.0 if removal == 0 else removal / inputs.mrr_eff_in3_per_hr
        return TimeEstimate(setup_hours=inputs.default_setup_hours, cut_hours=cut_hours)


DEFAULT_TIME_ESTIMATOR: TimeEstimator = GeometryProxyTimeEstimator()
