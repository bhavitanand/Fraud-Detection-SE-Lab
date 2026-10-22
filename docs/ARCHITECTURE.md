# Architecture

## Overview
```
 Browser (React + TypeScript, built by Vite, served as static files)
        │  JSON over HTTP  (/api/...)
        ▼
 FastAPI app (app/main.py, app factory)
   api/routes.py        thin HTTP layer, role checks via Depends(...)
   services/*           business logic: scoring, transactions, cards, auth, reports, ML, notifications
   repositories/        all SQL (db_access.py)
   schemas/models.py    Pydantic request/response validation
   core/                settings, security (Argon2, JWT), errors, audit hash chain
   db/                  connection, versioned migrations (v1 → v3)
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
