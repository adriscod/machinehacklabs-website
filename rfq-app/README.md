# rfq-app

A minimal, local **Request-for-Quote (RFQ)** web app for Machine Hack Labs. It is
a thin web wrapper around the local [`mhl-quote`](../mhl-quote) rough-quote
estimator.

Flow: customer uploads a **STEP/STL** + contact info → the `mhl_quote` estimator
produces a machining rough-quote **range** → the request is stored (queued) on
disk for the shop to follow up on.

This is an internal/local tool. It **does not send email** and stores no secrets.
It reuses the estimator's locked cost model (`$75/hr` + material pass-through,
Tormach 1500MX 3-axis envelope).

## Run it

The app imports the `mhl_quote` package, so use the estimator's virtualenv
(created by [`../.cursor/install.sh`](../.cursor/install.sh)) and add Flask:

```bash
cd mhl-quote
python -m venv .venv && . .venv/bin/activate   # or virtualenv .venv
python -m pip install -r requirements.txt -e .
python -m pip install -r requirements-step.txt   # optional: STEP support

cd ../rfq-app
python -m pip install -r requirements.txt        # Flask
python app.py
```

Then open <http://localhost:5000>.

## Routes

| Route        | Method | Purpose                                             |
| ------------ | ------ | --------------------------------------------------- |
| `/`          | GET    | RFQ form (upload + contact)                         |
| `/quote`     | POST   | Runs the estimator, stores the request, shows range |
| `/requests`  | GET    | Local RFQ queue (newest first)                      |
| `/healthz`   | GET    | Liveness/config check                               |

## Where requests go

Each submission appends a JSON line to `data/requests.jsonl` and the uploaded
solid is saved under `data/uploads/`. Both are git-ignored. There is no database
and no external service; delete the `data/` contents to clear the queue.

## Scope

Machining-only 3-axis rough quotes, exactly like the CLI. No finishes, turning,
or 5-axis. Over-envelope or otherwise un-quotable parts are still logged (marked
`rejected`) so the shop can reach out manually.
