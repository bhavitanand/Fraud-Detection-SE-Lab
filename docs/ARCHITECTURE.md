# Architecture

## Overview
```
 Browser (React + TypeScript, built by Vite, served as static files)
        │  JSON over HTTP  (/api/...)
        ▼
 FastAPI app (app/main.py, app factory)
   api/routes.py        thin HTTP layer, role checks via Depends(...)
   services/*           business logic: scoring, transactions, cards, auth, reports, ML, notifications, autopilot, live engine, copilot
   repositories/        all SQL (db_access.py)
   schemas/models.py    Pydantic request/response validation
   core/                settings, security (Argon2, JWT), errors, audit hash chain
   db/                  connection, versioned migrations (v1 → v4)
        │
        ▼
 SQLite file (WAL mode)            ml/artifacts/ (verified model files)
```
One process serves both the API and the built UI on port 8000.

## Layers and rules
- **Routes** only parse input, check the role, call a service and shape the response.
- **Services** hold the rules. Scoring is behind a `Scorer` interface: `HeuristicScorer` (rules) and `HybridScorer` (rules + ML).
- **Repositories** are the only place SQL is written. Every write runs in `BEGIN IMMEDIATE` together with its audit row, so a change and its audit entry commit or fail together.
- **Settings** come from environment variables (`app/core/config.py`); no secrets in code.

## Request flow: scoring a transaction
1. `POST /api/transactions` is validated (amount, currency, channel, card token; PAN-like values rejected).
2. Blocked token → HTTP 409.
3. Rules run (amount, country, channel, velocity, unusual amount, new country, new merchant, impossible travel) and produce factors that sum to the score (capped at 1.0).
4. If the active model exists and the request carries the 28 benchmark features: `score = 1 − (1 − rules)(1 − ml)`.
5. Thresholds turn the score into APPROVE (≤ 0.25), HOLD (≤ 0.65) or DECLINE.
6. The transaction, its factors, any alert and a cardholder message are saved with an audit row.

## Data model (schema v3)
Tables: `customers`, `merchants`, `cards`, `transactions` (source SEED/LIVE/BENCH, currency, city, score, decision, factors), `fraud_alerts` (status, assignee, verdict), `notifications` (simulated outbox with a one-time reply token), `users`, `otp_challenges`, `ml_models` (candidate/active/retired, SHA-256), `config`, `audit` (hash chain), `schema_version`. Views: `v_transactions`, `analysts`.

## Security design
| Concern | Mechanism |
|---|---|
| Passwords | Argon2 via pwdlib; per-account in-memory lockout |
| Sessions | Signed JWT (HS256), 8-hour expiry, kept in `sessionStorage` |
| Authorisation | `current_user` and `require_admin` dependencies on every route except `/health` and `/public/confirm` |
| OTP (optional) | 6 digits, HMAC-hashed, 5 minutes, 5 attempts, single use |
| Audit | Each row stores a hash of the previous row; `GET /api/audit/verify` recomputes the chain |
| ML artifacts | Loaded only from `ml/artifacts` after SHA-256 matches the registry |
| Browser | CSP header, `frame-ancestors 'none'` |

## Machine-learning pipeline (`ml/train.py`)
ULB dataset → drop duplicates → chronological 60/20/20 split → HistGradientBoosting vs RandomForest compared on validation PR-AUC → isotonic calibration → one evaluation on the test split → artifacts + metrics JSON → registered as *candidate* → an admin deploys it.

## Frontend (`frontend/src`)
React Router pages (`pages/`), a typed API client (`api/`), auth context (`auth.tsx`), hand-built SVG charts, an error boundary and a public `/confirm/:token` page. Strict TypeScript; Vitest + Testing Library tests.

## Not included (by design)
Real payment authorisation, bank or card-network integration, SMS, PostgreSQL/Redis, TLS termination, PCI DSS compliance. See `docs/lab-alignment.md` for how the lab's target architecture differs from this build.

## v3 additions
- **Live engine** (`services/live_service.py`): one daemon thread with its own SQLite connection. A simulated clock and an event heap generate genuine and fraudulent events from `ml/simulator.py`; each goes through `transactions_service.ingest` exactly like an API call. Replies and card re-issues are scheduled as future events. Ground truth is stored in `transactions.sim_label` and used only for KPIs. The clock starts in the past and stops when it reaches real time.
- **Autopilot** (`services/autopilot_service.py`): hooks after scoring (auto-block) and after a cardholder reply (close the alert, release its own blocks). Every action is audited with actor `autopilot`. Config keys `autopilot_enabled`, `auto_block_score`.
- **Live scorer** (`ml/features.py`, `ml/train_india.py`, `LiveModel` in `ml/wrapper.py`): model registry rows have a `kind` (`benchmark` or `live`), one active model per kind. Per-transaction reasons come from occlusion of feature groups.
- **Copilot** (`services/copilot_service.py`): Gemini over REST with timeouts and an offline fallback. Search never executes generated SQL: a validated filter is turned into a whitelisted, parameterised query.
- **Deployment**: multi-stage Dockerfile (Node build, Python runtime, non-root, health check), compose with a data volume, Render blueprint, CI workflow.
