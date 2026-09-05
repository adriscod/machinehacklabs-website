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


def _visible_html(html: str) -> str:
    stripped = re.sub(r"<!--.*?-->", "", html, flags=re.S).lower()
    return re.sub(r"\s+", " ", stripped)


def test_quote_page_estimate_is_customer_visible_not_final_bid() -> None:
    lower = _visible_html(QUOTE_HTML)
    assert "estimate" in lower
    assert "not a final bid" in lower
    assert "shop-only" not in lower
    assert "for andrew only" not in lower
    assert "shop-only range for andrew" not in lower
    assert "not a customer bid" not in lower
    assert "andrew" not in lower
    assert "payment link arrives in that email after you proceed" in lower
    assert "does not take payment" in lower
    assert 'type="tel"' in QUOTE_HTML  # phone, not a card field
    assert "card number" not in lower
    assert "card-number" not in lower
    assert 'name="card"' not in lower
    assert 'name="card_number"' not in lower
    assert "chase" not in lower  # no Chase widget / pay-to-accept UI on the form


def test_rfq_panel_copy_is_customer_visible_estimate() -> None:
    js = (REPO / "assets" / "js" / "rfq-form.js").read_text(encoding="utf-8")
    assert "Shop-only rough range" not in js
    assert "shop-only high-side" not in js.lower()
    assert "Shop-only range" not in js
    assert "Andrew" not in js
    assert "<h2>Estimate range</h2>" in js
    assert "This is an estimate — not a final bid." in js
    assert "The shop confirms from quotes@" in js
    assert "A payment link arrives in that email" in js
    assert "function customerCallouts" in js


def test_thanks_and_home_do_not_contradict_customer_estimate() -> None:
    thanks = _visible_html((REPO / "thanks" / "index.html").read_text(encoding="utf-8"))
    home = _visible_html((REPO / "index.html").read_text(encoding="utf-8"))
    privacy = _visible_html((REPO / "privacy" / "index.html").read_text(encoding="utf-8"))
    caps = _visible_html((REPO / "capabilities" / "index.html").read_text(encoding="utf-8"))
    assert "not a final bid" in thanks
    assert "estimate you saw on the form" in thanks
    assert "does not take payment" in thanks
    assert "does not show pricing" in thanks
    assert "shop-only" not in thanks
    assert "andrew" not in thanks
    assert "payment link arrives in that email after you proceed" in thanks
    assert "shop-only" not in privacy
    assert "andrew" not in privacy
    assert "not a customer quote" not in privacy
    assert "estimate range is shown on the quote page" in privacy
    assert "not a final bid" in privacy
    assert "andrew" not in caps
    assert "shop placeholders" in caps
    assert "cnc milling for real parts" in home
    assert "href=\"/quote/\"" in (REPO / "index.html").read_text(encoding="utf-8")
    assert "shop-only" not in home
    assert "chase" not in home
    assert "$75" not in home


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
    assert "— andrew" not in lower
    assert not re.search(r"^— andrew\s*$", TEMPLATE, flags=re.I | re.M)


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
    assert "payment link arrives in that email after you proceed" in auto
    assert "shop-only" not in auto
    assert "andrew" not in auto
    assert "andrew" not in rfq["providerNotes"].lower()


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
    for rel in (
        "index.html",
        "quote/index.html",
        "thanks/index.html",
        "capabilities/index.html",
        "work/index.html",
        "contact/index.html",
        "privacy/index.html",
    ):
        html = (REPO / rel).read_text(encoding="utf-8")
        assert 'href="/__shop' not in html
        assert "<h1>Shop job tracker" not in html


def test_site_nav_and_footer_on_customer_pages() -> None:
    pages = {
        "index.html": "/",
        "capabilities/index.html": "/capabilities/",
        "work/index.html": "/work/",
        "quote/index.html": "/quote/",
        "thanks/index.html": "/thanks/",
        "contact/index.html": "/contact/",
        "privacy/index.html": "/privacy/",
    }
    for rel in pages:
        html = (REPO / rel).read_text(encoding="utf-8")
        assert 'href="/capabilities/"' in html
        assert 'href="/work/"' in html
        assert 'href="/quote/"' in html
        assert 'href="/privacy/"' in html
        assert "© 2026 Machine Hack Labs" in html
        assert "quotes@machinehacklabs.com" in html
        assert "#121212" not in html


def test_contact_is_quotes_and_quote_link_only() -> None:
    html = (REPO / "contact" / "index.html").read_text(encoding="utf-8")
    assert "<form" not in html.lower()
    assert 'href="/quote/"' in html
    assert "quotes@machinehacklabs.com" in html
    assert "no second form" in html.lower()


def test_capabilities_and_work_use_shop_photos_and_scope() -> None:
    caps = (REPO / "capabilities" / "index.html").read_text(encoding="utf-8")
    work = (REPO / "work" / "index.html").read_text(encoding="utf-8")
    home = (REPO / "index.html").read_text(encoding="utf-8")
    assert "19.7" in caps and "13.8" in caps and "14" in caps
    assert "no finishes" in caps.lower()
    assert "5-axis" in caps.lower()
    assert "turning" in caps.lower()
    assert "/assets/img/site/01-hero-probe-on-part.jpg" in home
    assert "/assets/img/site/02-capabilities-1500mx-cutting.jpg" in caps
    assert "/assets/img/site/03-capabilities-1500mx-coolant.jpg" in caps
    assert "/assets/img/site/04-work-cutting-action.jpg" in work
    assert "/assets/img/site/05-work-coolant-spray.jpg" in work
    assert "finish" not in work.lower() or "not finish" in work.lower()


def test_privacy_skeleton_covers_rfq_and_no_cards() -> None:
    html = (REPO / "privacy" / "index.html").read_text(encoding="utf-8").lower()
    assert "formsubmit" in html
    assert "quotes@machinehacklabs.com" in html
    assert "no cards" in html
    assert "skeleton" in html
