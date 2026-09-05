# mhl-quote (calibration helper)

The **customer product** is the website RFQ form at `/quote/`, which emails
**quotes@machinehacklabs.com**. This folder is the shop-side helper:

- YAML source of truth for the cost model
- CLI for STEP solid volume (CadQuery) and MRR calibration
- Local site server that captures RFQs **without sending email**
- Local shop job ledger for the quotes@ → Chase payment journey

Ticket: **MHL-CF-001**. Machine: **Tormach 1500MX** (3-axis mill only).

## Website (primary)

From the repo root:

```bat
python mhl-quote\dev_rfq_server.py
```

Open http://127.0.0.1:8765/quote/

Local submits go to `mhl-quote/.local-inbox/` and **do not** email quotes@.
Each local capture also stubs a shop job in `mhl-quote/.local-jobs/`
(estimated / unpaid) so Andrew can set the bid and paste a Chase link.
Live delivery (after publish, not this draft) uses FormSubmit to
`quotes@machinehacklabs.com`. See the repo README.

Customer-facing copy: the website estimate is not a final bid. Andrew
sends a bid from `templates/bid-email.txt` (scope, materials+tooling
deposit, pasted Chase payment / invoice URL). Paying that link accepts
the stated scope and price. Deposit then balance before ship. No Chase
API and no card capture on the site. Scrap is not billed.

## Shop job tracker (after quotes@)

Andrew records each RFQ/job for the payment journey. Smallest useful
ledger: one JSON file per job in `.local-jobs/` (gitignored). Not an
accounting suite. No Chase API — he creates the payment request himself
and pastes the URL (same URL that goes in `{CHASE_PAYMENT_LINK}`).

Workflow: estimated → proceeded → bid sent → deposit paid → scheduled →
balanced → shipped.

Payment: unpaid / deposit paid / balanced (paid in full).

```bat
python mhl-quote\shop_jobs.py new --id MHL-1001 --estimate-low 110 --estimate-high 162
python mhl-quote\shop_jobs.py from-inbox 20260905T143000Z
python mhl-quote\shop_jobs.py set MHL-1001 --bid 145 --deposit 60 --chase-url https://secure.chase.com/your-request --status bid_sent
python mhl-quote\shop_jobs.py list
```

Or open http://127.0.0.1:8765/__shop/ while the local server is running.

Policy stored on every job file:

- Estimate band is a shop rough range, not the customer bid.
- Deposit is a materials + tooling floor, not a fixed percent.
- Paying the pasted Chase link is acceptance of the stated scope and price.
- Deposit, then balance, then ship. Scrap is not billed to the customer.
- This site never captures cards or auto-charges.

After editing `config/quote.yaml`:

```bat
python mhl-quote\scripts\export_site_config.py
```

## CLI (helper)

```bat
cd mhl-quote
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m mhl_quote samples\demo_block.stl --material al_6061
```

STEP volume (preferred for confirming a web high-side estimate):

```bat
python -m pip install -r requirements-step.txt
python -m mhl_quote path\to\part.step --units mm --material steel
```

| Flag | Purpose |
| --- | --- |
| `--units inch\|mm` | CAD units |
| `--material al_6061\|steel_1018\|…` | Catalog key or alias (`aluminum` → 6061) |
| `--qty 3` | Cut hours + catalog material scale |
| `--setups 2` | Scales setup hours (min 1) |
| `--material-source shop_buys\|customer_supplied` | Customer stock → material $ = 0 |
| `--turnaround standard\|rush\|emergency` | Rush mults are YAML starting points |
| `--due-date YYYY-MM-DD` | Auto-bumps turnaround if the calendar is tighter |
| `--tolerance standard\|tight\|precision` | Multiplies cut hours; precision → shop review |
| `--feature-risk deep_pockets` (repeatable) | +0.15 each, complexity cap 1.75 |
| `--setup-hours` / `--mrr` / `--stock-x/y/z` / `--stock-cost` | Overrides |
| `--json` | Machine-readable result |

`--finish`, `--five-axis`, `--turning` fail closed.

## Cost model (RFQ v2)

```
stock_vol = bbox (or stock override X/Y/Z) volume in³
part_vol = solid volume in³
removal_vol = max(0, stock_vol − part_vol)
cut_hours = (removal_vol / MRR_eff) × qty × complexity_mult
setup_hours = base_setup_hours × setups × rush_setup_mult
labor_$ = (setup_hours + cut_hours) × shop_rate × rush_labor_mult
material_$ = shop_buys ? catalog $/in³ × stock_vol × qty : 0
raw_$ = max(material_$ + labor_$, min_charge × rush_labor_mult)
range = raw_$ × 0.85  …  raw_$ × 1.25
```

`complexity_mult = min(1.75, tolerance_mult + n_feature_risks × 0.15)`

Tolerance: standard 1.0, tight 1.25, precision 1.5 (precision → shop review).

Turnaround starting points (tune in YAML, not code):

| Tier | labor | setup | min business days |
| --- | --- | --- | --- |
| standard | 1.0 | 1.0 | 10 |
| rush | 1.5 | 1.25 | 4 |
| emergency | 2.0 | 1.5 | 1 |

If `due_date` is tighter than the selected tier, the estimator auto-bumps
and sets `shop_review_required`. Business days are Mon–Fri only.

Scrap is not billed. Always a range. Not a customer-facing final quote.

## How Andrew replaces TODO costs / MRR

Every catalog `cost_usd_per_in3` and `mrr_eff_in3_per_hr` is a
**TODO_REPLACE placeholder**, not a market rate.

1. Edit `config/quote.yaml` for the grade (`al_6061`, `ss_304`, …).
2. Replace `cost_usd_per_in3` from a real stock invoice ($/in³ of the
   plate or bar you actually buy). Leave scrap unbilled.
3. Replace `mrr_eff_in3_per_hr` from a finished job:
   `actual_mrr = removal_in3 / chip_hours`. Use a slightly conservative number.
4. Change `cost_placeholder` / `mrr_placeholder` from `TODO_REPLACE` to
   `false` once that grade is calibrated.
5. Set `enabled: false` to hide a grade from the website dropdown.
6. Re-export: `python mhl-quote/scripts/export_site_config.py`

Rush / emergency multipliers and lead days are **starting points**. Change
them under `turnaround:` in the same YAML.

Starting MRR bands (placeholders): aluminum ~8–15 in³/hr; steel ~3–8;
stainless lower; plastics higher. Do not treat the YAML dollars as quotes.

## /quote/ UI teammate — inputs to wire

Do not treat this folder as owning the form markup. The estimator APIs
are additive. Pass these into `estimateFromGeometry` / `computeCost`
(`assets/js/estimator.js`) and copy `result.shop_payload` into FormSubmit
hidden fields.

**Visible / pricing inputs**

| Field | Values | Effect |
| --- | --- | --- |
| `material` | catalog key (`al_6061`, …) | Use `listEnabledMaterials(config)` for the dropdown. `aluminum`/`steel` aliases still resolve. |
| `material_source` | `shop_buys` \| `customer_supplied` | Customer stock → `material_usd = 0` |
| `turnaround` | `standard` \| `rush` \| `emergency` | Labor + setup multipliers |
| `due_date` | `YYYY-MM-DD` | Not price-inert; may auto-bump turnaround |
| `setups` | integer ≥ 1 (default 1) | Scales setup hours |
| `tolerance_class` | `standard` \| `tight` \| `precision` | Cut-time mult; precision forces shop review |
| `feature_risks` | optional multi: `deep_pockets`, `thin_walls`, `fine_engraving`, `many_holes` | +0.15 each, cap 1.75 |
| `stock_x_in` / `stock_y_in` / `stock_z_in` | optional inches | Replaces AABB as stock (all three together) |

**New shop-only hidden keys** (plus existing bbox / range / hours fields)

`material_key`, `material_family`, `material_source`, `turnaround`,
`turnaround_requested`, `turnaround_bumped`, `rush_labor_mult`,
`rush_setup_mult`, `setups`, `qty`, `tolerance_class`, `complexity_mult`,
`feature_risks`, `due_date_business_days`, `due_date_warning`,
`shop_review_required`, `shop_review_reasons`,
`catalog_values_are_placeholders`, `stock_x_in`, `stock_y_in`,
`stock_z_in`, `stock_override`

See `SHOP_HIDDEN_FIELD_KEYS` and `RFQ_V2_UI_INPUTS` in `assets/js/estimator.js`.
`/thanks/` must still show no pricing.

## Tests

```bat
python -m pip install pytest
python -m pytest
node --test ..\assets\js\estimator.test.mjs
```

Do not deploy or publish until Andrew says so.
