# Status — v2.1 (2026-10-23)

Current state of the project. Older audit notes were folded into this file; the first version (heuristic-only, no auth, 5 tests) no longer exists.

## What works (verified this session)
| Area | State | Evidence |
|---|---|---|
| Back end (FastAPI + SQLite, layered) | Working | 181 pytest tests passed, 97% line coverage |
| Front end (React + strict TypeScript) | Working | 26 Vitest tests passed; `npm run build` clean; all 13 pages opened in headless Chromium at 1440×900 |
| Auth | Working | E-mail + password (Argon2), roles analyst/admin enforced server-side, optional e-mail OTP |
| Scoring | Working | Rule engine `heuristic-v2` with explained factors; hybrid with ML for benchmark rows |
| ML model | Working | Random forest on the public ULB dataset; held-out PR-AUC 0.782, precision 85.1%, recall 77.0% at the app's 0.25 flag threshold (74 frauds in the test split, so wide uncertainty) |
| Cardholder reply flow | Working (simulated) | Outbox with one-time `/confirm/…` link; no real SMS or e-mail |
| Audit | Working | Hash chain with admin "Verify integrity" |
| Latency | Measured | p50 5.8 ms, p95 7.7 ms (in-process, excludes network) |
| Lab file | Complete | `docs/lab-file/…updated.docx`: Experiments 1–13 plus appendix |
| Docs | Complete | README, `docs/SETUP.md`, `ARCHITECTURE.md`, `API.md`, `DEMO.md`, `lab-alignment.md`, `CHANGELOG.md` |

Demo data: 129 synthetic transactions, 14 Indian cardholders and cards, 19 merchants, 18 alerts.

## Fixed in v2.1
- Transaction page overflowed the viewport (grid columns sized by table content); fixed with `minmax(0, 1fr)`.
- Trend chart labels were oversized on wide pages; chart width capped.
- README seed counts corrected; leftover starter files (`AGENTS.md`, `README-FIRST.txt`, `TASK_PROMPT.txt`, `opencode.json`) removed.
- Added UI screenshots (`docs/screenshots/`), a setup guide and a demo script.

## Known limits (honest list)
- The ML model was trained on 2013 European data (EUR, anonymised features). It cannot score live Indian transactions; those use rules. No Indian labelled dataset exists in this repo.
- No real payment authorisation, bank/network integration, SMS, real e-mail by default, TLS, PCI DSS compliance, or PostgreSQL/Redis. SQLite only.
- Sign-in lockout is per account and in memory (resets on restart).
- Experiment 12 (function points: complexity ratings, 10 FP per person-month) and Experiment 13 (Gantt/PERT dates, team size) use **assumptions**; replace them with the team's real data before submission.
- UI checked by component tests and headless-browser screenshots, not by a screen reader or automated end-to-end suite.
- Not load-tested.

## v3 candidates (only if required)
Real SMS/phone OTP and SMTP verification; PostgreSQL/Docker/Redis; scheduled retraining on live labels; automated browser tests and accessibility audit; a "Settled" state in the transaction state machine; an India-specific dataset.

## How to reproduce the numbers
`pip install -r requirements-dev.txt && python -m pytest --cov=app`, then `cd frontend && npm test`. `python scripts/collect_results.py` rewrites `docs/lab-file/results.json`.
