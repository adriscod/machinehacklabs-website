from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import app as rfq_app

SAMPLE_STL = Path(__file__).resolve().parents[2] / "mhl-quote" / "samples" / "demo_block.stl"


@pytest.fixture()
def client(tmp_path):
    application = rfq_app.create_app(data_dir=tmp_path)
    application.config.update(TESTING=True)
    with application.test_client() as test_client:
        test_client._data_dir = tmp_path  # type: ignore[attr-defined]
        yield test_client


def _stl_upload():
    return (io.BytesIO(SAMPLE_STL.read_bytes()), "demo_block.stl")


def test_index_renders_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Request a machining rough quote" in body
    assert 'name="cad_file"' in body


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_submit_valid_stl_quotes_and_queues(client):
    data = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "company": "Analytical Engines",
        "material": "aluminum",
        "units": "inch",
        "quantity": "3",
        "notes": "Prototype bracket",
        "cad_file": _stl_upload(),
    }
    resp = client.post("/quote", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Request received" in body
    assert "RFQ-" in body
    assert "Rough quote range" in body

    log = client._data_dir / "requests.jsonl"
    assert log.is_file()
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    rec = records[0]
    assert rec["contact"]["email"] == "ada@example.com"
    assert rec["part"]["quantity"] == 3
    assert rec["summary"]["status"] == "ok"
    assert rec["summary"]["quote_low_usd"] > 0
    uploads = list((client._data_dir / "uploads").glob("*.stl"))
    assert len(uploads) == 1


def test_missing_file_is_rejected(client):
    data = {"name": "No File", "email": "nofile@example.com", "material": "aluminum", "units": "inch"}
    resp = client.post("/quote", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "attach a STEP or STL file" in resp.get_data(as_text=True)


def test_invalid_email_is_rejected(client):
    data = {"name": "Bad Email", "email": "not-an-email", "material": "aluminum", "units": "inch", "cad_file": _stl_upload()}
    resp = client.post("/quote", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "valid email" in resp.get_data(as_text=True)


def test_bad_extension_is_rejected(client):
    data = {
        "name": "Bad Ext",
        "email": "badext@example.com",
        "material": "aluminum",
        "units": "inch",
        "cad_file": (io.BytesIO(b"nope"), "part.txt"),
    }
    resp = client.post("/quote", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.get_data(as_text=True)


def test_rejected_quote_is_still_logged(client, monkeypatch):
    from mhl_quote.models import QuoteResult, QuoteStatus

    def fake_estimate(**_kwargs):
        return QuoteResult(
            status=QuoteStatus.REJECTED,
            geometry=None,
            envelope=None,
            cost=None,
            callouts=["Machining-only 3-axis mill."],
            rejection_reasons=["REJECTED: stock exceeds Tormach 1500MX usable travel."],
        )

    monkeypatch.setattr(rfq_app, "estimate_quote", fake_estimate)

    data = {
        "name": "Big Part",
        "email": "big@example.com",
        "material": "aluminum",
        "units": "inch",
        "cad_file": _stl_upload(),
    }
    resp = client.post("/quote", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "can't be quoted automatically" in body
    assert "exceeds Tormach 1500MX usable travel" in body

    log = client._data_dir / "requests.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert records[-1]["summary"]["status"] == "rejected"
    assert records[-1]["summary"]["quote_low_usd"] is None


def test_requests_queue_lists_submissions(client):
    data = {
        "name": "Grace Hopper",
        "email": "grace@example.com",
        "material": "steel",
        "units": "inch",
        "quantity": "1",
        "cad_file": _stl_upload(),
    }
    client.post("/quote", data=data, content_type="multipart/form-data")
    resp = client.get("/requests")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "RFQ queue" in body
    assert "grace@example.com" in body
    assert "demo_block.stl" in body
