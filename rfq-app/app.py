"""Machine Hack Labs RFQ web app.

A deliberately small Request-for-Quote intake that wraps the local ``mhl_quote``
rough-quote estimator: a customer uploads a STEP/STL and contact details, the
estimator produces a machining rough-quote range, and the request is stored
(queued) on disk for the shop to follow up on.

This is an internal/local tool. It does not send email and stores no secrets.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from mhl_quote.config import ConfigError, QuoteConfig, find_material, load_config
from mhl_quote.geometry import GeometryError
from mhl_quote.models import JobOverrides, LengthUnit, QuoteStatus
from mhl_quote.quote import estimate_quote
from mhl_quote.report import result_to_jsonable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
REQUESTS_LOG = DATA_DIR / "requests.jsonl"

ALLOWED_EXTENSIONS = {".step", ".stp", ".stl"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RfqError(ValueError):
    """A user-facing validation problem with an RFQ submission."""


def create_app(config_path: str | Path | None = None, data_dir: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    data_root = Path(data_dir) if data_dir is not None else DATA_DIR
    upload_root = data_root / "uploads"
    requests_log = data_root / "requests.jsonl"
    upload_root.mkdir(parents=True, exist_ok=True)

    quote_config: QuoteConfig = load_config(config_path)

    @app.route("/")
    def index() -> str:
        return render_template(
            "index.html",
            materials=_material_options(quote_config),
            machine=quote_config.machine,
            shop=quote_config.shop,
        )

    @app.route("/quote", methods=["POST"])
    def submit_quote() -> Any:
        try:
            contact = _parse_contact(request.form)
            part = _parse_part(request.form)
            upload = request.files.get("cad_file")
            stored_path, original_name = _save_upload(upload, upload_root)
        except RfqError as exc:
            return (
                render_template(
                    "index.html",
                    materials=_material_options(quote_config),
                    machine=quote_config.machine,
                    shop=quote_config.shop,
                    error=str(exc),
                    form=request.form,
                ),
                400,
            )

        rfq_id = _new_rfq_id()
        try:
            result = estimate_quote(
                cad_path=stored_path,
                config=quote_config,
                material_name=part["material"],
                unit=LengthUnit.INCH if part["units"] == "inch" else LengthUnit.MM,
                overrides=JobOverrides(),
            )
        except (ConfigError, GeometryError, ValueError) as exc:
            return (
                render_template(
                    "index.html",
                    materials=_material_options(quote_config),
                    machine=quote_config.machine,
                    shop=quote_config.shop,
                    error=f"Could not quote that file: {exc}",
                    form=request.form,
                ),
                400,
            )

        record = _build_record(
            rfq_id=rfq_id,
            contact=contact,
            part=part,
            original_name=original_name,
            stored_path=stored_path,
            result=result,
        )
        _append_record(requests_log, record)

        return render_template("result.html", record=record, result=result)

    @app.route("/requests")
    def list_requests() -> str:
        records = _read_records(requests_log)
        records.reverse()
        return render_template("requests.html", records=records)

    @app.route("/healthz")
    def healthz() -> Any:
        return {"status": "ok", "config": quote_config.source_path}, 200

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc: RequestEntityTooLarge) -> Any:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return (
            render_template(
                "index.html",
                materials=_material_options(quote_config),
                machine=quote_config.machine,
                shop=quote_config.shop,
                error=f"That file is too large (limit {limit_mb} MB).",
            ),
            413,
        )

    return app


def _material_options(config: QuoteConfig) -> list[dict[str, str]]:
    return [
        {"key": spec.key, "label": spec.label}
        for spec in config.materials.values()
    ]


def _parse_contact(form: Any) -> dict[str, str]:
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    company = (form.get("company") or "").strip()
    phone = (form.get("phone") or "").strip()
    if not name:
        raise RfqError("Your name is required.")
    if not EMAIL_RE.match(email):
        raise RfqError("A valid email address is required.")
    return {"name": name, "email": email, "company": company, "phone": phone}


def _parse_part(form: Any) -> dict[str, Any]:
    material = (form.get("material") or "").strip().lower()
    units = (form.get("units") or "inch").strip().lower()
    notes = (form.get("notes") or "").strip()
    quantity_raw = (form.get("quantity") or "1").strip()
    if units not in {"inch", "mm"}:
        raise RfqError("Units must be inch or mm.")
    try:
        quantity = int(quantity_raw)
    except ValueError as exc:
        raise RfqError("Quantity must be a whole number.") from exc
    if quantity < 1:
        raise RfqError("Quantity must be at least 1.")
    if not material:
        raise RfqError("Please choose a material.")
    return {"material": material, "units": units, "notes": notes, "quantity": quantity}


def _save_upload(upload: Any, upload_root: Path) -> tuple[Path, str]:
    if upload is None or not upload.filename:
        raise RfqError("Please attach a STEP or STL file.")
    original_name = secure_filename(upload.filename)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise RfqError(f"Unsupported file type {suffix or '(none)'}; allowed: {allowed}.")
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = upload_root / stored_name
    upload.save(str(stored_path))
    if stored_path.stat().st_size == 0:
        stored_path.unlink(missing_ok=True)
        raise RfqError("The uploaded file was empty.")
    return stored_path, original_name


def _new_rfq_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"RFQ-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _build_record(
    *,
    rfq_id: str,
    contact: dict[str, str],
    part: dict[str, Any],
    original_name: str,
    stored_path: Path,
    result: Any,
) -> dict[str, Any]:
    payload = result_to_jsonable(result)
    cost = payload.get("cost")
    summary = {
        "status": payload["status"],
        "rejection_reasons": payload["rejection_reasons"],
        "quote_low_usd": cost["quote_low_usd"] if cost else None,
        "quote_high_usd": cost["quote_high_usd"] if cost else None,
    }
    return {
        "rfq_id": rfq_id,
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contact": contact,
        "part": {
            "original_filename": original_name,
            "stored_file": stored_path.name,
            "material": part["material"],
            "units": part["units"],
            "quantity": part["quantity"],
            "notes": part["notes"],
        },
        "summary": summary,
        "quote": payload,
    }


def _append_record(requests_log: Path, record: dict[str, Any]) -> None:
    requests_log.parent.mkdir(parents=True, exist_ok=True)
    with requests_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _read_records(requests_log: Path) -> list[dict[str, Any]]:
    if not requests_log.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in requests_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
