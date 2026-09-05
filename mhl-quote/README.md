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
python -m mhl_quote samples\demo_block.stl --material aluminum
```

STEP volume (preferred for confirming a web high-side estimate):

```bat
python -m pip install -r requirements-step.txt
python -m mhl_quote path\to\part.step --units mm --material steel
```

| Flag | Purpose |
| --- | --- |
| `--units inch\|mm` | CAD units |
| `--material aluminum\|steel\|…` | Catalog key or alias |
| `--qty 3` | Setup once; cut + catalog material scale |
| `--setup-hours` / `--mrr` / `--stock-x/y/z` / `--stock-cost` | Overrides |
| `--json` | Machine-readable result |

`--finish`, `--five-axis`, `--turning` fail closed.

## Cost model

```
stock_vol = bbox_x * bbox_y * bbox_z
part_vol = solid volume
removal_vol = max(0, stock_vol - part_vol)
cut_hours = (removal_vol / MRR_eff) * qty
labor = (setup_hours + cut_hours) * 75
materials = catalog $/in³ * stock_vol * qty   (or --stock-cost invoice)
raw = max(materials + labor, min_charge)
range = raw * 0.85  …  raw * 1.25
```

Scrap is not billed. Always a range.

## How to calibrate MRR

1. Take a finished 3-axis job.
2. Run the CLI (or use the web bbox/volume) and note removal in³.
3. Chip-making hours only from the traveler.
4. `actual_mrr = removal_in3 / actual_cut_hours`.
5. Average aluminum and steel separately; put a slightly conservative number
   in `config/quote.yaml` → `mrr_eff_in3_per_hr`.
6. Re-export site JSON. Past jobs should land in the 0.85–1.25 band.

Starting bands: aluminum ~8–15 in³/hr (default 12); steel ~3–8 (default 5).

## Tests

```bat
python -m pip install pytest
python -m pytest
node --test ..\assets\js\estimator.test.mjs
```

Do not deploy or publish until Andrew says so.
