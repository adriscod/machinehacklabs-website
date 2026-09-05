#!/usr/bin/env python3
"""Serve the website locally and capture RFQs without emailing quotes@.

    python mhl-quote/dev_rfq_server.py

Then open http://127.0.0.1:8765/quote/

POST /__local_rfq stores the structured fields + upload under
mhl-quote/.local-inbox/<timestamp>/  (gitignored). Does not send email.

Shop job tracker (local only, not a marketing page):
    http://127.0.0.1:8765/__shop/
JSON ledger: mhl-quote/.local-jobs/ (gitignored). No Chase API.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from mhl_quote.jobs import JobLedger

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = Path(__file__).resolve().parent / ".local-inbox"
JOBS = Path(__file__).resolve().parent / ".local-jobs"
SHOP_DIR = Path(__file__).resolve().parent / "shop"
LOCAL_PATH = "/__local_rfq"
SHOP_FILES = {
    "/__shop": "index.html",
    "/__shop/": "index.html",
    "/__shop/index.html": "index.html",
    "/__shop/tracker.js": "tracker.js",
}


class RfqHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == LOCAL_PATH:
            self._list_inbox()
            return
        if path in SHOP_FILES:
            self._serve_shop_file(SHOP_FILES[path])
            return
        if path == "/__shop/api/jobs":
            self._json(200, _jobs_payload())
            return
        if path == "/__shop/api/inbox":
            self._list_inbox()
            return
        job_id = _job_id_from_path(path, "/__shop/api/jobs/")
        if job_id:
            try:
                self._json(200, _ledger().get(job_id).to_mapping())
            except FileNotFoundError as exc:
                self._json(404, {"error": str(exc)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == LOCAL_PATH:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type") or ""
            folder = _save_submission(content_type, body)
            self.send_response(303)
            self.send_header("Location", "/thanks/?local=1")
            self.send_header("X-Local-Inbox", str(folder))
            self.end_headers()
            return
        if path.startswith("/__shop/api/"):
            self._shop_write(path)
            return
        self.send_error(404, "Use POST /__local_rfq or /__shop/api/…")

    def _list_inbox(self) -> None:
        INBOX.mkdir(parents=True, exist_ok=True)
        entries = sorted(p.name for p in INBOX.iterdir() if p.is_dir())
        self._json(200, {"inbox": str(INBOX), "submissions": entries})

    def _serve_shop_file(self, name: str) -> None:
        path = SHOP_DIR / name
        data = path.read_bytes()
        content_type = "text/html; charset=utf-8" if name.endswith(".html") else "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _shop_write(self, path: str) -> None:
        try:
            payload = self._read_json_body()
            ledger = _ledger()
            if path == "/__shop/api/jobs":
                job = ledger.create(**_job_fields(payload), source=payload.get("source") or "quotes@")
                self._json(201, job.to_mapping())
                return
            if path == "/__shop/api/jobs/from-inbox":
                folder_name = str(payload.get("inbox_folder") or "").strip()
                if not folder_name:
                    raise ValueError("inbox_folder is required")
                job = ledger.create_from_inbox(INBOX / folder_name, job_id=payload.get("job_id"))
                self._json(201, job.to_mapping())
                return
            if path.endswith("/advance"):
                job_id = _job_id_from_path(path[: -len("/advance")], "/__shop/api/jobs/")
                if not job_id:
                    raise ValueError("job id required")
                self._json(200, ledger.advance(job_id).to_mapping())
                return
            job_id = _job_id_from_path(path, "/__shop/api/jobs/")
            if job_id:
                self._json(200, ledger.update(job_id, **_job_fields(payload, for_update=True)).to_mapping())
                return
        except FileNotFoundError as exc:
            self._json(404, {"error": str(exc)})
            return
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "unknown shop endpoint"})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def _save_submission(content_type: str, body: bytes) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = INBOX / stamp
    folder.mkdir()
    preamble = f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8")
    msg = BytesParser(policy=policy.default).parsebytes(preamble + body)
    fields: dict[str, str] = {}
    files: list[str] = []
    if msg.is_multipart():
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                safe = Path(filename).name or "upload.bin"
                dest = folder / safe
                dest.write_bytes(payload)
                files.append(safe)
                fields[str(name or "attachment")] = safe
            elif name:
                fields[str(name)] = payload.decode("utf-8", errors="replace")
    else:
        fields["raw"] = body.decode("utf-8", errors="replace")
    (folder / "rfq.json").write_text(
        json.dumps(
            {
                "quotes_inbox": "quotes@machinehacklabs.com",
                "emailed": False,
                "fields": fields,
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    job_path = _seed_job_from_inbox(folder)
    extra = f"  shop job → {job_path}" if job_path else ""
    print(f"captured RFQ → {folder}{extra}")
    return folder


def _ledger() -> JobLedger:
    return JobLedger(JOBS)


def _jobs_payload() -> dict:
    ledger = _ledger()
    return {
        "jobs_dir": str(ledger.root),
        "jobs": [job.to_mapping() for job in ledger.list_jobs()],
    }


def _job_id_from_path(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    rest = unquote(path[len(prefix) :]).strip("/")
    if not rest or "/" in rest:
        return None
    return rest


def _job_fields(payload: dict, *, for_update: bool = False) -> dict:
    keys = (
        "rfq_id",
        "customer_name",
        "customer_email",
        "estimate_low_usd",
        "estimate_high_usd",
        "bid_usd",
        "deposit_usd",
        "chase_payment_url",
        "workflow_status",
        "payment_status",
        "notes",
    )
    fields: dict = {}
    if not for_update and payload.get("job_id"):
        fields["job_id"] = payload.get("job_id")
    for key in keys:
        if key in payload:
            fields[key] = payload.get(key)
    return fields


def _seed_job_from_inbox(folder: Path) -> Path | None:
    """Stub a shop job at 'estimated' so Andrew can paste a Chase link later."""
    try:
        job = _ledger().create_from_inbox(folder)
        return _ledger().path_for(job.job_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"shop job not seeded: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Local RFQ site server (no email)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RfqHandler)
    print(f"Serving {REPO_ROOT} at http://{args.host}:{args.port}/quote/")
    print(f"Local RFQ capture: POST {LOCAL_PATH} → {INBOX} (no email sent)")
    print(f"Shop job tracker:  http://{args.host}:{args.port}/__shop/ → {JOBS}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
