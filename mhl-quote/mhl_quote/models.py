from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, assert_never


class LengthUnit(str, Enum):
    INCH = "inch"
    MM = "mm"


class CadFormat(str, Enum):
    STEP = "step"
    STL = "stl"


class MaterialClass(str, Enum):
    METAL = "metal"
    PLASTIC = "plastic"


class Timeline(str, Enum):
    STANDARD = "standard"
    RUSH = "rush"


class QuoteStatus(str, Enum):
    OK = "ok"
    REJECTED = "rejected"


class UnsupportedProcess(str, Enum):
    FINISH = "finish"
    FIVE_AXIS = "five_axis"
    TURNING = "turning"


class Axis(str, Enum):
    X = "x"
    Y = "y"
    Z = "z"


MM_PER_INCH = 25.4
IN3_PER_MM3 = 1.0 / (MM_PER_INCH**3)


def linear_to_inches(value: float, unit: LengthUnit) -> float:
    if unit is LengthUnit.INCH:
        return value
    if unit is LengthUnit.MM:
        return value / MM_PER_INCH
    assert_never(unit)


def volume_to_in3(value: float, unit: LengthUnit) -> float:
    if unit is LengthUnit.INCH:
        return value
    if unit is LengthUnit.MM:
        return value * IN3_PER_MM3
    assert_never(unit)


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def volume(self) -> float:
        return max(0.0, self.x) * max(0.0, self.y) * max(0.0, self.z)

    def to_mapping(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class MaterialSpec:
    key: str
    label: str
    family: str
    aliases: tuple[str, ...]
    mrr_eff_in3_per_hr: float
    mrr_typical_low_in3_per_hr: float
    mrr_typical_high_in3_per_hr: float
    cost_usd_per_in3: float
    material_class: MaterialClass = MaterialClass.METAL


@dataclass(frozen=True)
class ShopConfig:
    rate_usd_per_hr: float
    setup_hours: float
    min_charge_usd: float
    band_low: float
    band_high: float
    # Rush jobs bill every labor hour at this elevated rate instead of `rate_usd_per_hr`.
    rush_rate_usd_per_hr: float = 125.0
    # Per-part floor. A batch never prices any single part below this.
    min_charge_per_part_usd: float = 75.0
    # Cap on the setup divisor: past this quantity, setup no longer amortizes further,
    # which is the point where batch pricing stops being advantageous.
    max_amortization_qty: int = 100


@dataclass(frozen=True)
class ToleranceConfig:
    """Tight-tolerance cost rules (labor only; materials still pass through).

    Standard quality is material-class dependent. A callout is "tight" when its
    tolerance is smaller (tighter) than the standard for the part's material class.
    """

    standard_in_metal: float = 0.005
    standard_in_plastic: float = 0.010
    # First tight callout costs one hour at this rate (defaults to the rush rate).
    tight_first_hour_rate_usd: float = 125.0
    # Each additional tight callout bills one hour at rate * (1 + uplift_pct/100).
    additional_uplift_pct: float = 25.0
    hours_per_callout: float = 1.0

    def standard_for(self, material_class: MaterialClass) -> float:
        if material_class is MaterialClass.METAL:
            return self.standard_in_metal
        if material_class is MaterialClass.PLASTIC:
            return self.standard_in_plastic
        assert_never(material_class)


@dataclass(frozen=True)
class MachineConfig:
    name: str
    axes: int
    envelope_in: Vec3
    fixture_margin_in: Vec3

    @property
    def usable_in(self) -> Vec3:
        return Vec3(
            x=self.envelope_in.x - self.fixture_margin_in.x,
            y=self.envelope_in.y - self.fixture_margin_in.y,
            z=self.envelope_in.z - self.fixture_margin_in.z,
        )


@dataclass(frozen=True)
class QuoteConfig:
    shop: ShopConfig
    machine: MachineConfig
    materials: Mapping[str, MaterialSpec]
    source_path: str
    tolerances: ToleranceConfig = field(default_factory=ToleranceConfig)


@dataclass(frozen=True)
class GeometryResult:
    source_path: str
    cad_format: CadFormat
    input_unit: LengthUnit
    bbox_in: Vec3
    part_volume_in3: float
    watertight_assumed: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobOverrides:
    setup_hours: float | None = None
    mrr_eff_in3_per_hr: float | None = None
    stock_dims_in: Vec3 | None = None
    stock_purchase_cost_usd: float | None = None
    # Quote drivers (default to a single standard-tolerance part).
    quantity: int = 1
    timeline: Timeline = Timeline.STANDARD
    tight_callouts: int = 0
    whole_part_tight: bool = False
    material_on_shelf: bool = False


@dataclass(frozen=True)
class EnvelopeCheck:
    fits: bool
    usable_in: Vec3
    stock_in: Vec3
    over_travel_axes: tuple[Axis, ...]
    rotation_would_fit: bool
    rotation_note: str | None = None


@dataclass(frozen=True)
class CostBreakdown:
    material_key: str
    material_label: str
    stock_volume_in3: float
    part_volume_in3: float
    removal_volume_in3: float
    setup_hours: float
    cut_hours: float
    mrr_eff_in3_per_hr: float
    shop_rate_usd_per_hr: float
    labor_usd: float
    material_usd: float
    material_cost_is_catalog_estimate: bool
    raw_quote_usd: float
    quote_low_usd: float
    quote_high_usd: float
    min_charge_applied: bool
    # Quote-driver detail (rush / tight tolerance / quantity amortization).
    quantity: int = 1
    effective_qty: int = 1
    rush_applied: bool = False
    tight_callouts: int = 0
    whole_part_tight: bool = False
    tolerance_labor_usd: float = 0.0
    per_part_labor_usd: float = 0.0
    per_part_material_usd: float = 0.0
    per_part_raw_usd: float = 0.0
    per_part_low_usd: float = 0.0
    per_part_high_usd: float = 0.0
    batch_total_usd: float = 0.0
    amortization_capped: bool = False
    material_on_shelf: bool = False
    guardrail_callout: str | None = None


@dataclass
class QuoteResult:
    status: QuoteStatus
    geometry: GeometryResult | None
    envelope: EnvelopeCheck | None
    cost: CostBreakdown | None
    callouts: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    overrides_applied: dict[str, object] = field(default_factory=dict)
