from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mhl_quote.jobs import (
    POLICY_NOTES,
    PAYMENT_LABELS,
    WORKFLOW_LABELS,
    WORKFLOW_ORDER,
    JobLedger,
    JobRecord,
    PaymentStatus,
    default_inbox_dir,
    default_jobs_dir,
)

EXIT_OK = 0
EXIT_USAGE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop_jobs",
        description=(
            "Shop job tracker for the quotes@ → Chase payment journey. "
            "Local ledger only. Estimate ≠ bid. No Chase API."
        ),
        epilog="\n".join(POLICY_NOTES),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--jobs-dir",
        default=None,
        help=f"JSON ledger directory (default: {default_jobs_dir()})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="Record a job after quotes@ receives an RFQ")
    new.add_argument("--id", dest="job_id", help="Shop / RFQ job id (default: MHL-<utc>)")
    new.add_argument("--rfq-id", dest="rfq_id", help="RFQ id if different from the job id")
    new.add_argument("--name", dest="customer_name")
    new.add_argument("--email", dest="customer_email")
    new.add_argument("--estimate-low", dest="estimate_low_usd", help="Estimator low (not the bid)")
    new.add_argument("--estimate-high", dest="estimate_high_usd", help="Estimator high (not the bid)")
    new.add_argument("--bid", dest="bid_usd", help="Shop bid (may be outside the estimate band)")
    new.add_argument(
        "--deposit",
        dest="deposit_usd",
        help="Materials+tooling floor — not a fixed percent",
    )
    new.add_argument(
        "--chase-url",
        dest="chase_payment_url",
        help="Chase payment link the shop pasted (created outside this site)",
    )
    new.add_argument("--notes", default="")
    new.add_argument("--json", action="store_true")

    inbox = sub.add_parser("from-inbox", help="Create a job from a local RFQ inbox folder")
    inbox.add_argument("inbox_folder", help="Folder name or path under mhl-quote/.local-inbox/")
    inbox.add_argument("--inbox-dir", default=None)
    inbox.add_argument("--id", dest="job_id")
    inbox.add_argument("--json", action="store_true")

    listed = sub.add_parser("list", help="List shop jobs")
    listed.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="Show one job")
    show.add_argument("job_id")
    show.add_argument("--json", action="store_true")

    update = sub.add_parser("set", help="Update bid, deposit, Chase link, or status")
    update.add_argument("job_id")
    update.add_argument("--rfq-id", dest="rfq_id")
    update.add_argument("--name", dest="customer_name")
    update.add_argument("--email", dest="customer_email")
    update.add_argument("--estimate-low", dest="estimate_low_usd")
    update.add_argument("--estimate-high", dest="estimate_high_usd")
    update.add_argument("--bid", dest="bid_usd")
    update.add_argument("--deposit", dest="deposit_usd")
    update.add_argument("--chase-url", dest="chase_payment_url")
    update.add_argument(
        "--status",
        dest="workflow_status",
        help="estimated|proceeded|bid_sent|deposit_paid|scheduled|balanced|shipped",
    )
    update.add_argument(
        "--payment",
        dest="payment_status",
        help="unpaid|deposit_paid|balanced",
    )
    update.add_argument("--notes")
    update.add_argument("--json", action="store_true")

    advance = sub.add_parser("advance", help="Move to the next workflow status")
    advance.add_argument("job_id")
    advance.add_argument("--json", action="store_true")

    statuses = sub.add_parser("statuses", help="Print the workflow and payment values")
    statuses.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ledger = JobLedger(Path(args.jobs_dir) if args.jobs_dir else None)
    try:
        if args.command == "new":
            job = ledger.create(
                job_id=args.job_id,
                rfq_id=args.rfq_id,
                customer_name=args.customer_name,
                customer_email=args.customer_email,
                estimate_low_usd=args.estimate_low_usd,
                estimate_high_usd=args.estimate_high_usd,
                bid_usd=args.bid_usd,
                deposit_usd=args.deposit_usd,
                chase_payment_url=args.chase_payment_url,
                notes=args.notes,
                source="quotes@",
            )
            _emit(job, as_json=args.json, ledger=ledger)
            return EXIT_OK
        if args.command == "from-inbox":
            folder = _resolve_inbox(args.inbox_folder, args.inbox_dir)
            job = ledger.create_from_inbox(folder, job_id=args.job_id)
            _emit(job, as_json=args.json, ledger=ledger)
            return EXIT_OK
        if args.command == "list":
            jobs = ledger.list_jobs()
            if args.json:
                sys.stdout.write(json.dumps({"jobs": [job.to_mapping() for job in jobs]}, indent=2) + "\n")
            else:
                _print_table(jobs, ledger.root)
            return EXIT_OK
        if args.command == "show":
            _emit(ledger.get(args.job_id), as_json=args.json, ledger=ledger)
            return EXIT_OK
        if args.command == "set":
            job = ledger.update(
                args.job_id,
                rfq_id=args.rfq_id,
                customer_name=args.customer_name,
                customer_email=args.customer_email,
                estimate_low_usd=args.estimate_low_usd,
                estimate_high_usd=args.estimate_high_usd,
                bid_usd=args.bid_usd,
                deposit_usd=args.deposit_usd,
                chase_payment_url=args.chase_payment_url,
                workflow_status=args.workflow_status,
                payment_status=args.payment_status,
                notes=args.notes,
            )
            _emit(job, as_json=args.json, ledger=ledger)
            return EXIT_OK
        if args.command == "advance":
            _emit(ledger.advance(args.job_id), as_json=args.json, ledger=ledger)
            return EXIT_OK
        if args.command == "statuses":
            _print_statuses(as_json=args.json)
            return EXIT_OK
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    parser.error(f"unhandled command {args.command}")
    return EXIT_USAGE


def _resolve_inbox(folder: str, inbox_dir: str | None) -> Path:
    path = Path(folder)
    if path.is_dir() and (path / "rfq.json").is_file():
        return path
    root = Path(inbox_dir) if inbox_dir else default_inbox_dir()
    candidate = root / folder
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(f"inbox folder not found: {folder}")


def _emit(job: JobRecord, *, as_json: bool, ledger: JobLedger) -> None:
    if as_json:
        sys.stdout.write(json.dumps(job.to_mapping(), indent=2) + "\n")
        return
    sys.stdout.write(_format_job(job, ledger.root))


def _print_table(jobs: list[JobRecord], root: Path) -> None:
    print(f"Shop jobs in {root}  (estimate ≠ bid; Chase link is pasted)")
    if not jobs:
        print("  (none yet — record one after quotes@ or import a local inbox RFQ)")
        return
    print(
        f"{'ID':<24} {'workflow':<14} {'payment':<14} {'estimate':<18} {'bid':<10} {'deposit':<10} chase"
    )
    for job in jobs:
        estimate = _band(job.estimate_low_usd, job.estimate_high_usd)
        print(
            f"{job.job_id:<24} {job.workflow_status.value:<14} {job.payment_status.value:<14} "
            f"{estimate:<18} {_money(job.bid_usd):<10} {_money(job.deposit_usd):<10} "
            f"{'yes' if job.chase_payment_url else '—'}"
        )


def _format_job(job: JobRecord, root: Path) -> str:
    lines = [
        f"Job {job.job_id}   {WORKFLOW_LABELS[job.workflow_status]} / {PAYMENT_LABELS[job.payment_status]}",
        f"  file:     {root / (job.job_id + '.json')}",
        f"  rfq:      {job.rfq_id or '—'}",
        f"  customer: {job.customer_name or '—'}  {job.customer_email or ''}".rstrip(),
        f"  estimate: {_band(job.estimate_low_usd, job.estimate_high_usd)}  (not the bid)",
        f"  bid:      {_money(job.bid_usd)}",
        f"  deposit:  {_money(job.deposit_usd)}  (materials+tooling floor)",
        f"  chase:    {job.chase_payment_url or '(paste after the shop creates the ask)'}",
        f"  notes:    {job.notes or '—'}",
        "",
        "Paying the Chase link = acceptance of the stated scope and price.",
        "Deposit, then balance, then ship. Scrap is not billed.",
        "",
    ]
    return "\n".join(lines)


def _print_statuses(*, as_json: bool) -> None:
    workflow = [status.value for status in WORKFLOW_ORDER]
    payment = [status.value for status in PaymentStatus]
    if as_json:
        sys.stdout.write(json.dumps({"workflow": workflow, "payment": payment}, indent=2) + "\n")
        return
    print("workflow: " + " → ".join(workflow))
    print("payment:  " + " / ".join(payment))
    for note in POLICY_NOTES:
        print(f"- {note}")


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:.2f}"


def _band(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "—"
    if low is None:
        return f"—–{_money(high)}"
    if high is None:
        return f"{_money(low)}–—"
    return f"{_money(low)}–{_money(high)}"


if __name__ == "__main__":
    raise SystemExit(main())
