# Status — v3.0 (2026-11-17)

Current state of the project. Older audit notes were folded into this file; the first version (heuristic-only, no auth, 5 tests) no longer exists.

## What works (verified this session)
| Area | State | Evidence |
|---|---|---|
| Back end (FastAPI + SQLite, layered) | Working | 195 pytest tests passed, 95% line coverage |
| Front end (React + strict TypeScript) | Working | 29 Vitest tests passed; strict `tsc` and `npm run build` clean; new pages opened in headless Chromium at 1440×900 |
| Auth | Working | E-mail + password (Argon2), roles analyst/admin enforced server-side, optional e-mail OTP |
| Scoring | Working | Live scorer: calibrated XGBoost on 19 shared features, with top reasons; rules `heuristic-v2` as fallback and context |
| Live scorer metrics | Measured on SIMULATED data | Held-out 138,527 simulated transactions (1,763 frauds): PR-AUC 0.934, precision 94.4%, recall 84.5%, false alarms 0.06% at the 0.25 flag threshold. Rules alone: PR-AUC 0.229. Weak spot: low-and-slow fraud (3% recall). Not real-world accuracy |
| Benchmark model | Working | Random forest on the public ULB dataset; PR-AUC 0.782, precision 85.1%, recall 77.0% (74 frauds in the test split) |
| Live mode and autopilot | Working | 150-card run: about 5,900 transactions, 84% precision and 84% recall against simulation ground truth, 79% of alerts closed without a human, 2.2 ms average scoring time |
| AI copilot | Working offline; Gemini path tested only with a mocked transport | No live Gemini call was made from the build environment |
| Deployment files | Written, not exercised | Dockerfile, compose, `render.yaml`, CI workflow were not built or run in the build environment (no Docker available) |
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
- The live scorer is trained on simulated data. Its accuracy figures are about the simulator, not the real world; simulated fraud prevalence (1.2%) is far above real rates. No real Indian labelled dataset exists in this repo. The ULB benchmark model is real data but European and 2013.
- Live mode's simulated cardholder replies and the Gemini copilot are the only non-deterministic parts; Gemini needs internet and a key.
- Seeded demo rows were scored by the rules; only transactions submitted after start-up use the live scorer.
- No real payment authorisation, bank/network integration, SMS, real e-mail by default, TLS, PCI DSS compliance, or PostgreSQL/Redis. SQLite only.
- Sign-in lockout is per account and in memory (resets on restart).
- Experiment 12 (function points: complexity ratings, 10 FP per person-month) and Experiment 13 (Gantt/PERT dates, team size) use **assumptions**; replace them with the team's real data before submission.
- UI checked by component tests and headless-browser screenshots, not by a screen reader or automated end-to-end suite.
- Not load-tested.

## v3 candidates (only if required)
Real SMS/phone OTP and SMTP verification; PostgreSQL/Docker/Redis; scheduled retraining on live labels; automated browser tests and accessibility audit; a "Settled" state in the transaction state machine; an India-specific dataset.

## How to reproduce the numbers
`pip install -r requirements-dev.txt && python -m pytest --cov=app`, then `cd frontend && npm test`. `python scripts/collect_results.py` rewrites `docs/lab-file/results.json`.
