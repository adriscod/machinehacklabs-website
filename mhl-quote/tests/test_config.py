from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mhl_quote.config import ConfigError, find_material, load_config

YAML_CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"


def test_json_config_round_trip(tmp_path: Path) -> None:
    raw = yaml.safe_load(YAML_CONFIG.read_text(encoding="utf-8"))
    json_path = tmp_path / "quote.json"
    json_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(json_path)
    assert config.shop.rate_usd_per_hr == 75
    assert config.materials["steel"].mrr_eff_in3_per_hr == 5.0
    assert find_material(config, "1018").key == "steel"
    assert find_material(config, "6061-T6").key == "aluminum"


def test_unknown_material() -> None:
    config = load_config(YAML_CONFIG)
    with pytest.raises(ConfigError, match="titanium"):
        find_material(config, "titanium")


def test_missing_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")
