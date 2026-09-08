"""Shop job ledger for the quotes@ → Chase payment journey.

This is a local shop tool. It is not a customer product, not accounting
software, and not a Chase integration.

Policy (keep these next to every record):
- The estimator band is a shop rough range. It is not the shop bid.
- The shop sets the bid after reviewing the RFQ at quotes@.
- Deposit is a materials + tooling floor, not a fixed percent of the bid.
- The shop creates a Chase payment request and pastes the URL.
  This repo never calls Chase and never captures cards.
- Paying that pasted link is acceptance of the stated scope and price.
- Collect deposit, then balance, then ship. Scrap is not billed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, assert_never

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
QUOTES_INBOX = "quotes@machinehacklabs.com"

POLICY_NOTES: tuple[str, ...] = (
    "Estimate band is a shop rough range, not the customer bid.",
    "The shop sets the bid after quotes@ review. Deposit is a materials+tooling floor, not a fixed percent.",
    "Paste a Chase payment URL the shop created. No Chase API. No card capture on machinehacklabs.com.",
    "Customer payment of that link is acceptance of the stated scope and price.",
    "Deposit first, then balance, then ship. Scrap is not billed to the customer.",
)


class WorkflowStatus(str, Enum):
    """Intended shop journey after an RFQ lands in quotes@."""

    ESTIMATED = "estimated"
    PROCEEDED = "proceeded"
    BID_SENT = "bid_sent"
    DEPOSIT_PAID = "deposit_paid"
    SCHEDULED = "scheduled"
    BALANCED = "balanced"
    SHIPPED = "shipped"


class PaymentStatus(str, Enum):
    """Clearer than a boolean paid flag: deposit and balance are separate asks."""

    UNPAID = "unpaid"
    DEPOSIT_PAID = "deposit_paid"
    BALANCED = "balanced"


WORKFLOW_ORDER: tuple[WorkflowStatus, ...] = (
    WorkflowStatus.ESTIMATED,
    WorkflowStatus.PROCEEDED,
    WorkflowStatus.BID_SENT,
    WorkflowStatus.DEPOSIT_PAID,
    WorkflowStatus.SCHEDULED,
    WorkflowStatus.BALANCED,
    WorkflowStatus.SHIPPED,
)

WORKFLOW_LABELS: dict[WorkflowStatus, str] = {
    WorkflowStatus.ESTIMATED: "Estimated",
    WorkflowStatus.PROCEEDED: "Proceeded",
    WorkflowStatus.BID_SENT: "Bid sent",
    WorkflowStatus.DEPOSIT_PAID: "Deposit paid",
    WorkflowStatus.SCHEDULED: "Scheduled",
    WorkflowStatus.BALANCED: "Balanced",
    WorkflowStatus.SHIPPED: "Shipped",
}

PAYMENT_LABELS: dict[PaymentStatus, str] = {
    PaymentStatus.UNPAID: "Unpaid",
    PaymentStatus.DEPOSIT_PAID: "Deposit paid",
    PaymentStatus.BALANCED: "Balanced (paid in full)",
}


def default_jobs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".local-jobs"


def default_inbox_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".local-inbox"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_job_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"MHL-{stamp}"


def parse_workflow(value: str | WorkflowStatus) -> WorkflowStatus:
    if isinstance(value, WorkflowStatus):
        return value
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "bid_sent": WorkflowStatus.BID_SENT,
        "deposit_paid": WorkflowStatus.DEPOSIT_PAID,
    }
    if key in aliases:
        return aliases[key]
    try:
        return WorkflowStatus(key)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in WORKFLOW_ORDER)
        raise ValueError(f"unknown workflow status {value!r}; use one of: {allowed}") from exc


def parse_payment(value: str | PaymentStatus) -> PaymentStatus:
    if isinstance(value, PaymentStatus):
        return value
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "paid": PaymentStatus.BALANCED,
        "paid_in_full": PaymentStatus.BALANCED,
        "unpaid": PaymentStatus.UNPAID,
        "deposit_paid": PaymentStatus.DEPOSIT_PAID,
        "deposit": PaymentStatus.DEPOSIT_PAID,
    }
    if key in aliases:
        return aliases[key]
    try:
        return PaymentStatus(key)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in PaymentStatus)
        raise ValueError(f"unknown payment status {value!r}; use one of: {allowed}") from exc


def next_workflow(status: WorkflowStatus) -> WorkflowStatus | None:
    idx = WORKFLOW_ORDER.index(status)
    if idx + 1 >= len(WORKFLOW_ORDER):
        return None
    return WORKFLOW_ORDER[idx + 1]


def implied_payment(status: WorkflowStatus) -> PaymentStatus | None:
    """Payment floor implied by a workflow step. Does not downgrade."""
    if status is WorkflowStatus.ESTIMATED:
        return None
    if status is WorkflowStatus.PROCEEDED:
        return None
    if status is WorkflowStatus.BID_SENT:
        return None
    if status is WorkflowStatus.DEPOSIT_PAID:
        return PaymentStatus.DEPOSIT_PAID
    if status is WorkflowStatus.SCHEDULED:
        return PaymentStatus.DEPOSIT_PAID
    if status is WorkflowStatus.BALANCED:
        return PaymentStatus.BALANCED
    if status is WorkflowStatus.SHIPPED:
        return PaymentStatus.BALANCED
    assert_never(status)


def _payment_rank(status: PaymentStatus) -> int:
    if status is PaymentStatus.UNPAID:
        return 0
    if status is PaymentStatus.DEPOSIT_PAID:
        return 1
    if status is PaymentStatus.BALANCED:
        return 2
    assert_never(status)


def validate_job_id(job_id: str) -> str:
    text = job_id.strip()
    if not JOB_ID_RE.fullmatch(text):
        raise ValueError(
            "job id must be 1–80 characters: letters, digits, dot, underscore, hyphen"
        )
    return text


def parse_money(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = float(value)
    else:
        text = str(value).strip().replace("$", "").replace(",", "")
        if text == "":
            return None
        amount = float(text)
    if amount < 0:
        raise ValueError("money amounts must be >= 0")
    return round(amount, 2)


def parse_chase_url(value: object | None) -> str | None:
    """Store the URL the shop pasted. This is not a Chase API client."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if not (text.startswith("http://") or text.startswith("https://")):
        raise ValueError(
            "Chase payment link must be an http(s) URL the shop pasted "
            "(this tool does not create or charge the link)"
        )
    return text


@dataclass(frozen=True)
class JobEvent:
    at: str
    workflow_status: str
    payment_status: str
    note: str = ""


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    rfq_id: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    estimate_low_usd: float | None = None
    estimate_high_usd: float | None = None
    bid_usd: float | None = None
    deposit_usd: float | None = None
    chase_payment_url: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.ESTIMATED
    payment_status: PaymentStatus = PaymentStatus.UNPAID
    notes: str = ""
    source: str = "manual"
    source_inbox: str | None = None
    quotes_inbox: str = QUOTES_INBOX
    created_at: str = ""
    updated_at: str = ""
    history: tuple[JobEvent, ...] = field(default_factory=tuple)
    policy: tuple[str, ...] = POLICY_NOTES

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workflow_status"] = self.workflow_status.value
        payload["payment_status"] = self.payment_status.value
        payload["workflow_label"] = WORKFLOW_LABELS[self.workflow_status]
        payload["payment_label"] = PAYMENT_LABELS[self.payment_status]
        payload["policy"] = list(self.policy)
        return payload


class JobLedger:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_jobs_dir()

    def path_for(self, job_id: str) -> Path:
        return self.root / f"{validate_job_id(job_id)}.json"

    def list_jobs(self) -> list[JobRecord]:
        if not self.root.is_dir():
            return []
        jobs = [self._read_path(path) for path in sorted(self.root.glob("*.json"))]
        jobs.sort(key=lambda job: job.updated_at, reverse=True)
        return jobs

    def get(self, job_id: str) -> JobRecord:
        path = self.path_for(job_id)
        if not path.is_file():
            raise FileNotFoundError(f"no shop job {job_id!r} in {self.root}")
        return self._read_path(path)

    def save(self, job: JobRecord) -> JobRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(job.job_id)
        path.write_text(json.dumps(job.to_mapping(), indent=2) + "\n", encoding="utf-8")
        return job

    def create(
        self,
        *,
        job_id: str | None = None,
        rfq_id: str | None = None,
        customer_name: str | None = None,
        customer_email: str | None = None,
        estimate_low_usd: object | None = None,
        estimate_high_usd: object | None = None,
        bid_usd: object | None = None,
        deposit_usd: object | None = None,
        chase_payment_url: object | None = None,
        workflow_status: str | WorkflowStatus = WorkflowStatus.ESTIMATED,
        payment_status: str | PaymentStatus = PaymentStatus.UNPAID,
        notes: str = "",
        source: str = "manual",
        source_inbox: str | None = None,
        created_at: str | None = None,
    ) -> JobRecord:
        ident = validate_job_id(job_id or new_job_id())
        if self.path_for(ident).exists():
            raise ValueError(f"shop job {ident!r} already exists")
        stamp = created_at or utc_now()
        workflow = parse_workflow(workflow_status)
        payment = parse_payment(payment_status)
        payment = _promote_payment(payment, implied_payment(workflow))
        job = _validated_record(
            JobRecord(
                job_id=ident,
                rfq_id=_blank_to_none(rfq_id) or ident,
                customer_name=_blank_to_none(customer_name),
                customer_email=_blank_to_none(customer_email),
                estimate_low_usd=parse_money(estimate_low_usd),
                estimate_high_usd=parse_money(estimate_high_usd),
                bid_usd=parse_money(bid_usd),
                deposit_usd=parse_money(deposit_usd),
                chase_payment_url=parse_chase_url(chase_payment_url),
                workflow_status=workflow,
                payment_status=payment,
                notes=notes.strip(),
                source=source,
                source_inbox=_blank_to_none(source_inbox),
                created_at=stamp,
                updated_at=stamp,
                history=(
                    JobEvent(
                        at=stamp,
                        workflow_status=workflow.value,
                        payment_status=payment.value,
                        note="created",
                    ),
                ),
            )
        )
        return self.save(job)

    def update(
        self,
        job_id: str,
        *,
        rfq_id: object | None = None,
        customer_name: object | None = None,
        customer_email: object | None = None,
        estimate_low_usd: object | None = None,
        estimate_high_usd: object | None = None,
        bid_usd: object | None = None,
        deposit_usd: object | None = None,
        chase_payment_url: object | None = None,
        workflow_status: str | WorkflowStatus | None = None,
        payment_status: str | PaymentStatus | None = None,
        notes: str | None = None,
        event_note: str = "updated",
    ) -> JobRecord:
        current = self.get(job_id)
        workflow = (
            parse_workflow(workflow_status)
            if workflow_status is not None
            else current.workflow_status
        )
        payment = (
            parse_payment(payment_status)
            if payment_status is not None
            else current.payment_status
        )
        if workflow_status is not None:
            payment = _promote_payment(payment, implied_payment(workflow))
        stamp = utc_now()
        updated = _validated_record(
            replace(
                current,
                rfq_id=current.rfq_id if rfq_id is None else _blank_to_none(str(rfq_id)),
                customer_name=(
                    current.customer_name
                    if customer_name is None
                    else _blank_to_none(str(customer_name))
                ),
                customer_email=(
                    current.customer_email
                    if customer_email is None
                    else _blank_to_none(str(customer_email))
                ),
                estimate_low_usd=_maybe_money(current.estimate_low_usd, estimate_low_usd),
                estimate_high_usd=_maybe_money(current.estimate_high_usd, estimate_high_usd),
                bid_usd=_maybe_money(current.bid_usd, bid_usd),
                deposit_usd=_maybe_money(current.deposit_usd, deposit_usd),
                chase_payment_url=_maybe_url(current.chase_payment_url, chase_payment_url),
                workflow_status=workflow,
                payment_status=payment,
                notes=current.notes if notes is None else notes.strip(),
                updated_at=stamp,
                history=current.history
                + (
                    JobEvent(
                        at=stamp,
                        workflow_status=workflow.value,
                        payment_status=payment.value,
                        note=event_note,
                    ),
                ),
            )
        )
        return self.save(updated)

    def advance(self, job_id: str) -> JobRecord:
        current = self.get(job_id)
        nxt = next_workflow(current.workflow_status)
        if nxt is None:
            raise ValueError(f"{job_id} is already {current.workflow_status.value}")
        return self.update(
            job_id,
            workflow_status=nxt,
            event_note=f"advanced to {WORKFLOW_LABELS[nxt]}",
        )

    def create_from_inbox(
        self,
        inbox_folder: Path,
        *,
        job_id: str | None = None,
    ) -> JobRecord:
        folder = Path(inbox_folder)
        payload_path = folder / "rfq.json"
        if not payload_path.is_file():
            raise FileNotFoundError(f"no rfq.json in inbox folder {folder}")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        fields = payload.get("fields") or {}
        if not isinstance(fields, Mapping):
            raise ValueError("rfq.json fields must be an object")
        ident = job_id or folder.name
        low, high = _estimate_from_fields(fields)
        return self.create(
            job_id=ident,
            rfq_id=folder.name,
            customer_name=fields.get("name"),
            customer_email=fields.get("email"),
            estimate_low_usd=low,
            estimate_high_usd=high,
            notes=_inbox_notes(fields),
            source="local-inbox",
            source_inbox=folder.name,
        )

    def _read_path(self, path: Path) -> JobRecord:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return job_from_mapping(payload)


def job_from_mapping(payload: Mapping[str, Any]) -> JobRecord:
    history_raw = payload.get("history") or []
    history = tuple(
        JobEvent(
            at=str(item.get("at") or ""),
            workflow_status=str(item.get("workflow_status") or ""),
            payment_status=str(item.get("payment_status") or ""),
            note=str(item.get("note") or ""),
        )
        for item in history_raw
    )
    policy = payload.get("policy") or POLICY_NOTES
    return _validated_record(
        JobRecord(
            job_id=validate_job_id(str(payload.get("job_id") or "")),
            rfq_id=_blank_to_none(payload.get("rfq_id")),
            customer_name=_blank_to_none(payload.get("customer_name")),
            customer_email=_blank_to_none(payload.get("customer_email")),
            estimate_low_usd=parse_money(payload.get("estimate_low_usd")),
            estimate_high_usd=parse_money(payload.get("estimate_high_usd")),
            bid_usd=parse_money(payload.get("bid_usd")),
            deposit_usd=parse_money(payload.get("deposit_usd")),
            chase_payment_url=parse_chase_url(payload.get("chase_payment_url")),
            workflow_status=parse_workflow(str(payload.get("workflow_status") or "estimated")),
            payment_status=parse_payment(str(payload.get("payment_status") or "unpaid")),
            notes=str(payload.get("notes") or ""),
            source=str(payload.get("source") or "manual"),
            source_inbox=_blank_to_none(payload.get("source_inbox")),
            quotes_inbox=str(payload.get("quotes_inbox") or QUOTES_INBOX),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            history=history,
            policy=tuple(str(item) for item in policy),
        )
    )


def _validated_record(job: JobRecord) -> JobRecord:
    if (
        job.estimate_low_usd is not None
        and job.estimate_high_usd is not None
        and job.estimate_low_usd > job.estimate_high_usd
    ):
        raise ValueError("estimate low must be <= estimate high")
    # Bid is intentionally not constrained to the estimate band.
    return job


def _promote_payment(
    current: PaymentStatus, implied: PaymentStatus | None
) -> PaymentStatus:
    if implied is None:
        return current
    if _payment_rank(implied) > _payment_rank(current):
        return implied
    return current


def _maybe_money(current: float | None, incoming: object | None) -> float | None:
    if incoming is None:
        return current
    return parse_money(incoming)


def _maybe_url(current: str | None, incoming: object | None) -> str | None:
    if incoming is None:
        return current
    return parse_chase_url(incoming)


def _blank_to_none(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _estimate_from_fields(fields: Mapping[str, Any]) -> tuple[float | None, float | None]:
    low = parse_money(fields.get("quote_low_usd"))
    high = parse_money(fields.get("quote_high_usd"))
    if low is not None and high is not None:
        return low, high
    range_text = _blank_to_none(fields.get("quote_range_usd"))
    if range_text:
        parts = range_text.replace("–", "-").split("-", 1)
        if len(parts) == 2:
            return parse_money(parts[0]), parse_money(parts[1])
    return low, high


def _inbox_notes(fields: Mapping[str, Any]) -> str:
    bits = []
    material = _blank_to_none(fields.get("material"))
    qty = _blank_to_none(fields.get("qty"))
    due = _blank_to_none(fields.get("due_date"))
    if material:
        bits.append(f"material={material}")
    if qty:
        bits.append(f"qty={qty}")
    if due:
        bits.append(f"due={due}")
    range_text = _blank_to_none(fields.get("quote_range_usd"))
    if range_text:
        bits.append(f"estimator band {range_text} (not a bid)")
    return "; ".join(bits)
