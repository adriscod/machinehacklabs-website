from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
YAML_PATH = REPO / "mhl-quote" / "config" / "quote.yaml"
JSON_PATH = REPO / "assets" / "config" / "quote-config.json"
RFQ_PATH = REPO / "assets" / "config" / "rfq.json"


def test_site_json_matches_yaml() -> None:
    yaml_data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    json_data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert json_data == json.loads(json.dumps(yaml_data))
    assert json_data["shop"]["rate_usd_per_hr"] == 75
    assert json_data["machine"]["envelope_in"]["x"] == 19.7


def test_rfq_inbox_is_quotes_at() -> None:
    rfq = json.loads(RFQ_PATH.read_text(encoding="utf-8"))
    assert rfq["quotesInbox"] == "quotes@machinehacklabs.com"
    assert "quotes@machinehacklabs.com" in rfq["productionFormAction"]
    assert rfq["localFormAction"] == "/__local_rfq"
    assert "not a final bid" in rfq["autoresponse"].lower()
