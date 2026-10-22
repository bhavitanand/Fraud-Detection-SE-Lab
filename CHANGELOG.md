# Changelog

## v2.1 — 2026-10-23
- Added UI screenshots, `docs/SETUP.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DEMO.md`.
- Rewrote `STATUS.md` as a single current-state document.
- Fixed transaction-page horizontal overflow and oversized trend-chart labels.
- Corrected README seed counts (129 transactions, 19 merchants).
- Removed leftover starter files.
- Lab file: function-point breakdown chart added to Experiment 12.

## v2.0 — 2026-10-22
- Layered back end (api / services / repositories / schemas / db), versioned migrations to schema v3.
- E-mail + password sign-in with roles, optional e-mail OTP, user management.
- India model: INR, Indian cities, merchants, MCC codes; velocity, new-country, new-merchant and impossible-travel rules.
- ML pipeline on the ULB dataset with registry, SHA-256 verified artifacts and benchmark replay.
- Cardholder outbox with one-time reply link; hash-chained audit log.
- React + TypeScript console (13 pages); 181 pytest and 26 Vitest tests.
- Lab file extended to Experiments 1–13 with as-built notes and appendix.

## v1.0 — 2026-10-20
- Initial FastAPI + SQLite prototype with heuristic scoring, static dashboard and 5 smoke tests.
