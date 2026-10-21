# Fraud Desk — credit card fraud review demonstrator

A Software Engineering Lab project: a FastAPI + SQLite backend and a React/TypeScript analyst console for reviewing potentially fraudulent card transactions.

> **Not a payment system.** All card identifiers are synthetic tokens. Blocking a token only changes this app's local behavior. There is no bank or payment-network integration, no PCI DSS compliance and no production readiness. Scoring is a **transparent rule baseline, not a trained ML model**; no detection-rate or accuracy figure is claimed anywhere.

## Prerequisites
Python 3.11+ and Node 20+ (Node is only needed to build or develop the frontend). No Docker, Redis or external services. Works offline after dependencies are installed.

## Quick start (single port, production build)
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
(cd frontend && npm install && npm run build)
python -m app.cli create-user --username alice --role admin      # prompts for a password (min 10 chars)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000. On Windows, `run-demo.ps1` does the same steps. API docs: http://127.0.0.1:8000/docs.

**No-login local demo:** set `FRAUD_AUTH_REQUIRED=false` before starting. Everyone is then treated as an administrator named `local-demo`; only use this on a machine you alone control (the server binds to 127.0.0.1 by default).

## Development (two terminals)
```bash
uvicorn app.main:app --reload --port 8000        # API
cd frontend && npm run dev                       # UI on http://localhost:5173, /api is proxied to :8000
```
Change the proxy target with `VITE_PROXY_TARGET` in `frontend/.env.local`; set `VITE_API_BASE` only if the UI is hosted apart from the API (then add its origin to `FRAUD_CORS_ORIGINS`).

## Configuration (environment variables)
| Variable | Default | Meaning |
|---|---|---|
| `FRAUD_DB` | `./fraud_demo.sqlite` | SQLite file |
| `FRAUD_AUTH_REQUIRED` | `true` | Require sign-in; `false` = local no-login mode |
| `FRAUD_SECRET_KEY` | generated, stored in the DB | Token-signing key (set it to share sessions across processes) |
| `FRAUD_CORS_ORIGINS` | Vite dev origins | Comma-separated allowed origins |
| `FRAUD_SEED_DEMO` | `true` | Create ~70 synthetic demo transactions on first start (labelled `SEED`) |

Delete the SQLite file to reset. Existing databases from the first version are migrated in place on startup.

## Roles
| | Analyst | Administrator |
|---|---|---|
| View everything, submit transactions, record verdicts | ✔ | ✔ |
| Block / unblock tokens manually, change thresholds | ✘ (403) | ✔ |
A confirmed-fraud verdict blocks the token automatically, whoever records it. Roles are enforced by the backend on every request. There are no default accounts.

## Using the app
1. **Overview** shows volume, decisions, backlog and review outcomes; the banner states how many rows are seeded vs live.
2. **Alerts and cases** lists held/declined transactions, highest risk first. *Investigate* opens the transaction.
3. The **transaction page** shows the score broken into factors, other activity on the token and the audit trail. Choose a verdict, confirm, and the result (including any card block) is shown. A verdict is final.
4. **Transactions** has search, filters, sorting and pagination (state is kept in the URL). *Submit synthetic transaction* creates live data.
5. **Cards**, **Fraud rules**, **Reports** (date/source filters, CSV export) and **Audit log** cover the rest.

Try it: submit amount 2400, ONLINE, token `SYNTH-DEMO-0001` → HOLD (0.49). Confirm fraud → token blocked → submitting the same token again returns 409.

## Scoring
Score = baseline 0.04 + high amount 0.35 + blocked country 0.75 + online channel 0.10 + velocity 0.25 (≥ limit earlier transactions on the token in 24 h), capped at 1.0 (shown as a negative `score_cap` factor so factors always sum to the score). `score <= approve_max` → APPROVE, `<= hold_max` → HOLD, otherwise DECLINE. Scoring sits behind the `Scorer` interface (`app/services/scoring.py`).

**Training a model later:** this repository has no labelled dataset and none was downloaded, so no model exists. To add one: obtain a dataset with licence/provenance you can cite, split by time (not randomly) to avoid leakage, handle class imbalance (class weights or resampling on the training split only), report precision, recall, F1 and PR-AUC on a held-out split, persist the artifact, implement `Scorer` with a fallback to `HeuristicScorer` when the artifact is missing, and add load/predict tests.

## Architecture
```
app/main.py            app factory, security headers, static SPA serving
app/api/               routes + auth dependencies (thin)
app/schemas/           request validation (Pydantic)
app/services/          scoring, ingest/review workflow, cards, config, reports, auth, seed
app/repositories/      all SQL
app/db/                connections/transactions, migrations (schema_version), init
app/core/              settings, error shape, password hashing and tokens
frontend/src/          React pages, typed API client, UI components
```
Every write runs in one `BEGIN IMMEDIATE` transaction together with its audit row. Errors always have the shape `{"error": {"code", "message", "details?"}}`.

### API summary
`GET /api/health` (public) · `POST /api/auth/login`, `GET /api/auth/me` · `POST/GET /api/transactions`, `GET /api/transactions/{id}` · `GET /api/alerts`, `POST /api/alerts/{id}/review` · `GET /api/cards`, `POST /api/cards/{token}/block|unblock` (admin) · `GET /api/config`, `PUT /api/config` (admin), `GET /api/rules` · `GET /api/reports`, `GET /api/reports/export.csv` · `GET /api/audit`. Full schema at `/docs`.
Notable statuses: 401 not signed in, 403 wrong role, 404 missing, 409 blocked card / already reviewed / no alert, 422 validation, 429 sign-in lockout, 503 database failure.

## Tests
```bash
pip install -r requirements-dev.txt && python -m pytest          # backend
cd frontend && npm test && npm run build                         # frontend tests, strict tsc, production build
```
Tests use temporary databases and never touch your demo DB.

## Security notes and limitations
- Full card numbers are rejected (PAN-like digit runs in token or merchant fields); no CVV field exists.
- Passwords: Argon2. Sessions: signed 8-hour tokens kept in `sessionStorage` (readable by any script on the page; the UI renders all data as text and ships a restrictive CSP). Sign-in lockout is per username and in memory, so it resets on restart.
- No TLS, password reset, MFA or user-management UI; accounts are created through the CLI. Put a TLS reverse proxy in front before exposing this beyond localhost, and do not do so with real data.
- SQLite is the only supported database. PostgreSQL is not configured; the SQL is isolated in `app/repositories` to make that port feasible.
- Seeded demo statistics describe synthetic data only.

## Troubleshooting
- *Page says the frontend is not built*: run `npm install && npm run build` in `frontend/`.
- *Sign-in screen but no account*: run `python -m app.cli create-user ...` or start with `FRAUD_AUTH_REQUIRED=false`.
- *"database is locked" / 503*: another process holds the SQLite file; stop it or use another `FRAUD_DB`.
- *Dev UI shows "Cannot reach the server"*: start uvicorn on port 8000 or set `VITE_PROXY_TARGET`.

Assignment mapping for the 13 lab experiments: `docs/lab-alignment.md`. Work log and current status: `STATUS.md`.
