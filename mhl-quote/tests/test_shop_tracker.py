from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.test_local_rfq import _load_server


def _start(server_mod, tmp_path: Path) -> tuple[ThreadingHTTPServer, str]:
    server_mod.INBOX = tmp_path / "inbox"
    server_mod.JOBS = tmp_path / "jobs"
    server_mod.INBOX.mkdir(exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.RfqHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, f"http://{host}:{port}"


def _json(url: str, payload: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


def test_shop_page_and_job_api(tmp_path: Path) -> None:
    server = _load_server()
    httpd, origin = _start(server, tmp_path)
    try:
        with urlopen(f"{origin}/__shop/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "Shop job tracker" in html
        assert "Estimate band" in html or "Estimator band" in html
        assert "Scrap is not billed" in html
        assert "No Chase API" in html or "does not call Chase" in html

        status, created = _json(
            f"{origin}/__shop/api/jobs",
            {
                "job_id": "MHL-WEB",
                "estimate_low_usd": 110,
                "estimate_high_usd": 160,
                "bid_usd": 150,
                "deposit_usd": 55,
                "chase_payment_url": "https://secure.chase.com/pasted-by-andrew",
                "workflow_status": "bid_sent",
            },
        )
        assert status == 201
        assert created["job_id"] == "MHL-WEB"
        assert created["chase_payment_url"].endswith("pasted-by-andrew")
        assert created["payment_status"] == "unpaid"
        assert (tmp_path / "jobs" / "MHL-WEB.json").is_file()

        status, advanced = _json(f"{origin}/__shop/api/jobs/MHL-WEB/advance", {}, method="POST")
        assert status == 200
        assert advanced["workflow_status"] == "deposit_paid"
        assert advanced["payment_status"] == "deposit_paid"

        status, listed = _json(f"{origin}/__shop/api/jobs")
        assert status == 200
        assert listed["jobs"][0]["job_id"] == "MHL-WEB"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_shop_from_inbox_and_bad_url(tmp_path: Path) -> None:
    server = _load_server()
    inbox = tmp_path / "inbox" / "LOC1"
    inbox.mkdir(parents=True)
    (inbox / "rfq.json").write_text(
        json.dumps({"fields": {"email": "c@d.e", "quote_low_usd": "9", "quote_high_usd": "11"}}),
        encoding="utf-8",
    )
    httpd, origin = _start(server, tmp_path)
    try:
        status, job = _json(f"{origin}/__shop/api/jobs/from-inbox", {"inbox_folder": "LOC1"})
        assert status == 201
        assert job["customer_email"] == "c@d.e"
        assert job["source"] == "local-inbox"

        status, err = _json(
            f"{origin}/__shop/api/jobs",
            {"job_id": "MHL-BAD", "chase_payment_url": "not-a-link"},
        )
        assert status == 400
        assert "http" in err["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()
