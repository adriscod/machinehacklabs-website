from __future__ import annotations

from pathlib import Path

import importlib.util


def _load_server():
    path = Path(__file__).resolve().parents[1] / "dev_rfq_server.py"
    spec = importlib.util.spec_from_file_location("dev_rfq_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_inbox_does_not_email(tmp_path: Path, monkeypatch) -> None:
    server = _load_server()
    monkeypatch.setattr(server, "INBOX", tmp_path)
    boundary = "----testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="email"\r\n\r\n'
        "buyer@example.com\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="quote_range_usd"\r\n\r\n'
        "109.82-161.50\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="attachment"; filename="part.stl"\r\n'
        "Content-Type: application/sla\r\n\r\n"
        "solid x\nendsolid x\n"
        f"\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    folder = server._save_submission(f"multipart/form-data; boundary={boundary}", body)
    payload = (folder / "rfq.json").read_text(encoding="utf-8")
    assert "buyer@example.com" in payload
    assert "emailed" in payload
    assert '"emailed": false' in payload
    assert (folder / "part.stl").is_file()
