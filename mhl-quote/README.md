# mhl-quote (calibration helper)

The **customer product** is the website RFQ form at `/quote/`, which emails
**quotes@machinehacklabs.com**. This folder is the shop-side helper:

- YAML source of truth for the cost model
- CLI for STEP solid volume (CadQuery) and MRR calibration
- Local site server that captures RFQs **without sending email**

Ticket: **MHL-CF-001**. Machine: **Tormach 1500MX** (3-axis mill only).

## Website (primary)

From the repo root:

```bat
python mhl-quote\dev_rfq_server.py
```

Open http://127.0.0.1:8765/quote/

Local submits go to `mhl-quote/.local-inbox/` and **do not** email quotes@.
Live delivery (after publish, not this draft) uses FormSubmit to
`quotes@machinehacklabs.com`. See the repo README.

Customer-facing copy: the website estimate is not a final bid. Andrew
sends a bid from `templates/bid-email.txt` (scope, materials+tooling
deposit, pasted Chase payment / invoice URL). Paying that link accepts
the stated scope and price. Deposit then balance before ship. No Chase
API and no card capture on the site. Scrap is not billed.

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
