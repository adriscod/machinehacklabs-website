from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_server():
    path = Path(__file__).resolve().parents[1] / "dev_rfq_server.py"
    spec = importlib.util.spec_from_file_location("dev_rfq_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_inbox_does_not_email(tmp_path: Path, monkeypatch) -> None:
    server = _load_server()
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(server, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(server, "JOBS", jobs)
    boundary = "----testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="email"\r\n\r\n'
        "buyer@example.com\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="quote_range_usd"\r\n\r\n'
        "109.82-161.50\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="quote_low_usd"\r\n\r\n'
        "109.82\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="quote_high_usd"\r\n\r\n'
        "161.50\r\n"
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
    seeded = jobs / f"{folder.name}.json"
    assert seeded.is_file()
    job = json.loads(seeded.read_text(encoding="utf-8"))
    assert job["workflow_status"] == "estimated"
    assert job["payment_status"] == "unpaid"
    assert job["estimate_low_usd"] == 109.82
    assert job["estimate_high_usd"] == 161.50
    assert job["bid_usd"] is None
    assert "not a bid" in job["notes"]


def test_store_viewer_mesh_tessellates_stl(tmp_path: Path) -> None:
    server = _load_server()
    dest = tmp_path / "viewer"
    stl = (
        "solid x\n"
        "  facet normal 0 0 1\n"
        "    outer loop\n"
        "      vertex 0 0 0\n"
        "      vertex 1 0 0\n"
        "      vertex 0 1 0\n"
        "    endloop\n"
        "  endfacet\n"
        "endsolid x\n"
    ).encode("ascii")
    sidecar = server._store_viewer_mesh("part.stl", stl, dest_root=dest)
    assert sidecar["format"] == "stl"
    assert sidecar["original_name"] == "part.stl"
    assert sidecar["mesh_url"] == f"/__local_mesh/{sidecar['draft_id']}"
    assert (dest / sidecar["mesh_file"]).is_file()
    assert (dest / sidecar["mesh_file"]).read_bytes() == stl
    assert (dest / sidecar["stored_file"]).is_file()


def test_store_viewer_mesh_rejects_bad_extension(tmp_path: Path) -> None:
    server = _load_server()
    try:
        server._store_viewer_mesh("part.txt", b"nope", dest_root=tmp_path / "viewer")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_extract_cad_part_reads_multipart() -> None:
    server = _load_server()
    boundary = "----viewbound"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="cad_file"; filename="bracket.stp"\r\n'
        "Content-Type: application/step\r\n\r\n"
        "ISO-10303-21;\n"
        f"\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    name, payload = server._extract_cad_part(f"multipart/form-data; boundary={boundary}", body)
    assert name == "bracket.stp"
    assert payload.startswith(b"ISO-10303-21;")
