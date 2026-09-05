from __future__ import annotations

import json
from pathlib import Path

from mhl_quote.job_cli import EXIT_OK, EXIT_USAGE, main


def test_cli_new_set_list_advance(tmp_path: Path, capsys) -> None:
    jobs_dir = str(tmp_path)
    code = main(
        [
            "--jobs-dir",
            jobs_dir,
            "new",
            "--id",
            "MHL-CLI",
            "--estimate-low",
            "100",
            "--estimate-high",
            "140",
            "--json",
        ]
    )
    assert code == EXIT_OK
    created = json.loads(capsys.readouterr().out)
    assert created["job_id"] == "MHL-CLI"
    assert created["source"] == "quotes@"
    assert created["workflow_status"] == "estimated"

    code = main(
        [
            "--jobs-dir",
            jobs_dir,
            "set",
            "MHL-CLI",
            "--bid",
            "155",
            "--deposit",
            "50",
            "--chase-url",
            "https://secure.chase.com/pasted",
            "--status",
            "bid_sent",
            "--json",
        ]
    )
    assert code == EXIT_OK
    updated = json.loads(capsys.readouterr().out)
    assert updated["bid_usd"] == 155
    assert updated["deposit_usd"] == 50
    assert updated["chase_payment_url"] == "https://secure.chase.com/pasted"
    assert updated["workflow_status"] == "bid_sent"
    assert updated["payment_status"] == "unpaid"

    code = main(["--jobs-dir", jobs_dir, "advance", "MHL-CLI", "--json"])
    assert code == EXIT_OK
    advanced = json.loads(capsys.readouterr().out)
    assert advanced["workflow_status"] == "deposit_paid"
    assert advanced["payment_status"] == "deposit_paid"

    code = main(["--jobs-dir", jobs_dir, "list", "--json"])
    assert code == EXIT_OK
    listed = json.loads(capsys.readouterr().out)
    assert listed["jobs"][0]["job_id"] == "MHL-CLI"


def test_cli_from_inbox(tmp_path: Path, capsys) -> None:
    inbox = tmp_path / "inbox" / "INBOX1"
    inbox.mkdir(parents=True)
    (inbox / "rfq.json").write_text(
        json.dumps({"fields": {"email": "a@b.c", "quote_low_usd": "10", "quote_high_usd": "20"}}),
        encoding="utf-8",
    )
    code = main(
        [
            "--jobs-dir",
            str(tmp_path / "jobs"),
            "from-inbox",
            str(inbox),
            "--json",
        ]
    )
    assert code == EXIT_OK
    job = json.loads(capsys.readouterr().out)
    assert job["customer_email"] == "a@b.c"
    assert job["estimate_low_usd"] == 10


def test_cli_rejects_unknown_status(tmp_path: Path, capsys) -> None:
    main(["--jobs-dir", str(tmp_path), "new", "--id", "MHL-X"])
    capsys.readouterr()
    code = main(["--jobs-dir", str(tmp_path), "set", "MHL-X", "--status", "invoiced"])
    assert code == EXIT_USAGE
    assert "unknown workflow status" in capsys.readouterr().err


def test_cli_statuses_include_policy(capsys) -> None:
    assert main(["statuses"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "estimated → proceeded → bid_sent → deposit_paid → scheduled → balanced → shipped" in out
    assert "Estimate band" in out
