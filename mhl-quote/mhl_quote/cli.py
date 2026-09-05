from __future__ import annotations

import argparse
import sys
from typing import assert_never

from mhl_quote.config import ConfigError, QuoteConfig, find_material, load_config
from mhl_quote.geometry import GeometryError
from mhl_quote.job_inputs import (
    JobInputError,
    parse_feature_risks,
    parse_iso_date,
    parse_material_source,
    parse_tolerance_class,
    parse_turnaround,
)
from mhl_quote.models import JobOverrides, LengthUnit, QuoteStatus, UnsupportedProcess, Vec3
from mhl_quote.quote import estimate_quote
from mhl_quote.report import render_json, render_text

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REJECTED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mhl-quote",
        description=(
            "Local rough-quote estimator: STEP/STL → AABB stock − part volume → "
            "removal → hours at the configured shop rate + material pass-through. "
            "Always prints a range. Machining-only 3-axis (Tormach 1500MX)."
        ),
        epilog=(
            "Calibration helper only. Customer RFQs go through the website form "
            "to quotes@machinehacklabs.com. Do not use this tool for finishes, "
            "turning, or 5-axis."
        ),
    )
    parser.add_argument(
        "cad_file",
        nargs="?",
        help="Path to a .step/.stp (preferred) or .stl file",
    )
    parser.add_argument(
        "--config",
        help="YAML or JSON config (default: mhl-quote/config/quote.yaml)",
    )
    parser.add_argument(
        "--material",
        default="aluminum",
        help="Catalog key or alias (default: aluminum). Use --list-materials to see the catalog.",
    )
    parser.add_argument(
        "--units",
        choices=("inch", "mm"),
        default="inch",
        help="Units of the CAD file (STL is unitless; STEP is often mm). Default: inch.",
    )
    parser.add_argument(
        "--setup-hours",
        type=float,
        default=None,
        help="Override default setup hours from config",
    )
    parser.add_argument(
        "--mrr",
        type=float,
        default=None,
        metavar="IN3_PER_HR",
        help="Override MRR_eff (in³/hr)",
    )
    parser.add_argument(
        "--stock-x",
        type=float,
        default=None,
        help="Override stock X (inches)",
    )
    parser.add_argument(
        "--stock-y",
        type=float,
        default=None,
        help="Override stock Y (inches)",
    )
    parser.add_argument(
        "--stock-z",
        type=float,
        default=None,
        help="Override stock Z (inches)",
    )
    parser.add_argument(
        "--stock-cost",
        type=float,
        default=None,
        metavar="USD",
        help="Actual stock purchase (pass-through). Replaces catalog $/in³ estimate.",
    )
    parser.add_argument(
        "--qty",
        type=int,
        default=1,
        help="Quantity (cut hours and catalog material scale)",
    )
    parser.add_argument(
        "--setups",
        type=int,
        default=1,
        help="Number of setups (min 1). Scales setup hours.",
    )
    parser.add_argument(
        "--material-source",
        choices=("shop_buys", "customer_supplied"),
        default="shop_buys",
        help="Who supplies stock. customer_supplied → material $ = 0.",
    )
    parser.add_argument(
        "--turnaround",
        choices=("standard", "rush", "emergency"),
        default="standard",
        help="Lead tier (rush/emergency multipliers are starting points in YAML).",
    )
    parser.add_argument(
        "--due-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Need-by date. If tighter than --turnaround, the tier is auto-bumped.",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="As-of date for due-date business-day math (default: today).",
    )
    parser.add_argument(
        "--tolerance",
        choices=("standard", "tight", "precision"),
        default="standard",
        help="Tolerance class (precision forces shop_review_required).",
    )
    parser.add_argument(
        "--feature-risk",
        action="append",
        default=[],
        metavar="RISK",
        help=(
            "Optional feature risk (repeatable): deep_pockets, thin_walls, "
            "fine_engraving, many_holes. Each adds ~0.15 to complexity_mult."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the human summary",
    )
    parser.add_argument(
        "--list-materials",
        action="store_true",
        help="Print the material catalog from config and exit",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print resolved tunables and exit",
    )

    # Present so a mistaken request is an explicit hard reject, not a silent quote.
    reject = parser.add_argument_group(
        "unsupported (hard reject — these do not produce a quote)"
    )
    reject.add_argument(
        "--finish",
        action="store_true",
        help="Rejected: finish services are out of scope",
    )
    reject.add_argument(
        "--five-axis",
        "--5-axis",
        dest="five_axis",
        action="store_true",
        help="Rejected: 5-axis is out of scope",
    )
    reject.add_argument(
        "--turning",
        "--lathe",
        dest="turning",
        action="store_true",
        help="Rejected: turning is out of scope",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.list_materials:
        _print_materials(config)
        return EXIT_OK
    if args.show_config:
        _print_config(config)
        return EXIT_OK

    if not args.cad_file:
        parser.error("cad_file is required (or pass --list-materials / --show-config)")

    requested: list[UnsupportedProcess] = []
    if args.finish:
        requested.append(UnsupportedProcess.FINISH)
    if args.five_axis:
        requested.append(UnsupportedProcess.FIVE_AXIS)
    if args.turning:
        requested.append(UnsupportedProcess.TURNING)

    try:
        if args.qty < 1:
            raise ValueError("qty must be >= 1")
        if args.setups < 1:
            raise ValueError("setups must be >= 1")
        stock_dims = _stock_override(args)
        find_material(config, args.material)
        result = estimate_quote(
            cad_path=args.cad_file,
            config=config,
            material_name=args.material,
            unit=LengthUnit.INCH if args.units == "inch" else LengthUnit.MM,
            overrides=JobOverrides(
                setup_hours=args.setup_hours,
                mrr_eff_in3_per_hr=args.mrr,
                stock_dims_in=stock_dims,
                stock_purchase_cost_usd=args.stock_cost,
                qty=args.qty,
                setups=args.setups,
                material_source=parse_material_source(args.material_source),
                turnaround=parse_turnaround(args.turnaround),
                tolerance_class=parse_tolerance_class(args.tolerance),
                feature_risks=parse_feature_risks(
                    args.feature_risk, allowed=config.feature_risks.keys
                ),
                due_date=parse_iso_date(args.due_date),
                as_of_date=parse_iso_date(args.as_of),
            ),
            requested_processes=requested,
        )
    except (ConfigError, GeometryError, JobInputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        sys.stdout.write(render_json(result))
    else:
        sys.stdout.write(render_text(result, material_name=args.material))

    if result.status is QuoteStatus.OK:
        return EXIT_OK
    if result.status is QuoteStatus.REJECTED:
        return EXIT_REJECTED
    assert_never(result.status)


def _stock_override(args: argparse.Namespace) -> Vec3 | None:
    supplied = [args.stock_x, args.stock_y, args.stock_z]
    if all(v is None for v in supplied):
        return None
    if any(v is None for v in supplied):
        raise ValueError("--stock-x, --stock-y, and --stock-z must be provided together")
    if any(v is None or v <= 0 for v in supplied):
        raise ValueError("stock dimensions must be > 0")
    return Vec3(x=float(args.stock_x), y=float(args.stock_y), z=float(args.stock_z))


def _print_materials(config: QuoteConfig) -> None:
    print(f"Material catalog  ({config.source_path})")
    print("  $/in³ and MRR_eff marked TODO_REPLACE are placeholders — not market rates.")
    for spec in config.materials.values():
        aliases = ", ".join(spec.aliases) if spec.aliases else "—"
        enabled = "on" if spec.enabled else "OFF"
        cost_flag = " TODO_REPLACE" if spec.cost_is_placeholder else ""
        mrr_flag = " TODO_REPLACE" if spec.mrr_is_placeholder else ""
        print(
            f"  {spec.key:12}  {spec.label}  [{spec.family}]  {enabled}  "
            f"MRR_eff={spec.mrr_eff_in3_per_hr:g} in³/hr{mrr_flag} "
            f"(typical {spec.mrr_typical_low_in3_per_hr:g}–{spec.mrr_typical_high_in3_per_hr:g})  "
            f"${spec.cost_usd_per_in3:g}/in³{cost_flag}  aliases: {aliases}"
        )


def _print_config(config: QuoteConfig) -> None:
    shop = config.shop
    machine = config.machine
    usable = machine.usable_in
    print(f"Config: {config.source_path}")
    print(
        f"  shop rate ${shop.rate_usd_per_hr:g}/hr  setup {shop.setup_hours:g} hr  "
        f"min charge ${shop.min_charge_usd:g}  band {shop.band_low:g}–{shop.band_high:g}"
    )
    for key, tier in config.turnaround.items():
        print(
            f"  turnaround {key.value}: labor×{tier.labor_mult:g} setup×{tier.setup_mult:g} "
            f"min {tier.min_business_days} business days  (starting points)"
        )
    print(
        f"  {machine.name} {machine.axes}-axis  "
        f"envelope {machine.envelope_in.x:g}×{machine.envelope_in.y:g}×{machine.envelope_in.z:g} in  "
        f"usable {usable.x:g}×{usable.y:g}×{usable.z:g} in"
    )
