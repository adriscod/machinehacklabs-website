from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_quote_page_is_quotes_inbox_and_machining_only() -> None:
    html = (REPO / "quote" / "index.html").read_text(encoding="utf-8")
    assert "quotes@machinehacklabs.com" in html
    assert 'name="attachment"' in html
    assert 'name="due_date"' in html
    assert 'name="tolerances"' in html
    assert "finish" not in html.lower() or "does not quote finishes" in html.lower()
    assert "5-axis" in html.lower()  # mentioned as out of scope
    assert 'name="five_axis"' not in html
    assert 'name="turning"' not in html
    assert 'name="finish"' not in html


def test_home_points_at_quote_route() -> None:
    html = (REPO / "index.html").read_text(encoding="utf-8")
    assert 'href="/quote/"' in html
    assert "quotes@machinehacklabs.com" in html
