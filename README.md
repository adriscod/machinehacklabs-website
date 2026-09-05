# Machine Hack Labs website

GitHub Pages site for [machinehacklabs.com](https://machinehacklabs.com).

The product on this repo is the **quote request form**. It emails
**quotes@machinehacklabs.com** with the RFQ package (fields + STEP/STL +
internal rough range). Andrew reviews before any customer reply.

## Pages

| URL | What |
| --- | --- |
| `/` | Shop intro + hero photo + link to the form |
| `/capabilities/` | 1500MX envelope, in/out of scope, shop photos |
| `/work/` | Shop photos (machining only) |
| `/quote/` | RFQ form + in-browser estimator |
| `/thanks/` | Confirmation (no pricing) |
| `/contact/` | quotes@ + link to `/quote/` (no second form) |
| `/privacy/` | Short privacy skeleton |

## How quotes@ is sent

On the live site the form POSTs to
`https://formsubmit.co/quotes@machinehacklabs.com`
(multipart: structured fields + file). No API key and no secrets in the repo.

- First live submit sends Andrew a **one-time confirmation** from FormSubmit.
  Until he clicks that, mail will not land in quotes@.
- FormSubmit's visitor autoresponse is configured to say the RFQ was received
  and that **this is not a quote** (no dollar amounts).
- The estimate range is shown on `/quote/` and included in the message to quotes@.

To use a different endpoint later (Formspree, a worker, etc.), edit
`assets/config/rfq.json` → `productionFormAction`. Do not commit secrets.
There are no required env vars for the default path.

## Test locally (does not publish, does not email)

```bat
cd path\to\machinehacklabs-website
python mhl-quote\dev_rfq_server.py
```

Open http://127.0.0.1:8765/quote/

On localhost the form POSTs to `/__local_rfq`. Packages land in
`mhl-quote/.local-inbox/` (gitignored). Nothing is sent to quotes@.

## After quotes@ (shop job tracker)

When an RFQ lands in **quotes@machinehacklabs.com**, Andrew records the shop
job in a local JSON ledger (`mhl-quote/.local-jobs/`, gitignored). This is
not a customer page and is not published.

```bat
python mhl-quote\dev_rfq_server.py
```

Then open http://127.0.0.1:8765/__shop/ — or use the CLI:

```bat
python mhl-quote\shop_jobs.py new --id MHL-1001 --estimate-low 110 --estimate-high 162
python mhl-quote\shop_jobs.py set MHL-1001 --bid 145 --deposit 60 --chase-url https://secure.chase.com/your-request --status bid_sent
python mhl-quote\shop_jobs.py advance MHL-1001
```

- Estimator band ≠ Andrew’s bid.
- Deposit is a materials + tooling floor, not a fixed percent.
- Paste a Chase payment URL Andrew created. No Chase API. No card capture here.
- Paying that link is acceptance of the stated scope and price.
- Deposit, then balance, then ship. Scrap is not billed.
- Customer bid email is `mhl-quote/templates/bid-email.txt` — paste the same Chase URL there.

## Shop tunables

Edit `mhl-quote/config/quote.yaml`, then:

```bat
python mhl-quote\scripts\export_site_config.py
```

That writes `assets/config/quote-config.json` for the website.

RFQ v2 catalog grades, rush multipliers, tolerance, and feature-risk
weights live in that YAML. **Every `$/in³` and `MRR_eff` is a
`TODO_REPLACE` placeholder** — not a market rate. Andrew replaces those
numbers (and can tune rush starting points) then re-exports. See
`mhl-quote/README.md`. The `/quote/` form markup is a teammate's lane;
estimator APIs are additive (`assets/js/estimator.js`).

## CLI helper

`mhl-quote/` remains a **calibration / STEP-volume** helper (`python -m mhl_quote`).
It is not the customer product. See `mhl-quote/README.md`.

## Bid / accept email (shop)

After quotes@ receives an RFQ, Andrew sends (or resends) a bid from
`mhl-quote/templates/bid-email.txt`:

1. Fill scope, total bid, and the materials+tooling deposit (a floor, not a
   fixed percent).
2. Create a Chase payment link or invoice URL in whatever accept tool he
   uses, then paste that URL into `{CHASE_PAYMENT_LINK}`. Product name TBD —
   treat it as a pasteable URL. **No Chase API. No card capture on this site.**
3. Send from quotes@. Paying the link accepts the stated scope and price.
   Deposit now; remaining balance before ship. No installments. Scrap is not
   billed.

The `/quote/` estimator band is a customer-visible estimate and is not a final bid.

## Publish policy

Do not merge or deploy this RFQ path until Andrew says so.
