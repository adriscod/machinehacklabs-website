from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QUOTE_HTML = (REPO / "quote" / "index.html").read_text(encoding="utf-8")
TEMPLATE = (REPO / "mhl-quote" / "templates" / "bid-email.txt").read_text(encoding="utf-8")


def test_quote_page_is_quotes_inbox_and_machining_only() -> None:
    html = QUOTE_HTML
    assert "quotes@machinehacklabs.com" in html
    assert 'name="attachment"' in html
    assert 'name="due_date"' in html
    assert 'name="tolerances"' in html
    assert "finish" not in html.lower() or "does not quote finishes" in html.lower()
    assert "5-axis" in html.lower()  # mentioned as out of scope
    assert 'name="five_axis"' not in html
    assert 'name="turning"' not in html
    assert 'name="finish"' not in html


def test_quote_page_estimate_is_not_bid_and_pay_link_accepts() -> None:
    lower = QUOTE_HTML.lower()
    assert "not a final bid" in lower
    assert "shop-only" in lower
    assert "paying that link accepts the stated scope and price" in lower
    assert "chase payment link" in lower
    assert "deposit now" in lower
    assert "no installment" in lower
    assert "scrap is not billed" in lower
    assert "does not take cards" in lower
    assert 'type="tel"' in QUOTE_HTML  # phone, not a card field
    assert "card number" not in lower
    assert "card-number" not in lower
    assert 'name="card"' not in lower


def test_thanks_and_home_state_estimate_vs_accept() -> None:
    thanks = (REPO / "thanks" / "index.html").read_text(encoding="utf-8").lower()
    home = (REPO / "index.html").read_text(encoding="utf-8").lower()
    assert "not a final bid" in thanks
    assert "paying that link accepts the stated scope and price" in thanks
    assert "does not take payment" in thanks
    assert "not a final bid" in home
    assert "chase payment link accepts the stated scope and price" in home


def test_bid_email_template_is_pay_to_accept() -> None:
    lower = TEMPLATE.lower()
    assert "{chase_payment_link}" in lower
    assert "{bid_usd}" in lower
    assert "{deposit_usd}" in lower
    assert "{scope}" in lower
    assert "not a final bid" in lower
    assert "accepts this stated scope and price" in lower
    assert "materials + tooling floor" in lower
    assert "no installment" in lower
    assert "not billed" in lower
    assert "chase business account" in lower
    assert "does not take cards" in lower


def test_readme_and_autoresponse_cover_template_usage() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8").lower()
    assert "mhl-quote/templates/bid-email.txt" in readme
    assert "pasteable url" in readme
    assert "no chase api" in readme
    assert "no card capture" in readme
    rfq = json.loads((REPO / "assets" / "config" / "rfq.json").read_text(encoding="utf-8"))
    auto = rfq["autoresponse"].lower()
    assert "not a final bid" in auto
    assert "does not include pricing" in auto
    assert "paying the chase payment link" in auto


def _shop_hidden_keys() -> list[str]:
    text = (REPO / "assets" / "js" / "estimator.js").read_text(encoding="utf-8")
    start = text.index("export const SHOP_HIDDEN_FIELD_KEYS = [")
    end = text.index("];", start)
    return re.findall(r'"([a-z0-9_]+)"', text[start:end])


def test_quote_page_wires_rfq_v2_controls_and_shop_hiddens() -> None:
    html = QUOTE_HTML
    assert 'id="material_filter"' in html
    assert 'id="material"' in html and 'name="material"' in html
    assert 'name="material_source"' in html
    assert 'value="shop_buys"' in html
    assert 'value="customer_supplied"' in html
    assert 'name="turnaround"' in html
    assert 'value="standard"' in html
    assert 'value="rush"' in html
    assert 'value="emergency"' in html
    assert 'name="due_date"' in html
    assert "not price-inert" in html
    assert 'name="setups"' in html
    assert 'name="tolerance_class"' in html
    assert 'value="tight"' in html
    assert 'value="precision"' in html
    for risk in ("deep_pockets", "thin_walls", "fine_engraving", "many_holes"):
        assert f'value="{risk}"' in html
    assert 'name="stock_x"' in html
    assert 'name="stock_y"' in html
    assert 'name="stock_z"' in html
    for key in _shop_hidden_keys():
        assert f'name="{key}"' in html, key
        if key not in {
            "material_source",
            "turnaround",
            "setups",
            "qty",
            "tolerance_class",
            "feature_risks",
            "due_date",
        }:
            assert f'<input type="hidden" name="{key}"' in html, key


def test_home_points_at_quote_route() -> None:
    html = (REPO / "index.html").read_text(encoding="utf-8")
    assert 'href="/quote/"' in html
    assert "quotes@machinehacklabs.com" in html


def test_readme_documents_shop_job_tracker() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "shop job tracker" in text.lower()
    assert "http://127.0.0.1:8765/__shop/" in text
    assert "shop_jobs.py" in text
    assert "Estimator band" in text
    assert "bid" in text
    assert "Chase" in text
    assert "Scrap is not billed" in text
    assert "acceptance of the stated scope and price" in text


def test_marketing_pages_do_not_link_shop_tracker() -> None:
    for rel in ("index.html", "quote/index.html", "thanks/index.html"):
        html = (REPO / rel).read_text(encoding="utf-8")
        assert 'href="/__shop' not in html
        assert "<h1>Shop job tracker" not in html
