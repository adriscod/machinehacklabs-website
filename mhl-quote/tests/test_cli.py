from __future__ import annotations

import json
from pathlib import Path

import pytest

from mhl_quote.cli import EXIT_OK, EXIT_REJECTED, EXIT_USAGE, main
from mhl_quote.config import load_config
from tests.stl_box import write_axis_aligned_box_stl

CONFIG = Path(__file__).resolve().parents[1] / "config" / "quote.yaml"


def test_cli_quotes_stl_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stl = write_axis_aligned_box_stl(tmp_path / "part.stl", 2.0, 1.5, 0.75)
    code = main(
        [
            str(stl),
            "--config",
            str(CONFIG),
            "--material",
            "aluminum",
            "--json",
        ]
    )
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["geometry"]["bbox_in"]["x"] == pytest.approx(2.0, abs=1e-3)
    assert payload["cost"]["quote_low_usd"] < payload["cost"]["raw_quote_usd"]
    assert payload["cost"]["raw_quote_usd"] < payload["cost"]["quote_high_usd"]
    assert payload["cost"]["shop_rate_usd_per_hr"] == 75
    assert payload["envelope"]["fits"] is True


def test_cli_rejects_over_envelope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stl = write_axis_aligned_box_stl(tmp_path / "huge.stl", 2.0, 1.0, 1.0)
    code = main(
        [
            str(stl),
            "--config",
            str(CONFIG),
            "--stock-x",
            "22",
            "--stock-y",
            "1",
            "--stock-z",
            "1",
            "--json",
        ]
    )
    assert code == EXIT_REJECTED
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert payload["cost"] is None
    assert payload["envelope"]["fits"] is False
    assert any("REJECTED" in r for r in payload["rejection_reasons"])


def test_cli_rejects_finish_five_axis_turning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_axis_aligned_box_stl(tmp_path / "part.stl", 1.0, 1.0, 1.0)
    code = main(
        [str(stl), "--config", str(CONFIG), "--finish", "--five-axis", "--turning", "--json"]
    )
    assert code == EXIT_REJECTED
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert payload["cost"] is None
    assert len(payload["rejection_reasons"]) == 3


def test_cli_list_materials(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--config", str(CONFIG), "--list-materials"])
    assert code == EXIT_OK
    out = capsys.readouterr().out.lower()
    assert "aluminum" in out
    assert "steel" in out


def test_cli_missing_file(tmp_path: Path) -> None:
    code = main(["--config", str(CONFIG), str(tmp_path / "nope.stl")])
    assert code == EXIT_USAGE


def test_default_config_loads_shop_rate() -> None:
    config = load_config(CONFIG)
    assert config.shop.rate_usd_per_hr == 75
    assert config.machine.envelope_in.x == 19.7
    assert config.machine.envelope_in.y == 13.8
    assert config.machine.envelope_in.z == 14.0
