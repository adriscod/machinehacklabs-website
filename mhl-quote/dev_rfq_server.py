#!/usr/bin/env python3
"""Serve the website locally and capture RFQs without emailing quotes@.

    python mhl-quote/dev_rfq_server.py

Then open http://127.0.0.1:8765/quote/

POST /__local_rfq stores the structured fields + upload under
mhl-quote/.local-inbox/<timestamp>/  (gitignored). Does not send email.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = Path(__file__).resolve().parent / ".local-inbox"
LOCAL_PATH = "/__local_rfq"


class RfqHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == LOCAL_PATH:
            self._list_inbox()
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != LOCAL_PATH:
            self.send_error(404, "Use POST /__local_rfq")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type") or ""
        folder = _save_submission(content_type, body)
        self.send_response(303)
        self.send_header("Location", "/thanks/?local=1")
        self.send_header("X-Local-Inbox", str(folder))
        self.end_headers()

    def _list_inbox(self) -> None:
        INBOX.mkdir(parents=True, exist_ok=True)
        entries = sorted(p.name for p in INBOX.iterdir() if p.is_dir())
        payload = {"inbox": str(INBOX), "submissions": entries}
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
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
    print(f"captured RFQ → {folder}")
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description="Local RFQ site server (no email)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RfqHandler)
    print(f"Serving {REPO_ROOT} at http://{args.host}:{args.port}/quote/")
    print(f"Local RFQ capture: POST {LOCAL_PATH} → {INBOX} (no email sent)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
