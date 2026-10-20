# Project agent instructions — Credit Card Fraud Detection System

## Scope and source of truth
- This folder is the sole project workspace. Work only inside this workspace. Do not read, write, search, or modify files outside it. Do not inspect the user's Desktop, Documents, other projects, SSH keys, browser data, environment files, or personal directories.
- The authoritative assignment references are `reference/SE_Lab_File_Credit_Card_Fraud_Detection.pdf` and `reference/Software_Engineering_Syllabus.pdf`. Read the adjacent `.txt` extractions for searchable text, and consult the PDFs for diagrams/figures. Preserve the terminology and requirements actually in those files; distinguish implementation choices from stated requirements.
- Do not invent that real banking infrastructure, real SMS, real payment authorisation, or production-level model accuracy exists. This is an academic demonstrator using synthetic/demo transactions unless a dataset is provided inside this folder.
- Do not use external network access, install/download packages, run containers, or connect to third-party services without explicit approval. Do not use secrets or real cardholder data.

## Product goal
Build a polished, locally runnable Credit Card Fraud Detection System demonstrator consistent with the project practical file and the SE Lab syllabus. Prioritise a coherent end-to-end demo over a sprawling, half-implemented architecture.

The practical-file target stack is Python/FastAPI, scikit-learn or XGBoost, PostgreSQL, Redis, and a React web dashboard. Where services are not installed locally, design a practical local development fallback (for example SQLite and an in-process cache) and clearly document the production-equivalent PostgreSQL/Redis option rather than making setup impossible.

Core demo flows to implement:
1. Transaction ingestion and validation through a REST API.
2. Explainable demo risk score in [0,1] combining model-style scoring and configurable rules; show why a transaction was flagged. If a trained model or real dataset is absent, label scoring clearly as a demo baseline and never claim measured real-world accuracy.
3. Configurable APPROVE / HOLD / DECLINE thresholds.
4. Persistent transaction history and fraud alerts.
5. Analyst queue with filters, case detail, verdict recording (confirmed fraud / false positive), and card block/unblock behavior.
6. Admin-configurable rules/thresholds and basic reports for fraud rate, detection/false-positive counts and alert backlog.
7. Seeded synthetic demo data; no real card numbers. Use generated tokens/masked identifiers only.
8. Useful validation, errors, tests, health endpoint, and clear local setup instructions.
9. If reasonable within the available time, basic roles/auth for Analyst and Administrator, while clearly marking demo-only authentication limitations.

## Engineering rules
- First inspect this file and both reference text extractions/PDFs; then make a small implementation plan and proceed without asking routine questions.
- Keep the app runnable on a Windows laptop with 16 GB RAM. Avoid heavy dependencies, heavyweight model downloads, mandatory Docker, and unnecessary services for the default demo.
- Prefer small, comprehensible modules and typed request/response schemas. Validate input; never store a full PAN or CVV. Explain that this prototype is not PCI DSS compliant and must not receive real payment data.
- Never silently overwrite existing user files (initially this folder should contain only these starter files). Never delete, reset, or force-clean anything. No destructive git operations.
- Do not change global machine configuration or install software. Use only the current project directory.
- Keep docs truthful: commands must match actual files; don't claim tests passed unless they were run and passed.
- Avoid leaving critical flows as TODOs. If an external dependency is missing, provide the code/config and a clearly documented fallback rather than repeatedly attempting installs.
- Create `STATUS.md` as you go. If interrupted or nearing context limits, record what works, tests actually run, remaining defects, and the exact next steps.

## Software Engineering Lab deliverables
Create `docs/lab-alignment.md` mapping the implemented system to the 13 experiments listed in the lab syllabus/practical file. Provide diagrams as source-controlled Mermaid diagrams where suitable, including:
1. Problem statement;
2. SRS / requirements;
3. DFD levels 0, 1 and 2 plus structure chart;
4. ER diagram;
5. Use case diagram;
6. Class and object diagrams;
7. Transaction state-chart and activity diagram;
8. Sequence and collaboration/communication diagram;
9. Component diagram;
10. Deployment diagram;
11. Unit and integration tests;
12. Explicitly labelled function-point effort estimate with assumptions;
13. Gantt/timeline or PERT with assumptions.

Priority order for this first pass: (P0) inspect sources and plan; (P1) functioning local end-to-end application and run instructions; (P2) tests and bug fixes; (P3) lab alignment and diagram documentation. Do not sacrifice an executable MVP to generate lots of documentation.
