# Lab alignment — CIC-357 practical experiments 1–13

The syllabus lists 13 practical experiments. These artifacts describe the implemented local demo, with academic design intent distinguished from implemented behavior. The app is a synthetic-data demonstrator with a heuristic baseline; it has no trained classifier, real card data, payment authorization, role-based authentication, external notifications or production deployment.

## 1. Problem statement

Automated suspicious-transaction triage reduces dependence on manual review and rigid static checks. This MVP accepts a synthetic transaction token and transaction attributes, validates them, creates an explainable heuristic score, and returns APPROVE/HOLD/DECLINE. Analysts can record outcomes and administrators can configure cutoffs and blocked countries. It advises only; it does not move funds. The deliverable prioritizes local repeatability and privacy over production throughput/model accuracy.

## 2. Requirements and SRS summary

**Actors:** gateway client (represented by a REST caller), analyst workflow, administrator workflow. **Implemented functional requirements:** validate and score transaction requests; persist transactions; list alerts/history; record fraud/false-positive verdicts; block/unblock synthetic tokens; configure amount/country rules and thresholds; expose descriptive counts and an audit log. **Quality constraints implemented:** local setup, schema validation, heuristic reason strings, SQLite persistence, synthetic-only identifiers, HTTP JSON API. **Not implemented from the practical-file/SRS target:** trained supervised model, behavioral profile beyond same-day transaction count, velocity windows other than same-day count, analyst assignment, cardholder SMS/e-mail/step-up verification, retraining, user/role management, TLS/authentication, performance guarantees, payment authorization, or PCI compliance. The app only advises; false-positive review records a label and does not change the original decision. Config cutoffs must be ordered `approve_max < hold_max`; scores are in [0,1].

## 3. Function-oriented diagrams

### DFD Level 0
```mermaid
flowchart LR
  G[Gateway client] -->|Synthetic transaction| S((Fraud Detection Demo))
  S -->|Risk and decision| G
  S <-->|Review/verdict| A[Analyst]
  S <-->|Rules and reports| M[Administrator]
  S --- D[(SQLite)]
```

### DFD Level 1
```mermaid
flowchart LR
 G[Gateway] --> P1[1. Validate and ingest]
 P1 --> P2[2. Feature/rule scoring]
 D1[(Transactions and cards)] --> P2
 C[(Configuration)] --> P2
 P2 --> P3[3. Decide and alert]
 P3 --> D1
 P3 --> G
 P3 --> A[Analyst]
 A --> P4[4. Review case]
 P4 --> D1
 P4 --> L[(Audit log)]
 M[Administrator] --> P5[5. Configure and report]
 P5 --> C
 D1 --> P5
 L --> P5
```

### DFD Level 2 — scoring
```mermaid
flowchart TD
 I[Request] --> V{Schema valid?}
 V -->|No| E[HTTP validation error]
 V -->|Yes| B{Token blocked?}
 B -->|Yes| R[409 blocked]
 B -->|No| H[Read config and daily history]
 H --> F[Evaluate amount, country, channel, velocity]
 F --> S[Clamp score to 0..1]
 S --> D{Compare thresholds}
 D -->|Low| A[APPROVE]
 D -->|Medium| Hold[HOLD + alert]
 D -->|High| Decline[DECLINE + alert]
 A --> W[Persist transaction + audit]
 Hold --> W
 Decline --> W
```

### Structure chart
```mermaid
flowchart TD
 API[FastAPI application] --> Ingest[Transaction ingestion]
 API --> Review[Alert and review]
 API --> Admin[Admin/config/reporting]
 Ingest --> Validate[Typed request validation]
 Ingest --> Score[Heuristic scorer]
 Score --> Rules[Configurable rules]
 Ingest --> Store[(SQLite persistence)]
 Review --> Store
 Review --> Audit[Audit writer]
 Admin --> Store
 Admin --> Audit
 UI[Dashboard HTML/JS] --> API
```

## 4. ER diagram
```mermaid
erDiagram
 TRANSACTION {
  int id PK
  string token
  real amount
  string merchant
  string country
  string channel
  datetime created
  real score
  string decision
  json reasons
  string review
 }
 CARD {
  string token PK
  int blocked
 }
 CONFIG {
  string key PK
  string value
 }
 AUDIT {
  int id PK
  datetime at
  string actor
  string action
  string detail
 }
 CARD ||--o{ TRANSACTION : used_for
```

This is a logical relationship: the implementation has no separate alert or user table. Alerts are the non-APPROVE transaction rows; review status is stored on the transaction. The schema also has no explicit foreign-key constraint.

## 5. Use case diagram
```mermaid
flowchart LR
 Gateway[Gateway client] --- U1((Submit transaction))
 Gateway --- U2((Receive decision))
 Analyst[Analyst] --- U3((View alert queue))
 Analyst --- U4((Record verdict))
 Analyst --- U5((Block card via fraud verdict))
 Admin[Administrator] --- U6((Set thresholds and rules))
 Admin --- U7((View reports and audit))
 Admin --- U8((Block or unblock token))
```

## 6. Class and object diagrams
```mermaid
classDiagram
 class Tx {
  +card_token: str
  +amount: float
  +merchant: str
  +country: str
  +channel: str
 }
 class Verdict {
  +verdict: str
 }
 class Config {
  +approve_max: float
  +hold_max: float
  +high_amount: float
  +blocked_countries: str
 }
 class Scorer {
  +score(tx): tuple
 }
 class Database {
  +transactions
  +cards
  +config
  +audit
 }
 class FraudAPI {
  +ingest(tx)
  +alerts(status)
  +configure(data)
 }
 FraudAPI --> Tx
 FraudAPI --> Scorer
 FraudAPI --> Database
 Scorer --> Config
```

Example object snapshot (synthetic, illustrative seed):
```mermaid
classDiagram
 class tx17 {
  +token: str
  +amount: float
  +score: float
  +decision: str
 }
 class alert17 {
  +review: str
  +reasons: str
 }
 tx17 --> alert17 : surfaced as
```

## 7. State-chart and activity diagrams
```mermaid
stateDiagram-v2
 [*] --> Received
 Received --> Rejected: invalid or blocked
 Received --> Scored: validated
 Scored --> Approved: score <= approve_max
 Scored --> Held: score <= hold_max
 Scored --> Declined: score > hold_max
 Held --> Reviewed
 Declined --> Reviewed
 Reviewed --> ConfirmedFraud: fraud verdict / block token
 Reviewed --> FalsePositive: false positive verdict
 Approved --> [*]
 ConfirmedFraud --> [*]
 FalsePositive --> [*]
```

The implemented review verdict is stored as `CONFIRMED_FRAUD` or `FALSE_POSITIVE`; neither transition changes the original APPROVE/HOLD/DECLINE value. A confirmed-fraud verdict blocks the token. Settlement/release states in the reference are outside this demonstrator.

```mermaid
flowchart TD
 Start([Request]) --> Validate[Validate schema and token]
 Validate --> Score[Score from rules/history]
 Score --> Decide{Threshold decision}
 Decide -->|Approve| Persist[Persist and audit]
 Decide -->|Hold/decline| Alert[Create reviewable alert]
 Alert --> Queue[Analyst queue]
 Queue --> Verdict{Analyst verdict}
 Verdict -->|Fraud| Block[Block token and record verdict]
 Verdict -->|False positive| Clear[Record false positive]
 Block --> Persist
 Clear --> Persist
```

## 8. Sequence and communication diagrams
```mermaid
sequenceDiagram
 participant G as Gateway client
 participant API as FastAPI
 participant S as Scorer
 participant DB as SQLite
 participant A as Analyst
 G->>API: POST transaction
 API->>API: Validate and check blocked token
 API->>S: score(transaction)
 S->>DB: Read config and same-day token history
 DB-->>S: Rules and count
 S-->>API: score, decision, reasons
 API->>DB: Save transaction and audit
 API-->>G: decision response
 A->>API: GET alerts
 API->>DB: Read open cases
 DB-->>API: Cases
 API-->>A: Alert queue
 A->>API: POST verdict
 API->>DB: Save verdict; block token if fraud
 API-->>A: Review result
```

Communication view: `1 Gateway → API: submit`; `2 API → Scorer: evaluate`; `3 API → SQLite: persist`; `4 API → Gateway: decision`; `5 Analyst → API: fetch/review`; `6 API → SQLite: update verdict/card/audit`.

## 9. Component diagram
```mermaid
flowchart LR
 Browser[Dashboard: static HTML/JS] -->|JSON| API[FastAPI routes]
 API --> Validate[Pydantic validation]
 API --> Scorer[Heuristic scoring and thresholds]
 API --> Repo[SQLite data access: config, history and persistence]
 Repo --> DB[(SQLite file)]
 API --> Audit[Audit event writer]
 Scorer --> Config[Read configuration and recent count from SQLite]
```

## 10. Deployment diagram
```mermaid
flowchart LR
 subgraph LocalComputer[Developer laptop]
  Browser[Browser]
  Server[Uvicorn + FastAPI]
  DB[(SQLite file)]
  Browser -->|localhost HTTP| Server
  Server --> DB
 end
 Gateway[Optional synthetic API client] -->|localhost HTTP| Server
```

The practical file describes a production-equivalent browser/React, API gateway, application server, model server, Redis and PostgreSQL plus notification provider. Those are not deployed by this MVP. Local HTTP is for localhost demonstration only.

## 11. Testing

`tests/test_smoke.py` contains five API integration tests that call the FastAPI ASGI app directly and create a fresh SQLite file in the OS temporary directory for each test. The suite requires the declared FastAPI/Starlette/Pydantic dependencies, but no HTTP test-client package or separately running server. Last verified command: `python -m unittest discover -s tests -v`; **5 tests passed** (2026-10-20). Covered: dashboard/health, validation and threshold ordering, score range and persistence, analyst verdicts, fraud-triggered token block, blocked-token rejection, false-positive persistence, admin block/unblock and audit. This is functional smoke coverage, not exhaustive unit, system, load, security, model-quality or accuracy testing. No labelled evaluation dataset exists, so precision/recall/F1/PR-AUC are not measured. The tests do not claim to cover every individual rule branch or frontend interaction.

## 12. Function point effort estimate (assumption-based)

Illustrative unadjusted FP estimate using average complexity weights (EI=4, EO=5, EQ=4, ILF=10, EIF=7): inputs: transaction, verdict, config, block/unblock = 4 EI (16); outputs: score/decision, reports, history/alerts, audit = 4 EO (20); queries: health/config/cards/queue = 4 EQ (16); internal logical files: transaction, cards, config, audit = 4 ILF (40); external interfaces = 0 EIF (0). **Total 92 UFP.** This is a student planning estimate, not measured size; screens and endpoint overlap are simplified. At assumed 10 FP/person-month, effort ≈9.2 person-months; for 2 people ≈4.6 months before calendar overlap, testing and academic documentation. The local MVP is substantially smaller than this conceptual scope.

## 13. Gantt / PERT timeline

Assumption: two-person student team, 10-week calendar, tasks can partly overlap. Weeks are planning estimates rather than a claim about actual elapsed development.

```mermaid
gantt
 title Illustrative 10-week project timeline
 dateFormat YYYY-MM-DD
 axisFormat %d %b
 section Requirements and design
 SRS and scope :a1, 2026-10-01, 10d
 DFD/ER/UML design :a2, after a1, 10d
 section Build
 API and scoring :b1, after a1, 15d
 Dashboard and review :b2, after b1, 15d
 Persistence and admin :b3, after b1, 10d
 section Verification and delivery
 Integration and regression :c1, after b2, 10d
 Documentation and demo :c2, after c1, 10d
```

PERT dependency: `Requirements (2w) → Design (2w) → API/scoring (3w) → UI/review (3w) → integration (2w) → final docs/demo (2w)`. Expected critical path is 14 weeks under the assumed serial durations; parallelize persistence/admin and early documentation to target the 10-week calendar. Estimates are illustrative and should be replanned with actual team availability.
