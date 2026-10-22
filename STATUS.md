# Status â€” final quality audit (2026-10-20)

## Verified in this audit

- Read both PDF text extractions. The practical-file text lists Experiments 1â€“13; the syllabus additionally states that at least 10 experiments are to be performed, including at least 5 from its listed practicals. Reviewed the existing experiment documentation against both sources and the local application. The PDF binaries were not visually rendered: no PDF inspection utility is installed in the workspace, so source figures were not independently checked.
- Ran `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: **5 tests passed**. Tests cover dashboard/health, request validation, configured threshold ordering, heuristic score range and persistence, alert reviews, fraud-triggered block and blocked-token rejection, false-positive persistence, admin token block/unblock, and audit events.
- Tests call the FastAPI ASGI app in process and use a fresh OS temporary-directory SQLite database per test. They remove those databases after each test and need no running server or hand-managed database.
- Fixed `conn()` in `app/main.py` to commit/rollback and close each SQLite connection. Before the fix, files remained locked on Windows and temporary test database cleanup failed.
- Updated README test instructions and experiment documentation, including the explicit difference between target architecture and delivered prototype.
- Reviewed Mermaid source syntax and application consistency manually. No Mermaid CLI/parser is installed in this workspace, so rendered/parser-based diagram validation was not performed.

## Final acceptance check (2026-10-20)

- Ran `\.venv\Scripts\python.exe -m unittest discover -s tests -v`: exit code **0**; 5 tests passed in 0.185 seconds.
- Started Uvicorn with the README launch command at `127.0.0.1:8000`, using an isolated `FRAUD_DB` only for this check. `GET /` returned HTTP 200 and `GET /api/health` returned `status: ok`, `database: sqlite`, and the demo-heuristic notice. The server was then stopped deliberately with Ctrl+C.
- Confirmed the README launch/test commands and listed API endpoints match the implemented FastAPI routes. Confirmed `docs/lab-alignment.md` has individually identifiable sections 1 through 13 and documents prototype limitations.

## Practical-file / syllabus gaps (not implemented)

- No trained supervised model, real labeled dataset, model evaluation, or precision/recall/F1/PR-AUC evidence. The score is a transparent heuristic baseline.
- Behavioral scoring uses same-day token transaction count, amount, blocked-country, and online-channel rules; it does not implement the reference's recent time windows, customer/merchant profiles, geolocation distance, or model feature store.
- No actual payment authorization, clearing, settlement, gateway integration, analyst assignment, cardholder notification/step-up verification, or continuous model retraining.
- No authentication, role enforcement, TLS, hardened deployment, PCI DSS compliance, production PostgreSQL/Redis/React stack, availability or latency measurements. The dashboard is static HTML/JS served by FastAPI and uses SQLite.
- Reports are descriptive counts over synthetic/demo rows; detection and false-positive rates against labels are not calculated. Alerts are non-APPROVE transaction rows rather than a separately modeled case entity. False-positive review records a verdict but does not revise the original decision.
- The five integration tests are useful smoke coverage, not exhaustive unit, security, load, frontend-browser, or system testing. Some scoring rules and API error paths lack direct tests.

## Windows setup verification limit

README PowerShell commands were reviewed for project-relative paths and current files. The already configured `.venv` successfully ran the test suite. A complete clean environment recreation and dependency installation was not executed in this audit, so the `py -3 -m venv` and package-install steps are documented but not newly verified here; they require a working Python launcher and package availability. No packages were installed during this audit.


---

# Overhaul audit and plan (2026-10-20)

Appended, not replaced: the earlier audit above is preserved.

## Audit findings (from reading the code, not from running it)

- Repo is not a Git working tree in the supplied zip, so there was no status to preserve. Nothing was committed or deleted.
- `app/main.py` (131 lines) holds routes, SQL, scoring, config, audit and the embedded dashboard HTML.
- Correctness gaps:
  - `/api/alerts/{id}/review` can be applied repeatedly and overwrites an earlier verdict; there is no state-transition rule.
  - Review of an APPROVE transaction (no alert) is accepted.
  - Ingest checks the block flag and inserts in separate transactions (race window); each `audit()` opens its own connection, so the action and its audit row are not atomic.
  - Config is stored as strings with no server-side check on `blocked_countries` format; thresholds are only partly cross-validated.
  - Daily velocity uses a string timestamp comparison and counts only same UTC day.
  - `init()` runs at import time, so tests must set `FRAUD_DB` before import.
  - Transactions list is capped at 200 with no search, filter, sort or pagination.
  - Reports give counts only; no rates against labels, no trends.
  - Seed rows are not flagged as demo data, so seeded and live rows cannot be told apart.
- Security gaps: no authentication or roles, unrestricted CORS posture undefined, dashboard renders `reasons` unescaped in the alert table (`${r.reasons}`, `${r.token}` etc.), audit detail stored as raw JSON.
- Testing: 5 smoke tests using a hand-written ASGI client; no scoring boundary, config, report or auth tests; no frontend tests.

## Plan

1. Backend: split into `app/core`, `app/db`, `app/schemas`, `app/repositories`, `app/services`, `app/api`; schema versioning table; one transaction per request including its audit row; review state machine (OPEN -> CONFIRMED_FRAUD | FALSE_POSITIVE, repeat returns 409); paginated/filterable transaction API; scorer behind an interface; `source` column (SEED vs LIVE); richer reports; optional bearer-token auth with Analyst/Admin roles (hashed passwords, no default credentials).
2. Frontend: `frontend/` with React, strict TypeScript, Vite, light theme, pages from the brief; typed API client; dev proxy to FastAPI; production build served by FastAPI.
3. Tests: pytest with isolated temp databases; keep the five existing tests passing; Vitest for key frontend flows; run `tsc` and `vite build`.
4. Docs: README, `docs/lab-alignment.md` (keep the 13 experiment sections), this file.

## Implementation result (2026-10-21)

Dependency installation was approved by the project owner and was confined to `.venv/` and `frontend/node_modules/`. No Git operations were performed (the supplied zip had no `.git`), nothing was committed, and the original `app/main.py` and `tests/test_smoke.py` are the only files that were replaced (copies kept outside the repo during the work).

### What changed
- **Backend** split into `app/{core,db,schemas,repositories,services,api}`; `app/main.py` is now an app factory. Added: schema migrations (v1 baseline, v2 additions; legacy DBs migrate in place), one `BEGIN IMMEDIATE` transaction per write including its audit row, review state machine (`OPEN -> CONFIRMED_FRAUD | FALSE_POSITIVE`, `NOT_REQUIRED` for approvals; repeats return 409), per-factor score explanations stored with each transaction, `Scorer` interface, `source` (SEED/LIVE) labelling, paginated/filterable/sortable transaction search, transaction detail with token history and audit trail, `/api/rules`, richer reports with date/source filters and a formula-safe CSV export, JWT sign-in with Argon2 hashes and analyst/admin roles enforced by the backend, security headers, restricted CORS, uniform error shape, structured logging without payloads.
- **Frontend** `frontend/`: React + strict TypeScript + Vite, light theme, no UI or chart dependencies (SVG charts), pages: Overview, Transactions (+ submit form), Transaction investigation, Alerts and cases, Cards, Fraud rules, Reports, Audit log, Login. All data comes from the API; every button maps to an implemented endpoint.
- **Docs**: README rewritten; `docs/lab-alignment.md` keeps all 13 experiment sections, with the ER, state, component, deployment, testing and FP sections updated.

### Contract changes (and the tests they touched)
`GET /api/transactions` and `GET /api/audit` now return `{items, total, ...}` instead of a bare list; `reasons` is a JSON list; velocity is a rolling 24 h. The five original scenarios in `tests/test_smoke.py` were ported to pytest fixtures (the old test reached into `main.DB_PATH`, which no longer exists) with identical assertions apart from reading `["items"]`.

### Verified results (commands actually run)
| Check | Result |
|---|---|
| `python -m pytest` | **72 passed** |
| `cd frontend && npx vitest run` | **17 passed** (3 files) |
| `npx tsc --noEmit` (strict) | no errors |
| `npm run build` | succeeded (~307 kB JS, ~94 kB gzip) |
| Live server run (uvicorn, auth on, built SPA) | 401 without token; analyst 403 on block; review -> card blocked; repeat review 409; blocked-card ingest 409; admin unblock; `/` serves the SPA; server log contained no passwords or tokens |

### Not verified / remaining limitations
- **The UI was not opened in a real browser**, so visual polish, contrast, layout at different widths and keyboard flow were not checked by eye. Only type checks, jsdom component tests and a served-build smoke test were run.
- No trained model, dataset or ML metrics exist; scoring is a rule baseline and the README lists the steps required to add a model.
- Session token lives in `sessionStorage`; lockout is in-memory; no TLS, MFA, password reset or user-management UI (CLI only).
- PostgreSQL is not configured. Concurrency is covered by SQLite write locking plus a threaded double-review test; no load testing was done.
- Legacy rows are marked SEED only for the three rows the old app seeded; any other pre-existing rows are treated as LIVE.
- Accessibility work (labels, focus rings, reduced motion, dialog focus/Esc) was implemented but not audited with a screen reader.


---

# Second iteration: India-specific data model, ML, sign-in, lab file (2026-10-22)

## What changed
- **Schema v3** (in-place migration of v1/v2 databases): customers, merchants, cards (card_id PK), fraud_alerts (alerts are now rows; review state moved off transactions; view `v_transactions`), ml_models, notifications, otp_challenges, audit hash chain, `analysts` view. Matches the seven entities of the lab file's ER diagram.
- **India**: INR default with en-IN formatting, ₹50,000 high-amount limit, Indian cities with coordinates, MCC merchants, 14 synthetic cardholders; seeded through the real scoring/alert/notification code.
- **New scoring factors**: unusual amount, new country, new merchant, impossible travel (haversine speed), plus currency conversion with fixed demo rates.
- **ML**: `ml/train.py` (ULB dataset, chronological split, calibrated), registry + deploy/retire + benchmark replay, verified artifact loading, hybrid noisy-OR scorer with safe fallback.
- **Sign-in**: e-mail + password; optional e-mail one-time code (console or SMTP); users page; change password; last-admin protection.
- **Workflow**: alert assignment, simulated cardholder messages with a public one-time reply link (“not me” blocks the card), analyst productivity, label export, audit integrity check.
- **Docs/lab file**: `docs/lab-file/` builds the updated practical file (original Experiments 1–10 untouched plus as-built notes, new Experiments 11–13 and an appendix).
- Google sign-in was dropped at the owner's request.

## Measured results (scripts/collect_results.py, 2026-10-22T19:28:32+00:00)
| Check | Result |
|---|---|
| Back-end `pytest` | **181 passed**, 0 failed, 96.6% statement coverage |
| Front-end `vitest` | **26 passed** |
| `tsc --noEmit` (strict) | passed |
| Scoring latency (in-process, 300 requests) | p50 5.8 ms, p95 7.7 ms, p99 9.4 ms (no network) |
| Live server run (OTP sign-in, SPA, model replay, audit verify) | passed; no secrets in logs |
| ML held-out test (74 frauds in 56,746 rows) | PR-AUC 0.78; at the app threshold 57 caught, 17 missed, 10 false alarms (precision 85%, recall 77%) |

## Not verified / limits
- The UI was **never opened in a real browser** (none available here): no visual, contrast or keyboard check.
- E-mail sending through a real SMTP server was tested only with a mock; SMS/phone OTP is not implemented.
- ML metrics rest on 74 test frauds, a 2013 European dataset in EUR; Indian live transactions are rule-scored. The benchmark replay sample is enriched with fraud (20%) and over-states precision.
- No load, penetration or accessibility testing; hash chain is tamper-evident only; no TLS.
- The Gantt/PERT schedule and FP complexity ratings in the lab file are planning assumptions to be replaced with the team's real dates and judgement.
