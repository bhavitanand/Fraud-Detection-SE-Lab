# API reference

Interactive docs with request/response schemas: **http://127.0.0.1:8000/docs** (Swagger) and `/openapi.json`.

All routes are under `/api`. Send `Authorization: Bearer <token>` (token from `/api/auth/login`). "user" = analyst or admin; "admin" = administrator only. With `FRAUD_AUTH_REQUIRED=false` every caller acts as admin `local-demo`.

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/health` | none | Liveness, schema version, whether ML is loaded |
| GET | `/api/meta` | user | Currencies, channels, enums for the UI |
| POST | `/api/auth/login` | none | E-mail + password; returns a token, or an OTP challenge when OTP is on |
| POST | `/api/auth/otp` | none | Verify the 6-digit code, returns a token |
| GET | `/api/auth/me` | user | Current user and role |
| PUT | `/api/auth/password` | user | Change own password |
| GET | `/api/users` | admin | List users |
| POST | `/api/users` | admin | Create a user (201) |
| PATCH | `/api/users/{email}` | admin | Change role / active flag (last admin protected) |
| PUT | `/api/users/{email}/password` | admin | Reset a password |
| POST | `/api/transactions` | user | Score and store a transaction → decision, score, factors |
| GET | `/api/transactions` | user | Search, filter, sort, paginate |
| GET | `/api/transactions/{id}` | user | Detail: factors, cardholder, merchant, history, audit |
| GET | `/api/alerts` | user | Queue; filters: status, decision, assigned |
| POST | `/api/alerts/{id}/review` | user | Verdict CONFIRMED_FRAUD (blocks card) or FALSE_POSITIVE |
| POST | `/api/alerts/{id}/assign` | user | Assign to self / unassign |
| GET | `/api/notifications` | user | Simulated cardholder messages |
| GET | `/api/public/confirm/{token}` | none | Cardholder page data (one-time token) |
| POST | `/api/public/confirm/{token}` | none | Cardholder answers 'Was this you?' |
| GET | `/api/cards` | user | Cards with holder, issuer, status |
| POST | `/api/cards/{token}/block` | admin | Block a card token |
| POST | `/api/cards/{token}/unblock` | admin | Unblock a card token |
| GET | `/api/config` | user | Thresholds, ₹ limit, blocked countries, velocity limit |
| PUT | `/api/config` | admin | Update configuration (approve_max < hold_max) |
| GET | `/api/rules` | user | Factor catalogue |
| GET | `/api/models` | user | Model registry with held-out metrics |
| POST | `/api/models/{id}/deploy` | admin | Make a candidate the active model |
| POST | `/api/models/{id}/retire` | admin | Retire a model |
| POST | `/api/models/benchmark/replay?count=N` | admin | Replay N (1–25) held-out benchmark rows |
| GET | `/api/reports` | user | Counts, rates, analyst productivity, daily trend (date and source filters) |
| GET | `/api/reports/export.csv` | user | Transactions as CSV |
| GET | `/api/labels/export.csv` | user | Analyst verdicts as CSV |
| GET | `/api/audit` | user | Audit events (filters: action, actor, q) |
| GET | `/api/audit/verify` | admin | Recompute the hash chain |

## Example
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"your-password"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X POST localhost:8000/api/transactions -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"card_token":"SYNTH-IN-1001","amount":120000,"currency":"INR","merchant":"Tanishq","country":"IN","location":"Mumbai","channel":"ONLINE"}'
```
The response contains `decision` (APPROVE / HOLD / DECLINE), `score` (0–1) and the `factors` that explain it.

## Errors
| Code | Meaning |
|---|---|
| 401 | Missing, invalid or expired token |
| 403 | Role not allowed |
| 409 | Card is blocked, or the alert was already reviewed |
| 422 | Validation failed (negative amount, PAN-like value, thresholds out of order, ...) |
| 429 | Too many failed sign-ins for this account (temporary lockout) |
