from __future__ import annotations

import json
from pathlib import Path

import pytest

from mhl_quote.jobs import (
    POLICY_NOTES,
    JobLedger,
    PaymentStatus,
    WorkflowStatus,
    implied_payment,
    next_workflow,
    parse_chase_url,
)


def test_create_stores_required_shop_fields(tmp_path: Path) -> None:
    ledger = JobLedger(tmp_path)
    job = ledger.create(
        job_id="MHL-1001",
        rfq_id="RFQ-88",
        estimate_low_usd="109.82",
        estimate_high_usd=161.5,
        bid_usd=145,
        deposit_usd="60",
        chase_payment_url="https://secure.chase.com/pay/example",
        customer_email="buyer@example.com",
    )
    assert job.job_id == "MHL-1001"
    assert job.rfq_id == "RFQ-88"
    assert job.estimate_low_usd == 109.82
    assert job.estimate_high_usd == 161.50
    assert job.bid_usd == 145.00
    assert job.deposit_usd == 60.00
    assert job.chase_payment_url == "https://secure.chase.com/pay/example"
    assert job.workflow_status is WorkflowStatus.ESTIMATED
    assert job.payment_status is PaymentStatus.UNPAID
    loaded = json.loads((tmp_path / "MHL-1001.json").read_text(encoding="utf-8"))
    assert loaded["quotes_inbox"] == "quotes@machinehacklabs.com"
    assert loaded["policy"] == list(POLICY_NOTES)


def test_bid_may_sit_outside_estimate_band(tmp_path: Path) -> None:
    ledger = JobLedger(tmp_path)
    job = ledger.create(job_id="MHL-1002", estimate_low_usd=100, estimate_high_usd=120, bid_usd=180)
    assert job.bid_usd == 180
    assert job.estimate_low_usd == 100
    assert job.estimate_high_usd == 120


def test_estimate_low_cannot_exceed_high(tmp_path: Path) -> None:
    ledger = JobLedger(tmp_path)
    with pytest.raises(ValueError, match="estimate low"):
        ledger.create(job_id="MHL-bad", estimate_low_usd=200, estimate_high_usd=100)


def test_chase_url_must_be_http(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="http"):
        parse_chase_url("not-a-url")
    ledger = JobLedger(tmp_path)
    with pytest.raises(ValueError, match="http"):
        ledger.create(job_id="MHL-link", chase_payment_url="chase-without-scheme")


def test_workflow_advance_and_payment_promotion(tmp_path: Path) -> None:
    ledger = JobLedger(tmp_path)
    ledger.create(job_id="MHL-flow")
    assert next_workflow(WorkflowStatus.ESTIMATED) is WorkflowStatus.PROCEEDED
    job = ledger.advance("MHL-flow")
    assert job.workflow_status is WorkflowStatus.PROCEEDED
    job = ledger.update("MHL-flow", workflow_status="bid_sent")
    assert job.workflow_status is WorkflowStatus.BID_SENT
    assert job.payment_status is PaymentStatus.UNPAID
    job = ledger.update("MHL-flow", workflow_status="deposit_paid")
    assert job.payment_status is PaymentStatus.DEPOSIT_PAID
    job = ledger.update("MHL-flow", workflow_status=WorkflowStatus.SHIPPED)
    assert job.workflow_status is WorkflowStatus.SHIPPED
    assert job.payment_status is PaymentStatus.BALANCED
    with pytest.raises(ValueError, match="already shipped"):
        ledger.advance("MHL-flow")


def test_implied_payment_covers_every_workflow_step() -> None:
    expected = {
        WorkflowStatus.ESTIMATED: None,
        WorkflowStatus.PROCEEDED: None,
        WorkflowStatus.BID_SENT: None,
        WorkflowStatus.DEPOSIT_PAID: PaymentStatus.DEPOSIT_PAID,
        WorkflowStatus.SCHEDULED: PaymentStatus.DEPOSIT_PAID,
        WorkflowStatus.BALANCED: PaymentStatus.BALANCED,
        WorkflowStatus.SHIPPED: PaymentStatus.BALANCED,
    }
    for status in WorkflowStatus:
        assert implied_payment(status) is expected[status]


def test_from_inbox_reads_estimator_band(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox" / "20260905T143000Z"
    inbox.mkdir(parents=True)
    (inbox / "rfq.json").write_text(
        json.dumps(
            {
                "fields": {
                    "name": "Buyer",
                    "email": "buyer@example.com",
                    "quote_low_usd": "109.82",
                    "quote_high_usd": "161.50",
                    "quote_range_usd": "109.82-161.50",
                    "material": "aluminum",
                    "qty": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    job = JobLedger(tmp_path / "jobs").create_from_inbox(inbox)
    assert job.job_id == "20260905T143000Z"
    assert job.customer_email == "buyer@example.com"
    assert job.estimate_low_usd == 109.82
    assert job.estimate_high_usd == 161.50
    assert job.source == "local-inbox"
    assert "not a bid" in job.notes

    ranged = tmp_path / "inbox" / "RANGEONLY"
    ranged.mkdir()
    (ranged / "rfq.json").write_text(
        json.dumps({"fields": {"quote_range_usd": "109.82-161.50"}}),
        encoding="utf-8",
    )
    from_range = JobLedger(tmp_path / "jobs-range").create_from_inbox(ranged)
    assert from_range.estimate_low_usd == 109.82
    assert from_range.estimate_high_usd == 161.50
