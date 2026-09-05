from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Mapping, assert_never


class LengthUnit(str, Enum):
    INCH = "inch"
    MM = "mm"


class CadFormat(str, Enum):
    STEP = "step"
    STL = "stl"


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


class MaterialSource(str, Enum):
    SHOP_BUYS = "shop_buys"
    CUSTOMER_SUPPLIED = "customer_supplied"


class Turnaround(str, Enum):
    STANDARD = "standard"
    RUSH = "rush"
    EMERGENCY = "emergency"


class ToleranceClass(str, Enum):
    STANDARD = "standard"
    TIGHT = "tight"
    PRECISION = "precision"


class FeatureRisk(str, Enum):
    DEEP_POCKETS = "deep_pockets"
    THIN_WALLS = "thin_walls"
    FINE_ENGRAVING = "fine_engraving"
    MANY_HOLES = "many_holes"


MM_PER_INCH = 25.4
IN3_PER_MM3 = 1.0 / (MM_PER_INCH**3)

TURNAROUND_RANK = {
    Turnaround.STANDARD: 0,
    Turnaround.RUSH: 1,
    Turnaround.EMERGENCY: 2,
}


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
    enabled: bool = True
    cost_is_placeholder: bool = True
    mrr_is_placeholder: bool = True


@dataclass(frozen=True)
class ShopConfig:
    rate_usd_per_hr: float
    setup_hours: float
    min_charge_usd: float
    band_low: float
    band_high: float


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
class TurnaroundTier:
    key: Turnaround
    labor_mult: float
    setup_mult: float
    min_business_days: int


@dataclass(frozen=True)
class FeatureRiskConfig:
    keys: tuple[FeatureRisk, ...]
    mult_each: float
    mult_cap: float


@dataclass(frozen=True)
class ToleranceConfig:
    multipliers: Mapping[ToleranceClass, float]
    precision_requires_shop_review: bool


@dataclass(frozen=True)
class QuoteConfig:
    shop: ShopConfig
    machine: MachineConfig
    materials: Mapping[str, MaterialSpec]
    turnaround: Mapping[Turnaround, TurnaroundTier]
    tolerance: ToleranceConfig
    feature_risks: FeatureRiskConfig
    source_path: str
    meta: Mapping[str, object] = field(default_factory=dict)


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
    qty: int = 1
    setups: int = 1
    material_source: MaterialSource = MaterialSource.SHOP_BUYS
    turnaround: Turnaround = Turnaround.STANDARD
    tolerance_class: ToleranceClass = ToleranceClass.STANDARD
    feature_risks: tuple[FeatureRisk, ...] = ()
    due_date: date | None = None
    as_of_date: date | None = None


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
    material_family: str
    material_source: MaterialSource
    qty: int
    setups: int
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
    catalog_values_are_placeholders: bool
    raw_quote_usd: float
    quote_low_usd: float
    quote_high_usd: float
    min_charge_applied: bool
    turnaround_requested: Turnaround
    turnaround_applied: Turnaround
    turnaround_bumped: bool
    rush_labor_mult: float
    rush_setup_mult: float
    tolerance_class: ToleranceClass
    feature_risks: tuple[FeatureRisk, ...]
    complexity_mult: float
    due_date: date | None
    as_of_date: date | None
    due_date_business_days: int | None
    due_date_warning: str | None
    shop_review_required: bool
    shop_review_reasons: tuple[str, ...]


@dataclass
class QuoteResult:
    status: QuoteStatus
    geometry: GeometryResult | None
    envelope: EnvelopeCheck | None
    cost: CostBreakdown | None
    callouts: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    overrides_applied: dict[str, object] = field(default_factory=dict)
    shop_review_required: bool = False
    shop_review_reasons: list[str] = field(default_factory=list)
