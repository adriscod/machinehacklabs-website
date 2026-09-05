# Machine Hack Labs website

GitHub Pages site for [machinehacklabs.com](https://machinehacklabs.com).

The product on this repo is the **quote request form**. It emails
**quotes@machinehacklabs.com** with the RFQ package (fields + STEP/STL +
internal rough range). Andrew reviews before any customer reply.

## Pages

| URL | What |
| --- | --- |
| `/` | Shop intro + link to the form |
| `/quote/` | RFQ form + in-browser estimator |
| `/thanks/` | Confirmation (no pricing) |

## How quotes@ is sent

On the live site the form POSTs to
`https://formsubmit.co/quotes@machinehacklabs.com`
(multipart: structured fields + file). No API key and no secrets in the repo.

- First live submit sends Andrew a **one-time confirmation** from FormSubmit.
  Until he clicks that, mail will not land in quotes@.
- FormSubmit's visitor autoresponse is configured to say the RFQ was received
  and that **this is not a quote** (no dollar amounts).
- The internal range is only in the message to quotes@.

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

## Shop tunables

Edit `mhl-quote/config/quote.yaml`, then:

```bat
python mhl-quote\scripts\export_site_config.py
```

That writes `assets/config/quote-config.json` for the website.

## CLI helper

`mhl-quote/` remains a **calibration / STEP-volume** helper (`python -m mhl_quote`).
It is not the customer product. See `mhl-quote/README.md`.

## Publish policy

Do not merge or deploy this RFQ path until Andrew says so.
