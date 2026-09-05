# mhl-quote

Local, Windows-friendly CNC **rough-quote** estimator for Machine Hack Labs.

This is **not** the marketing site, not an RFQ inbox, and not a published product.
It runs on your machine: `STEP`/`STL` → axis-aligned bounding box as stock →
part volume → removal → hours at **$75/hr** + material pass-through → **quote range**.

Ticket: **MHL-CF-001**. Shop machine: **Tormach 1500MX** (3-axis mill only).

## What it does

1. Reads a solid (`STEP` preferred, `STL` accepted).
2. Measures AABB (stock) and solid volume (part).
3. `removal = max(0, stock_box − part)`.
4. `cut_hours = removal / MRR_eff`.
5. `labor = (setup_hours + cut_hours) × shop_rate`.
6. `materials = stock purchase` (pass-through at Andrew's cost; **no scrap adder**).
7. `raw = max(materials + labor, min_charge)`.
8. Prints **`raw × 0.85` – `raw × 1.25`**. Never a single-dollar quote.

If the stock box exceeds usable 1500MX travel (envelope minus fixture margin),
the job is **hard-rejected** and no customer range is emitted.

## What it will not do

- Finishes, turning, 5-axis, or full CAM/toolpath simulation
- Xometry-style marketplace pricing
- RFQ email/form wiring (intentionally skipped)
- Cloud calls or secrets
- Personality / marketing automation

`--finish`, `--five-axis` / `--5-axis`, and `--turning` / `--lathe` exist only
so those requests **fail closed**.

## Windows setup

Needs **Python 3.10+** (3.12 is fine). From Command Prompt or PowerShell:

```bat
cd path\to\machinehacklabs-website\mhl-quote
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

STL quoting works after that. For **STEP** (preferred):

```bat
python -m pip install -r requirements-step.txt
```

CadQuery pulls in OCP. If `pip` fails on Windows, use a current 64-bit CPython
from python.org (not Store stubs) and retry. This tool does not need conda.

Optional editable install (gives the `mhl-quote` command):

```bat
python -m pip install -e .
```

## How to run

From the `mhl-quote` folder, with the venv active:

```bat
python -m mhl_quote samples\demo_block.stl --material aluminum
python -m mhl_quote path\to\part.step --units mm --material steel
```

Or `run.bat` (same arguments):

```bat
run.bat samples\demo_block.stl --material aluminum
```

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--units inch\|mm` | CAD units (STL is unitless; many STEP files are mm) |
| `--material aluminum\|steel\|…` | Catalog key or alias |
| `--setup-hours 1.5` | Override default setup |
| `--mrr 10` | Override MRR_eff (in³/hr) |
| `--stock-x/y/z` | Override AABB stock, inches |
| `--stock-cost 42.00` | Actual plate invoice (pass-through) |
| `--json` | Machine-readable result |
| `--list-materials` | Dump the catalog |
| `--show-config` | Dump resolved tunables |
| `--config path` | Alternate YAML/JSON |

Exit codes: `0` quoted, `2` rejected (envelope or unsupported process), `1` usage/error.

## Config path

**Edit this file to calibrate the shop:**

`mhl-quote/config/quote.yaml`

Tunables (locked model, editable numbers):

- `shop.rate_usd_per_hr` (default 75)
- `shop.setup_hours` (default 1.0)
- `shop.min_charge_usd` (default 75)
- `shop.band_low` / `band_high` (default 0.85 / 1.25)
- `machine.envelope_in` `{19.7, 13.8, 14.0}` plus `fixture_margin_in`
- `materials.*.mrr_eff_in3_per_hr` and `cost_usd_per_in3`

JSON configs are also accepted (`--config quote.json`). Do not put secrets,
API keys, or customer PII in the config.

Replace catalog `cost_usd_per_in3` with Andrew's real stock cost, or pass
`--stock-cost` per job so the invoice is passed through exactly.

## How to calibrate MRR

`MRR_eff` is **not** a catalog cutting-data number. It is the shop's effective
cubic inches per *paid chip-making hour* (tool changes, pecks, and conservative
feeds already baked in).

1. Pick a finished 3-axis job you would actually take again.
2. From the CAD: run this tool, note `Removal` (in³). Or measure stock box − part volume.
3. From the traveler: chip-making hours only (exclude quote time, degrease, packing).
4. `actual_mrr = removal_in3 / actual_cut_hours`.
5. Average a few aluminum jobs and a few steel jobs separately.
6. Put a **slightly conservative** (lower) number in `mrr_eff_in3_per_hr`.
7. Re-run those past jobs. The real invoice should land inside the 0.85–1.25 band.
   If you are consistently high, raise MRR. If consistently low, drop it.

Starting bands in the default config (labeled tunable):

- Aluminum: ~8–15 in³/hr (default 12)
- Steel: ~3–8 in³/hr (default 5)

Do not chase single-dollar precision. If a job is thin-wall, heavily fixtured,
or mostly drilling, override `--mrr` / `--setup-hours` on that run instead of
poisoning the catalog.

## Envelope

Tormach 1500MX travels: **X 19.7 in, Y 13.8 in, Z 14.0 in**.
Usable travel subtracts `fixture_margin_in` (default 0.5 in each axis).
Over-travel → reject. A 90° remapping note is informational only; the
as-imported orientation is what is accepted or rejected.

## Tests

```bat
python -m pip install pytest
python -m pytest
```

STEP tests skip automatically when CadQuery is not installed.

## Layout

```
mhl-quote/                 ← this tool (keep it out of the website app)
  config/quote.yaml        ← the one editable shop file
  mhl_quote/               ← Python package
  samples/demo_block.stl   ← 2.0 × 1.5 × 0.75 in solid, inches
  tests/
  requirements.txt         ← STL + cost model
  requirements-step.txt    ← CadQuery/OCP
  run.bat
```

v1 is local-only. Do not deploy or publish this package until Andrew says so.
