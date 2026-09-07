"""Machine Hack Labs RFQ web app.

A guided Request-for-Quote pipeline that wraps the local ``mhl_quote`` rough-quote
estimator:

    Home (/)  ->  RFQ Tool (/rfq)  ->  upload + 3D viewer  ->  rough quote  ->
    stored request + staged operator hand-off (/requests)

The tool only ever produces a ROUGH estimate range. A human operator at
``Quotes@machinehacklabs.com`` sends the ACTUAL formal quote and payment link.
This is an internal/local tool: it does not send email and stores no secrets.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote as urlquote

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from mhl_quote.config import ConfigError, QuoteConfig, load_config
from mhl_quote.geometry import GeometryError, measure_file, tessellate_to_stl
from mhl_quote.models import JobOverrides, LengthUnit, Timeline
from mhl_quote.quote import estimate_quote
from mhl_quote.report import result_to_jsonable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

OPERATOR_EMAIL = "Quotes@machinehacklabs.com"
CAD_EXTENSIONS = {".step", ".stp", ".stl"}
BLUEPRINT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".step", ".stp", ".dxf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEX_ID_RE = re.compile(r"^[0-9a-f]{8,40}$")


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

    def _rfq_context(**extra: Any) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "materials": _material_options(quote_config),
            "machine": quote_config.machine,
            "shop": quote_config.shop,
            "tolerances": quote_config.tolerances,
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        }
        ctx.update(extra)
        return ctx

    @app.route("/")
    def home() -> str:
        return render_template("home.html", shop=quote_config.shop, machine=quote_config.machine)

    @app.route("/rfq")
    def rfq() -> str:
        return render_template("rfq.html", **_rfq_context())

    @app.route("/rfq/upload", methods=["POST"])
    def upload() -> Any:
        upload_file = request.files.get("cad_file")
        try:
            draft = _store_cad_upload(upload_file, upload_root)
        except RfqError as exc:
            return jsonify({"error": str(exc)}), 400
        except GeometryError as exc:
            return jsonify({"error": f"Could not read that file: {exc}"}), 400
        return jsonify(
            {
                "draft_id": draft["draft_id"],
                "original_name": draft["original_name"],
                "format": draft["format"],
                "bbox_in": draft["bbox_in"],
                "mesh_url": url_for("mesh", draft_id=draft["draft_id"]),
            }
        )

    @app.route("/api/mesh/<draft_id>")
    def mesh(draft_id: str) -> Any:
        if not HEX_ID_RE.match(draft_id):
            abort(404)
        mesh_path = upload_root / f"{draft_id}.mesh.stl"
        if not mesh_path.is_file():
            abort(404)
        return send_file(mesh_path, mimetype="model/stl", download_name=f"{draft_id}.stl")

    @app.route("/quote", methods=["POST"])
    def submit_quote() -> Any:
        try:
            contact = _parse_contact(request.form)
            part = _parse_part(request.form)
            draft = _resolve_cad(request, upload_root)
            blueprint = _resolve_blueprint(request, upload_root, draft["draft_id"], part)
        except RfqError as exc:
            return (
                render_template("rfq.html", **_rfq_context(error=str(exc), form=request.form)),
                400,
            )
        except GeometryError as exc:
            return (
                render_template(
                    "rfq.html",
                    **_rfq_context(error=f"Could not read that file: {exc}", form=request.form),
                ),
                400,
            )

        overrides = JobOverrides(
            quantity=part["quantity"],
            timeline=Timeline.RUSH if part["rush"] else Timeline.STANDARD,
            tight_callouts=part["tight_callouts"],
            whole_part_tight=part["whole_part_tight"],
        )
        try:
            result = estimate_quote(
                cad_path=draft["stored_path"],
                config=quote_config,
                material_name=part["material"],
                unit=LengthUnit.INCH if part["units"] == "inch" else LengthUnit.MM,
                overrides=overrides,
            )
        except (ConfigError, GeometryError, ValueError) as exc:
            return (
                render_template(
                    "rfq.html",
                    **_rfq_context(error=f"Could not quote that file: {exc}", form=request.form),
                ),
                400,
            )

        rfq_id = _new_rfq_id()
        record = _build_record(
            rfq_id=rfq_id,
            contact=contact,
            part=part,
            draft=draft,
            blueprint=blueprint,
            result=result,
        )
        _append_record(requests_log, record)
        return render_template("result.html", record=record, result=result)

    @app.route("/requests")
    def list_requests() -> str:
        records = _read_records(requests_log)
        records.reverse()
        return render_template("requests.html", records=records, operator_email=OPERATOR_EMAIL)

    @app.route("/requests/<rfq_id>/operator", methods=["POST"])
    def update_operator(rfq_id: str) -> Any:
        payment_link = (request.form.get("payment_link") or "").strip()
        mark_sent = request.form.get("mark_sent") == "on"
        on_shelf = request.form.get("material_on_shelf") == "on"

        def mutate(record: dict[str, Any]) -> None:
            operator = record.setdefault("operator", {})
            operator["payment_link"] = payment_link
            operator["sent_to_operator"] = mark_sent
            record.setdefault("part", {})["material_on_shelf"] = on_shelf

        if not _update_record(requests_log, rfq_id, mutate):
            abort(404)
        return redirect(url_for("list_requests") + f"#{rfq_id}")

    @app.route("/healthz")
    def healthz() -> Any:
        return {"status": "ok", "config": quote_config.source_path}, 200

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc: RequestEntityTooLarge) -> Any:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return (
            render_template(
                "rfq.html",
                **_rfq_context(error=f"That file is too large (limit {limit_mb} MB)."),
            ),
            413,
        )

    return app


def _material_options(config: QuoteConfig) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for spec in config.materials.values():
        standard = config.tolerances.standard_for(spec.material_class)
        options.append(
            {
                "key": spec.key,
                "label": spec.label,
                "material_class": spec.material_class.value,
                "standard_tol_in": standard,
            }
        )
    return options


def _parse_contact(form: Any) -> dict[str, str]:
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    address = (form.get("address") or "").strip()
    company = (form.get("company") or "").strip()
    phone = (form.get("phone") or "").strip()
    if not name:
        raise RfqError("Your name is required.")
    if not EMAIL_RE.match(email):
        raise RfqError("A valid email address is required.")
    if len(address) < 6:
        raise RfqError("A valid mailing address is required.")
    return {"name": name, "email": email, "address": address, "company": company, "phone": phone}


def _parse_part(form: Any) -> dict[str, Any]:
    material = (form.get("material") or "").strip().lower()
    units = (form.get("units") or "inch").strip().lower()
    notes = (form.get("notes") or "").strip()
    quantity_raw = (form.get("quantity") or "1").strip()
    timeline = (form.get("timeline") or "standard").strip().lower()
    tolerance = (form.get("tolerance") or "standard").strip().lower()
    tight_callouts_raw = (form.get("tight_callouts") or "0").strip()
    whole_part_tight = form.get("whole_part_tight") == "on"
    material_cert = form.get("material_cert") == "on"
    tapped_holes = form.get("tapped_holes") == "on"
    part_marking = form.get("part_marking") == "on"

    if units not in {"inch", "mm"}:
        raise RfqError("Units must be inch or mm.")
    if timeline not in {"standard", "rush"}:
        raise RfqError("Timeline must be standard or rush.")
    if tolerance not in {"standard", "tight"}:
        raise RfqError("Tolerance must be standard or tight.")
    if not material:
        raise RfqError("Please choose a material.")
    try:
        quantity = int(quantity_raw)
    except ValueError as exc:
        raise RfqError("Quantity must be a whole number.") from exc
    if quantity < 1:
        raise RfqError("Quantity must be at least 1.")
    try:
        tight_callouts = int(tight_callouts_raw)
    except ValueError as exc:
        raise RfqError("Tight-tolerance callout count must be a whole number.") from exc
    if tight_callouts < 0:
        raise RfqError("Tight-tolerance callout count cannot be negative.")

    if tolerance == "standard":
        tight_callouts = 0
        whole_part_tight = False
    elif not whole_part_tight and tight_callouts < 1:
        raise RfqError(
            "For tight tolerance, enter at least one tight callout or check "
            "'whole part is tight'."
        )

    return {
        "material": material,
        "units": units,
        "notes": notes,
        "quantity": quantity,
        "timeline": timeline,
        "rush": timeline == "rush",
        "tolerance": tolerance,
        "tight_callouts": tight_callouts,
        "whole_part_tight": whole_part_tight,
        "material_cert": material_cert,
        "tapped_holes": tapped_holes,
        "part_marking": part_marking,
    }


def _store_cad_upload(upload: Any, upload_root: Path) -> dict[str, Any]:
    """Save a CAD upload, tessellate it to a render mesh, and write a sidecar."""
    if upload is None or not upload.filename:
        raise RfqError("Please attach a STEP or STL file.")
    original_name = secure_filename(upload.filename)
    suffix = Path(original_name).suffix.lower()
    if suffix not in CAD_EXTENSIONS:
        allowed = ", ".join(sorted(CAD_EXTENSIONS))
        raise RfqError(f"Unsupported file type {suffix or '(none)'}; allowed: {allowed}.")

    draft_id = uuid.uuid4().hex
    stored_path = upload_root / f"{draft_id}{suffix}"
    upload.save(str(stored_path))
    if stored_path.stat().st_size == 0:
        stored_path.unlink(missing_ok=True)
        raise RfqError("The uploaded file was empty.")

    mesh_path = upload_root / f"{draft_id}.mesh.stl"
    # STEP is often modeled in mm; measuring for the viewer bbox is best-effort.
    tessellate_to_stl(stored_path, mesh_path)

    fmt = "step" if suffix in {".step", ".stp"} else "stl"
    bbox = _safe_bbox(stored_path, fmt)
    sidecar = {
        "draft_id": draft_id,
        "original_name": original_name,
        "stored_file": stored_path.name,
        "mesh_file": mesh_path.name,
        "format": fmt,
        "bbox_in": bbox,
    }
    (upload_root / f"{draft_id}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return {**sidecar, "stored_path": stored_path}


def _safe_bbox(stored_path: Path, fmt: str) -> dict[str, float] | None:
    unit = LengthUnit.MM if fmt == "step" else LengthUnit.INCH
    try:
        geo = measure_file(stored_path, unit)
    except GeometryError:
        return None
    return geo.bbox_in.to_mapping()


def _resolve_cad(req: Any, upload_root: Path) -> dict[str, Any]:
    """Prefer an async-uploaded draft; otherwise accept the file in the POST."""
    draft_id = (req.form.get("draft_id") or "").strip().lower()
    if draft_id and HEX_ID_RE.match(draft_id):
        sidecar_path = upload_root / f"{draft_id}.json"
        if sidecar_path.is_file():
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            stored_path = upload_root / sidecar["stored_file"]
            if stored_path.is_file():
                return {**sidecar, "stored_path": stored_path}
    upload_file = req.files.get("cad_file")
    return _store_cad_upload(upload_file, upload_root)


def _resolve_blueprint(
    req: Any, upload_root: Path, draft_id: str, part: dict[str, Any]
) -> dict[str, Any] | None:
    upload = req.files.get("blueprint_file")
    tight = part["tolerance"] == "tight"
    has_file = upload is not None and bool(upload.filename)
    if not has_file:
        if tight:
            raise RfqError(
                "A blueprint / drawing is required whenever tight tolerance is requested."
            )
        return None

    original = secure_filename(upload.filename)
    suffix = Path(original).suffix.lower()
    if suffix not in BLUEPRINT_EXTENSIONS:
        allowed = ", ".join(sorted(BLUEPRINT_EXTENSIONS))
        raise RfqError(f"Unsupported blueprint type {suffix or '(none)'}; allowed: {allowed}.")
    stored = upload_root / f"{draft_id}.blueprint{suffix}"
    upload.save(str(stored))
    if stored.stat().st_size == 0:
        stored.unlink(missing_ok=True)
        raise RfqError("The uploaded blueprint was empty.")
    return {"original_name": original, "stored_file": stored.name}


def _new_rfq_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"RFQ-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _build_record(
    *,
    rfq_id: str,
    contact: dict[str, str],
    part: dict[str, Any],
    draft: dict[str, Any],
    blueprint: dict[str, Any] | None,
    result: Any,
) -> dict[str, Any]:
    payload = result_to_jsonable(result)
    cost = payload.get("cost")
    summary = {
        "status": payload["status"],
        "rejection_reasons": payload["rejection_reasons"],
        "quote_low_usd": cost["quote_low_usd"] if cost else None,
        "quote_high_usd": cost["quote_high_usd"] if cost else None,
        "per_part_low_usd": cost["per_part_low_usd"] if cost else None,
        "per_part_high_usd": cost["per_part_high_usd"] if cost else None,
    }
    part_record = {
        "original_filename": draft["original_name"],
        "stored_file": draft["stored_file"],
        "mesh_file": draft.get("mesh_file"),
        "format": draft.get("format"),
        "material": part["material"],
        "units": part["units"],
        "quantity": part["quantity"],
        "timeline": part["timeline"],
        "tolerance": part["tolerance"],
        "tight_callouts": part["tight_callouts"],
        "whole_part_tight": part["whole_part_tight"],
        "material_cert": part["material_cert"],
        "tapped_holes": part["tapped_holes"],
        "part_marking": part["part_marking"],
        "material_on_shelf": False,
        "notes": part["notes"],
    }
    if blueprint:
        part_record["blueprint"] = blueprint

    record = {
        "rfq_id": rfq_id,
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contact": contact,
        "part": part_record,
        "summary": summary,
        "quote": payload,
    }
    record["operator"] = _build_operator_handoff(record)
    return record


def _build_operator_handoff(record: dict[str, Any]) -> dict[str, Any]:
    """Stage an operator-ready email draft + mailto. Nothing is actually sent."""
    subject = _operator_subject(record)
    body = _operator_body(record)
    mailto = (
        f"mailto:{OPERATOR_EMAIL}"
        f"?subject={urlquote(subject)}&body={urlquote(body)}"
    )
    return {
        "to": OPERATOR_EMAIL,
        "subject": subject,
        "body": body,
        "mailto": mailto,
        "sent_to_operator": False,
        "payment_link": "",
    }


def _operator_subject(record: dict[str, Any]) -> str:
    part = record["part"]
    return (
        f"[{record['rfq_id']}] {record['contact']['name']} — "
        f"{part['material']} x{part['quantity']}"
    )


def _operator_body(record: dict[str, Any]) -> str:
    contact = record["contact"]
    part = record["part"]
    summary = record["summary"]
    cost = record["quote"].get("cost")
    lines = [
        f"RFQ {record['rfq_id']} received {record['received_at']}",
        "",
        "CUSTOMER",
        f"  Name:    {contact['name']}",
        f"  Email:   {contact['email']}",
        f"  Address: {contact['address']}",
    ]
    if contact.get("company"):
        lines.append(f"  Company: {contact['company']}")
    if contact.get("phone"):
        lines.append(f"  Phone:   {contact['phone']}")
    lines += [
        "",
        "PART",
        f"  File:      {part['original_filename']} ({part.get('format', '?')})",
        f"  Material:  {part['material']}",
        f"  Quantity:  {part['quantity']}",
        f"  Timeline:  {part['timeline']}",
        f"  Tolerance: {part['tolerance']}"
        + (
            f" (whole part tight)"
            if part["whole_part_tight"]
            else f" ({part['tight_callouts']} tight callout(s))"
            if part["tight_callouts"]
            else ""
        ),
        f"  Cert:      {'yes' if part['material_cert'] else 'no'}"
        f"  · Tapped/threaded: {'yes' if part['tapped_holes'] else 'no'}"
        f"  · Marking: {'yes' if part['part_marking'] else 'no'}",
    ]
    if part.get("blueprint"):
        lines.append(f"  Blueprint: {part['blueprint']['original_name']}")
    if part.get("notes"):
        lines.append(f"  Notes:     {part['notes']}")

    lines += ["", "ROUGH ESTIMATE (internal — send a formal quote after review)"]
    if summary["status"] == "ok" and cost:
        lines += [
            f"  Per part:  ${cost['per_part_low_usd']:.2f} – ${cost['per_part_high_usd']:.2f}",
            f"  Batch:     ${cost['quote_low_usd']:.2f} – ${cost['quote_high_usd']:.2f}",
            f"  Labor:     ${cost['per_part_labor_usd']:.2f}/part @ ${cost['shop_rate_usd_per_hr']:g}/hr",
            f"  Material:  ${cost['per_part_material_usd']:.2f}/part",
        ]
        if cost.get("guardrail_callout"):
            lines.append(f"  Guardrail: {cost['guardrail_callout']}")
    else:
        lines.append("  NOT auto-quotable:")
        for reason in summary["rejection_reasons"]:
            lines.append(f"    - {reason}")

    lines += [
        "",
        "NEXT: reply to the customer with the formal quote and a Chase payment link.",
    ]
    return "\n".join(lines)


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


def _update_record(
    requests_log: Path, rfq_id: str, mutate: Any
) -> bool:
    records = _read_records(requests_log)
    found = False
    for record in records:
        if record.get("rfq_id") == rfq_id:
            mutate(record)
            found = True
    if not found:
        return False
    lines: Iterable[str] = (json.dumps(rec) for rec in records)
    requests_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
