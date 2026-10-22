# Lab alignment: Software Engineering Lab (CIC-357)

The authoritative deliverable is the practical file (`docs/lab-file/SE_Lab_File_Credit_Card_Fraud_Detection_updated.docx`, rebuilt by `docs/lab-file/build_lab_file.py` from the submitted original). This page maps each syllabus experiment to evidence in the repository and says what is **specified in the file**, **implemented**, and **only proposed**. The syllabus requires at least 10 experiments with at least 5 from its list; the file covers all 13 listed.

| Exp | Syllabus item | In the lab file | Evidence in the repository | Status |
|---|---|---|---|---|
| 1 | Problem statement | as submitted + as-built note | README, scope in `STATUS.md` | done |
| 2 | Requirement analysis, SRS | as submitted + FR-1…13 status table | tests per requirement (`tests/`), `GET /api/health`, latency in `results.json` | done; FR-6, FR-11, FR-12 partly implemented |
| 3 | DFD levels 0–2, structure chart | as submitted + design→code map | `app/services/*`, `app/repositories/db_access.py` | done |
| 4 | ER diagram | as submitted + entity→table map | migration v3 in `app/db/migrations.py` (7 entities + supporting tables) | done; matches |
| 5 | Use case diagram | as submitted + use case→page map | UI pages, `app/api/routes.py` | done |
| 6 | Class and object diagram | as submitted + class→module map | `scoring.py`, `ml/wrapper.py`, `ml_service.py` | done |
| 7 | State-chart, activity | as submitted + implemented states | `transactions_service.py` (review state machine) | done; Settled not implemented |
| 8 | Sequence, collaboration | as submitted + as-built note | `ingest()` single DB transaction | done |
| 9 | Component diagram | as submitted + Fig. 9.2 as-built | `docs/lab-file/diagrams.py` | done |
| 10 | Deployment diagram | as submitted + Fig. 10.2 as-built | `run-demo.ps1`, README | done |
| 11 | Unit and integration testing with a tool | new: unit, integration, BVA/ECP/decision-table cases, coverage | `tests/` (pytest), `frontend/src/*.test.tsx` (Vitest), `scripts/collect_results.py` | drafted from measured results |
| 12 | Function Point estimation | new: counts, 14 GSC, VAF, AFP, effort, COCOMO cross-check | `docs/lab-file/build_lab_file.py` | drafted; ratings and productivity are assumptions |
| 13 | Gantt / PERT | new: activity table, Gantt, PERT, critical path | `docs/lab-file/diagrams.py` | drafted; schedule is a baseline to replace with real dates |

## Requirements in the submitted SRS vs the demonstrator
Specified in the file: ML + rules hybrid, behavioural features, cardholder notification and step-up, alert and case management, retraining, reports, PostgreSQL, Redis, TLS, containers, RBAC, auditability.
Implemented: everything in that list except PostgreSQL, Redis, TLS and containers (SQLite, single process, localhost) and real SMS/e-mail notification (simulated outbox).
Proposed for production only: PostgreSQL, Redis feature cache, API gateway and TLS termination, container deployment, real notification providers, scheduled retraining on live labels, device and IP features.
Assumptions and estimates (not measurements): FP complexity ratings and productivity (10 FP per person-month), the PERT estimates, fixed FX rates.
