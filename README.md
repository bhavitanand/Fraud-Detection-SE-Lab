# Credit Card Fraud Detection System â€” Local demo

A locally hosted academic demonstrator for synthetic transaction scoring, review, card controls, configuration and audit. Scores come from a transparent rule-based heuristic, not a trained or evaluated model. The app does not authorize payments, send notifications, or handle real payment card data; use generated `SYNTH-*` tokens only. It is not PCI DSS compliant.

## Windows PowerShell setup

Run from the project folder. The `TEMP`/`TMP` override keeps `ensurepip` temporary files within the project; in this environment Windows denied writes in the sandbox-managed system temp directory.

```powershell
Set-Location 'C:\path\to\Fraud-Detection-SE-Lab-Starter'
New-Item -ItemType Directory -Force .local-temp | Out-Null
$env:TEMP = (Resolve-Path .local-temp).Path
$env:TMP = $env:TEMP
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for the API. SQLite creates `fraud_demo.sqlite` in the workspace and seeds three synthetic examples on first launch. Set `FRAUD_DB` before starting to choose a different local database file. If `.venv` was already created, omit the `py -3 -m venv .venv` command.

## Tests

The integration tests invoke the FastAPI application directly. Every test creates and removes its own temporary SQLite database; no running server, port, or persistent test data is needed:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The five integration smoke tests cover dashboard and health responses, validation and threshold ordering, score output, persistence, fraud and false-positive verdict handling, automatic token blocking, manual block/unblock, and audit entries. They do not evaluate model quality, security, load, or every dashboard interaction.



## Features and limitations

- Validated transaction JSON endpoint (`POST /api/transactions`); amount, token, channel, country and merchant are checked.
- Explainable heuristic risk score (0â€“1) from amount, configurable blocked-country rule, online channel and daily token velocity. Configurable approve/hold cutoffs.
- Persistent transaction history, alerts and audit events; review verdicts and block/unblock endpoints.
- Dashboard for scoring, queue, recent transactions, counts, thresholds and audit.
- Admin configuration API (`GET/PUT /api/config`); no login or role enforcement in this local demo.

Use only fake identifiers. Tokens are not PANs. No full PAN/CVV fields exist. REST endpoints are not protected with authentication; bind to localhost only. No real SMS/email, production model, authorization, settlement or learning pipeline is implemented. The reference's PostgreSQL, Redis, React, supervised model, gateway integration and notifications remain production directions; SQLite and a single-page HTML dashboard keep local setup light.

## API quick start

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
$body = @{card_token='SYNTH-4481'; amount=240; merchant='Demo Market'; country='US'; channel='ONLINE'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/transactions -ContentType 'application/json' -Body $body
Invoke-RestMethod http://127.0.0.1:8000/api/alerts
```

Review using `POST /api/alerts/{id}/review` with `{"verdict":"CONFIRMED_FRAUD"}` or `{"verdict":"FALSE_POSITIVE"}`. Confirmed fraud blocks the associated token. Admin card endpoints are `POST /api/cards/{token}/block` and `/unblock`.

## Scoring note

The score is a transparent demo heuristic; no trained model or model evaluation exists. Seed transactions and test transactions are synthetic examples, not evaluation results or evidence of accuracy.
