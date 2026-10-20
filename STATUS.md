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
