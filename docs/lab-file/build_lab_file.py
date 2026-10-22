"""Builds the updated practical file from the submitted original:  python docs/lab-file/build_lab_file.py
 - keeps Experiments 1-10 exactly as submitted;
 - adds an "Implementation Note (as built)" before each Result line, mapping the design to the working demonstrator;
 - adds Experiments 11, 12 and 13 and an appendix, using measured results from results.json and figures from diagrams.py.
Re-run scripts/collect_results.py and docs/lab-file/diagrams.py first when the code changes."""
from __future__ import annotations

import copy
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import docx
from docx.oxml import parse_xml
from docx.shared import Cm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import diagrams  # noqa: E402

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
TNR = '<w:rFonts w:ascii="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman" w:hAnsi="Times New Roman"/>'
R = json.loads((HERE / "results.json").read_text())
ACTS, ORDER, CRIT, END, SD = diagrams.cpm()


# ----------------------------------------------------------------------------- XML helpers
def runs(text: str, size: int = 24, bold: bool = False, italic: bool = False, mono: bool = False) -> str:
    """'**bold**' segments inside text become bold runs."""
    out = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        b = bold or i % 2 == 1
        font = '<w:rFonts w:ascii="Courier New" w:cs="Courier New" w:hAnsi="Courier New"/>' if mono else TNR
        out.append(f'<w:r><w:rPr>{font}{"<w:b/><w:bCs/>" if b else ""}{"<w:i/><w:iCs/>" if italic else ""}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>'
                   f'<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def P(text: str, align: str = "both", size: int = 24, after: int = 120, line: int | None = 300, bold: bool = False, italic: bool = False, mono: bool = False, keep: bool = False, indent: int = 0):
    ln = f' w:line="{line}"' if line else ""
    ind = f'<w:ind w:left="{indent}" w:hanging="260"/>' if indent else ""
    return parse_xml(f'<w:p {NS}><w:pPr>{"<w:keepNext/>" if keep else ""}<w:spacing w:after="{after}"{ln}/>{ind}<w:jc w:val="{align}"/></w:pPr>{runs(text, size, bold, italic, mono)}</w:p>')


def H2(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:pStyle w:val="Heading2"/><w:keepNext/><w:spacing w:after="100" w:before="200"/></w:pPr>{runs(text, 26, True)}</w:p>')


def H3(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:keepNext/><w:spacing w:after="80" w:before="120"/></w:pPr>{runs(text, 24, True, True)}</w:p>')


def BUL(text: str):
    return P("•\u00A0" + text, indent=360, after=60)


def CAPTION(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:spacing w:after="160"/><w:jc w:val="center"/></w:pPr>{runs(text, 21, False, True)}</w:p>')


def RESULT(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:spacing w:after="120" w:line="300"/><w:jc w:val="both"/></w:pPr>{runs("Result:- ", 24, True)}{runs(text, 24)}</w:p>')


def TABLE(rows: list[list[str]], widths: list[int], size: int = 20, align_right: set[int] = frozenset()):
    border = "".join(f'<w:{s} w:val="single" w:color="888888" w:sz="4"/>' for s in ("top", "left", "bottom", "right"))
    mar = '<w:tcMar><w:top w:type="dxa" w:w="50"/><w:left w:type="dxa" w:w="90"/><w:bottom w:type="dxa" w:w="50"/><w:right w:type="dxa" w:w="90"/></w:tcMar>'
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    trs = []
    for ri, row in enumerate(rows):
        hdr = ri == 0
        cells = []
        for ci, (cell, w) in enumerate(zip(row, widths)):
            shd = '<w:shd w:fill="D9E2F3" w:color="auto" w:val="clear"/>' if hdr else ""
            jc = '<w:jc w:val="right"/>' if (ci in align_right and not hdr) else ""
            cells.append(f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{w}"/><w:tcBorders>{border}</w:tcBorders>{shd}{mar}</w:tcPr><w:p><w:pPr><w:spacing w:after="20"/>{jc}</w:pPr>{runs(str(cell), size, hdr)}</w:p></w:tc>')
        trs.append(f'<w:tr><w:trPr>{"<w:tblHeader/>" if hdr else ""}<w:cantSplit/></w:trPr>{"".join(cells)}</w:tr>')
    total = sum(widths)
    return parse_xml(f'<w:tbl {NS}><w:tblPr><w:tblW w:type="dxa" w:w="{total}"/><w:tblLayout w:type="fixed"/><w:tblBorders>'
                     + "".join(f'<w:{s} w:val="single" w:color="auto" w:sz="4"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
                     + f'</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(trs)}</w:tbl>')


def SPACER():
    return P("", after=80, line=None, size=8)


# ----------------------------------------------------------------------------- document assembly
doc = docx.Document(str(HERE / "SE_Lab_File_original.docx"))
body = doc.element.body
paras = list(doc.paragraphs)
heads = {}
for p in paras:
    m = re.match(r"Experiment (\d+)", p.text.strip())
    if m and p._p.pPr is not None and p._p.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pageBreakBefore") is not None:
        heads[int(m.group(1))] = p
assert sorted(heads) == list(range(1, 11)), sorted(heads)


def result_anchor(k: int):
    start = paras.index(heads[k])
    end = paras.index(heads[k + 1]) if k + 1 in heads else len(paras)
    for p in paras[start:end]:
        if p.text.strip().startswith("Result"):
            return p._p
    return heads[k + 1]._p if k + 1 in heads else None


def insert_before(anchor, elements):
    for e in elements:
        anchor.addprevious(e)


def picture(path: Path, width_cm: float):
    doc.add_picture(str(path), width=Cm(width_cm))
    p = doc.paragraphs[-1]
    p.alignment = 1
    p.paragraph_format.space_after = docx.shared.Pt(4)
    p.paragraph_format.keep_with_next = True
    return p._p


FIGS = HERE / "figures"
NOTE_HEAD = "Implementation Note (as built in the demonstrator)"
n_tests, cov, lat, loc = R["backend"]["tests"], R["backend"]["coverage_percent"], R["latency_ms"], R["loc"]
fe = R["frontend"]
DESIGN_VS = "The diagram above is the target design submitted for this experiment and is unchanged."

# ------------------------------------------------------------------ notes for Experiments 1-10
NOTES: dict[int, list] = {}
NOTES[1] = [
    H2(NOTE_HEAD),
    P("The working demonstrator implements the core of this problem statement for an **Indian card portfolio**: amounts are in rupees (₹) with lakh-style grouping, the synthetic customers, cities, merchants and Merchant Category Codes are Indian, and thresholds such as the high-amount limit (₹50,000) are set in INR. Names of merchants and banks are illustrative labels on invented data; no real customer data is used and no affiliation is implied."),
    P("**Data and model.** The public ULB/Kaggle dataset named in this experiment (284,807 transactions, 492 frauds, European cardholders, 2013, amounts in EUR) was used to train and evaluate the machine-learning component. Its features are anonymised principal components, so the model can score only transactions that carry those features; Indian demo transactions are scored by the rule engine. Both facts are stated on the application’s ML page."),
    P("**Cost analysis.** The demonstrator uses SQLite and runs in one process on a laptop (no PostgreSQL, Redis or containers). The stack remains open source, so the software licence cost is nil. PostgreSQL, Redis and containers stay as the proposed production design."),
]
FR_STATUS = [
    ["ID", "Status", "How it is met in the demonstrator"],
    ["FR-1", "Implemented", "Token, amount, currency (INR default), merchant, country, city, channel; validated; card-number-like values rejected. Time is set by the server."],
    ["FR-2", "Implemented", "24-hour velocity, amount against the card’s average, new country, new merchant, distance and time between consecutive transactions (city level). No device or IP features."],
    ["FR-3", "Implemented (hybrid)", "Rule engine always runs. The ML probability is combined (noisy-OR) when the 28 benchmark features are present; live Indian transactions are rule-scored."],
    ["FR-4", "Implemented", "APPROVE / HOLD / DECLINE from configurable thresholds, validated on the server."],
    ["FR-5", "Implemented", "A fraud_alerts row is created for every HOLD or DECLINE."],
    ["FR-6", "Partly", "A cardholder message is queued in a simulated outbox with a one-time reply link (“Was this you?”). “Not me” blocks the card. No real SMS or e-mail provider; real e-mail is used only for the optional sign-in code."],
    ["FR-7", "Implemented", "Alert queue with filters, assign to self (administrator can assign anyone), transaction and card history."],
    ["FR-8", "Implemented", "Confirmed fraud (blocks the token) or false positive; one verdict per alert; manual block/unblock by administrators."],
    ["FR-9", "Implemented", "Users page: create, change role, disable, reset password. Roles analyst and administrator."],
    ["FR-10", "Implemented", "Thresholds, high-amount limit, blocked countries and velocity limit. Rule weights are fixed in code."],
    ["FR-11", "Partly", "Confirmed labels are stored and exportable. Training and evaluation run offline (python -m ml.train); administrators deploy or retire registered models in the UI. No scheduled retraining on live labels."],
    ["FR-12", "Partly", "Fraud rate, false-positive share, backlog, analyst productivity, flagged value. Detection rate is shown only for the held-out test set and the benchmark replay, because approved live transactions are never labelled."],
    ["FR-13", "Implemented", "Every score, decision and action is logged; entries are hash-chained and an administrator can verify the chain (tamper-evident, not tamper-proof)."],
]
NOTES[2] = [
    H2(NOTE_HEAD),
    P("Status of each functional requirement in the working application (verified by automated tests, see Experiment 11):", keep=True),
    TABLE(FR_STATUS, [800, 1500, 6726], size=19), SPACER(),
    P(f"**Non-functional requirements.** Scoring latency (target about 200 ms for 95% of requests): measured in-process over {lat['n']} requests, median {lat['p50']:.1f} ms, 95th percentile {lat['p95']:.1f} ms (network and browser time excluded; not a load test). Roles are enforced by the backend on every protected route. Passwords are stored as Argon2 hashes; sign-in can require an e-mail code. Full card numbers are never accepted or stored, but TLS and PCI DSS certification are not provided; the application must be placed behind a TLS proxy before any real deployment. If the ML component is missing or fails, scoring continues with the rules (tested). Redis, PostgreSQL, containers and horizontal scaling are not implemented."),
]
NOTES[3] = [
    H2(NOTE_HEAD),
    P("Each DFD process and structure-chart module has a counterpart in the code. Data stores D1 to D5 are tables of one SQLite database.", keep=True),
    TABLE([["Design element", "Where it lives in the code"],
           ["1.0 Transaction Ingestion & Validation / Transaction Handler", "app/schemas/models.py (TransactionIn) and transactions_service.ingest"],
           ["2.0 Feature Engineering / Feature Engine", "repositories.card_history_stats and the ScoringInput built in ingest (replaces the Redis feature cache with an indexed SQL query)"],
           ["3.1 Load model and rules", "settings_service.load_risk_config and ml_service.ModelService (artifact hash verified before loading)"],
           ["3.2 Apply rule engine", "scoring.HeuristicScorer (nine rules, every point a named factor)"],
           ["3.3 ML model inference", "ml/wrapper.CalibratedModel through ModelService.predict"],
           ["3.4 Combine scores and normalise", "scoring.HybridScorer: 1 − (1 − rules)(1 − p), capped at 1"],
           ["4.0 Decision & Alert Generation / Decision & Alert Manager", "scoring.decide, fraud_alerts rows, notifications_service (simulated cardholder message)"],
           ["5.0 Case Review & Feedback / Case Manager", "transactions_service.review and assign, cards_service, notifications_service.record_reply, label export"],
           ["6.0 Model Training & Management / Model Manager", "ml/train.py (offline) and models_service (register, deploy, retire, replay)"],
           ["7.0 Reporting & Administration", "reports_service, settings_service, auth_service (users)"],
           ["D1 Transaction DB / D2 Card & Customer Profile / D3 Alert & Case / D4 Model & Rule Store / D5 Rule & Threshold Store", "tables transactions; customers, cards, merchants; fraud_alerts; ml_models; config"]],
          [3600, 5426], size=19),
]
NOTES[4] = [
    H2(NOTE_HEAD),
    P("The working database implements the seven entities of this ER diagram. Deviations are listed below; the diagram itself is unchanged.", keep=True),
    TABLE([["ER entity", "Table in the demonstrator", "Differences"],
           ["Customer", "customers", "Single name field instead of first and last name; phone numbers are invented; home_country defaults to IN."],
           ["Card", "cards", "card_id primary key and unique card_token as designed; adds network, issuer, card_type, expiry_date, credit_limit. status is derived from a blocked flag with reason, time and actor."],
           ["Merchant", "merchants", "As designed (category_code, country, risk_level) plus category label and city."],
           ["Transaction", "transactions (read through the view v_transactions)", "Adds currency, location (city), channel, source (SEED, LIVE or BENCH), scorer version, score factors; card_id, merchant_id and model_id are foreign keys."],
           ["ML_Model", "ml_models", "recall_score is the recall on the held-out test set at the application’s flag threshold; also stores PR-AUC, precision, F1, artifact hash and status candidate/active/retired."],
           ["Fraud_Alert", "fraud_alerts", "One row per HOLD or DECLINE (unique txn_id); assigned_to, status OPEN / CONFIRMED_FRAUD / FALSE_POSITIVE, resolution note, cardholder response."],
           ["Analyst", "users, exposed as the view analysts", "Administrators are also rows of users; the e-mail address is the sign-in name."],
           ["(not in the ER)", "config, audit, notifications, otp_challenges, meta, schema_version", "Supporting tables: thresholds, hash-chained audit log, simulated outbox, one-time sign-in codes, signing secret, migration history."]],
          [1500, 2500, 5026], size=19),
]
NOTES[5] = [
    H2(NOTE_HEAD),
    TABLE([["Use case", "Where it is implemented"],
           ["Submit Transaction, Score Transaction, Approve / Decline", "POST /api/transactions and the “Submit synthetic transaction” form; response carries score, decision and factors"],
           ["Generate Fraud Alert", "automatic for every HOLD or DECLINE (fraud_alerts row)"],
           ["Receive Fraud Notification, Confirm / Dispute Transaction, Block Card (cardholder)", "Cardholder messages page (simulated outbox) and the public reply page /confirm/…; “No, this was not me” blocks the card"],
           ["Review Alerts, View Txn History, Mark Fraud / False Positive", "Alerts and cases page, transaction page (score factors, history, audit trail, verdict with confirmation)"],
           ["Block / Unblock Card (staff)", "Cards page (administrator) and automatically after a confirmed-fraud verdict"],
           ["Generate Reports", "Overview and Reports pages, CSV export, analyst productivity"],
           ["Configure Rules & Thresholds", "Fraud rules page (administrator, validated on client and server)"],
           ["Train / Retrain Model", "python -m ml.train offline, then Deploy or Retire on the ML model page (administrator)"],
           ["Manage Users & Roles", "Users page (administrator)"]], [3800, 5226], size=19),
]
NOTES[6] = [
    H2(NOTE_HEAD),
    P("The code base is function-oriented around services and repositories rather than one Python class per entity, so the class diagram maps to modules: FraudDetector → HybridScorer and transactions_service.ingest; RuleEngine → HeuristicScorer; MLModel → CalibratedModel (ml/wrapper.py) managed by ModelService; Customer, Card, Merchant, Transaction, FraudAlert → rows of the tables listed under Experiment 4; User, Analyst, Administrator → the users table with a role checked by require_admin."),
]
NOTES[7] = [
    H2(NOTE_HEAD),
    P("States implemented: Received → Rejected (validation error 422, or blocked card 409 with an audit entry) or Validated → Scoring → Approved, Held for Review or Declined. Held and declined transactions get an alert in state OPEN, then Confirmed Fraud (card blocked) or False Positive; a verdict is final. **Not implemented:** Settled, and releasing a cleared (false-positive) transaction to Approved. The demonstrator advises on risk; it does not authorise, release or settle payments."),
]
NOTES[8] = [
    H2(NOTE_HEAD),
    P("The scoring sequence runs in one database transaction: validate, read the card history (the “Feature Store” is an indexed SQL query, not a separate service), score with the rules and, when features exist, the in-process ML model, save the transaction, create the alert and the simulated cardholder message, write the audit entry, return the decision. The analyst’s verdict, the card block and their audit entries are likewise committed together; a failed audit write rolls everything back (tested)."),
]
NOTES[9] = [
    H2(NOTE_HEAD),
    P("The demonstrator is a modular monolith. The as-built component diagram is shown below; the target design above is unchanged. Differences: no Redis feature cache (SQL query instead), PostgreSQL replaced by SQLite, ML inference runs in-process rather than as a separate service, the Notification Service is a simulated outbox (optional SMTP only for sign-in codes), and training is an offline command.", keep=True),
    "FIG:fig_9_2_component_asbuilt.png:13.5",
    CAPTION("Fig. 9.2: As-built component diagram of the demonstrator"),
]
NOTES[10] = [
    H2(NOTE_HEAD),
    P("The demonstrator runs on one machine and binds to 127.0.0.1. There is no API gateway, load balancer, TLS termination, separate database or cache server, or SMS provider; those remain the proposed production deployment shown above.", keep=True),
    "FIG:fig_10_2_deployment_asbuilt.png:12.5",
    CAPTION("Fig. 10.2: As-built deployment of the demonstrator"),
]
for k, items in NOTES.items():
    anchor = result_anchor(k)
    out = []
    for it in items:
        if isinstance(it, str) and it.startswith("FIG:"):
            _, name, w = it.split(":")
            out.append(picture(FIGS / name, float(w)))
        else:
            out.append(it)
    if anchor is None:
        for e in out:
            body.insert(len(body) - 1, e)
    else:
        insert_before(anchor, out)

# ------------------------------------------------------------------ index table: add rows 11-13
index = next(t for t in doc.tables if len(t.columns) == 4 and t.rows[0].cells[0].text.strip().startswith("Exp"))
titles = {11: "Testing: unit and integration testing with a testing tool (including black-box techniques)", 12: "Effort estimation using Function Point (FP) analysis", 13: "Time line chart: Gantt chart and PERT chart"}
for n, title in titles.items():
    row = copy.deepcopy(index.rows[-1]._tr)
    index._tbl.append(row)
    cells = index.rows[-1].cells
    for c, text in zip(cells, [str(n), title, "", ""]):
        for p in c.paragraphs[1:]:
            p._p.getparent().remove(p._p)
        rs = c.paragraphs[0].runs
        if rs:
            rs[0].text = text
            for r_ in rs[1:]:
                r_._r.getparent().remove(r_._r)
        elif text:
            c.paragraphs[0].add_run(text)

# ------------------------------------------------------------------ new experiments: copy the Experiment 10 heading style
last_result = next(p for p in reversed(doc.paragraphs) if p.text.strip().startswith("Result"))
tail = last_result._p


def new_heading(text: str):
    h = copy.deepcopy(heads[10]._p)
    ts = h.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
    ts[0].text = text
    for t in ts[1:]:
        t.text = ""
    return h


def AIM(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:spacing w:after="120" w:line="300"/><w:jc w:val="both"/></w:pPr>{runs("Aim:- ", 24, True)}{runs(text, 24)}</w:p>')


def SOFT(text: str):
    return parse_xml(f'<w:p {NS}><w:pPr><w:spacing w:after="120" w:line="300"/><w:jc w:val="both"/></w:pPr>{runs("Software Used:- ", 24, True)}{runs(text, 24)}</w:p>')


def add(elements):
    global tail
    for e in elements:
        if isinstance(e, str) and e.startswith("FIG:"):
            _, name, w = e.split(":")
            e = picture(FIGS / name, float(w))
        tail.addnext(e)
        tail = e


mods = {}
for name, n in R["backend"]["modules"].items():
    mods[name] = n
suite_rows = [["Test module", "Kind", "Tests"]]
KIND = {"test_scoring": "Unit (rule engine, decision thresholds, hybrid scorer)", "test_smoke": "Integration (original five API scenarios)", "test_workflows": "Integration + validation (API, database, reports, CSV)",
        "test_db_and_failures": "Integration (migrations, isolation, failure handling, static serving)", "test_auth": "Integration (sign-in, one-time code, roles, user management, CLI)",
        "test_india_and_alerts": "Integration (India features, alerts, cardholder reply, assignment, audit chain)", "test_ml": "Integration (model registry, replay, tamper checks)",
        "test_exp11_black_box": "Black-box design (boundary value, equivalence class, decision table, state transition)"}
for name in sorted(mods):
    suite_rows.append([name + ".py", KIND.get(name, ""), str(mods[name])])
suite_rows.append(["**Total (backend, pytest)**", "", f"**{n_tests}**"])
suite_rows.append(["Frontend (Vitest + Testing Library)", "Component and flow tests with a mocked API", str(fe["tests"])])

cov_files = sorted(((k, v) for k, v in R["backend"]["files"].items() if v["statements"] >= 10), key=lambda kv: kv[1]["percent"])
cov_rows = [["Module", "Statements", "Covered"]] + [[k, str(v["statements"]), f'{v["percent"]}%'] for k, v in cov_files[:8]]

BVA = [["ID", "Input under test", "Test values", "Expected"],
       ["BVA-1..6", "amount (valid 0.01 to 100,000,000)", "0 | 0.01 | 0.02 | 99,999,999.99 | 100,000,000 | 100,000,000.01", "reject, accept, accept, accept, accept, reject"],
       ["BVA-7..12", "card token length (valid 4 to 40)", "3 | 4 | 5 | 39 | 40 | 41 characters", "reject, accept ×5 up to 40, reject at 41"],
       ["BVA-13..15", "country code length (valid 2)", "1 | 2 | 3 letters", "reject, accept, reject"],
       ["BVA-16..18", "benchmark feature count (valid 28)", "27 | 28 | 29 values", "reject, accept, reject"],
       ["BVA-19..21", "high-amount rule (limit ₹50,000)", "49,999.99 | 50,000 | 50,000.01", "no flag, no flag, flag"],
       ["BVA-22..24", "velocity rule (limit 4 earlier transactions)", "3 | 4 | 5", "no flag, flag, flag"],
       ["BVA-25..30", "decision thresholds (approve ≤ 0.25 < hold ≤ 0.65)", "0.2499 | 0.25 | 0.2501 | 0.6499 | 0.65 | 0.6501", "APPROVE, APPROVE, HOLD, HOLD, HOLD, DECLINE"]]
ECP = [["ID", "Input", "Equivalence classes (representative value)", "Expected"],
       ["ECP-1..7", "channel", "POS, ONLINE, ATM, WALLET (valid); FAX, “online”, empty (invalid)", "valid accepted; invalid rejected (422)"],
       ["ECP-8..15", "currency", "INR, USD, EUR, GBP, AED, SGD (valid); JPY, “inr” (invalid)", "valid accepted; invalid rejected"],
       ["ECP-16..22", "card token", "SYNTH-IN-1001, a_b-c_9 (valid); with space, with symbol, markup, 16-digit and 19-digit card numbers (invalid)", "valid accepted; invalid rejected; card numbers never stored"]]
DT = [["ID", "C1 blocked country", "C2 amount above ₹50,000", "C3 online channel", "Score", "Decision"],
      ["DT-1", "No", "No", "No", "0.04", "APPROVE"], ["DT-2", "No", "No", "Yes", "0.14", "APPROVE"], ["DT-3", "No", "Yes", "No", "0.39", "HOLD"], ["DT-4", "No", "Yes", "Yes", "0.49", "HOLD"],
      ["DT-5", "Yes", "No", "No", "0.79", "DECLINE"], ["DT-6", "Yes", "No", "Yes", "0.89", "DECLINE"], ["DT-7", "Yes", "Yes", "No", "1.00 (capped)", "DECLINE"], ["DT-8", "Yes", "Yes", "Yes", "1.00 (capped)", "DECLINE"]]

exp11 = [
    new_heading("Experiment 11: Testing: Unit Testing and Integration Testing with a Testing Tool"),
    AIM("To perform unit testing and integration testing, with black-box test design, on the working code of the Credit Card Fraud Detection System using a testing tool."),
    SOFT(f"pytest 8 with the FastAPI test client and pytest-cov (coverage.py) for the Python back end; Vitest with Testing Library for the React front end; the TypeScript compiler in strict mode. Python {R['python']}."),
    H2("Theory"),
    P("**Unit testing** checks the smallest testable parts (functions and classes) in isolation. **Integration testing** checks that units work together, here through the real HTTP interface and a real database. **Black-box (functional) testing** designs cases from the specification without looking at the code: **boundary value analysis** tests values at and next to the edges of an input range, **equivalence class partitioning** tests one representative of each class of inputs that should behave alike, and **decision-table testing** covers every combination of conditions. **Structural (white-box) testing** is measured here as statement coverage. **Regression testing** means rerunning the whole suite after every change."),
    H2("Test environment and method"),
    P("Every test creates its own temporary SQLite database, so tests are independent and never touch the demo database. The API is called through the FastAPI test client (the real application, routing, validation, services and database). Test data is deterministic. The rule-based scoring unit is tested directly with explicit inputs; the ML component is tested with the shipped model and with a stub."),
    H2("A. Unit testing"),
    TABLE([["Unit", "What is verified", "Tests in"],
           ["scoring.HeuristicScorer", "Each of the nine rules adds its documented points; thresholds are strict (amount exactly ₹50,000 is not flagged); score cap at 1.0 and factors always sum to the score; benchmark rows skip rules", "test_scoring"],
           ["scoring.decide", "APPROVE / HOLD / DECLINE boundaries at 0.25 and 0.65", "test_scoring, BVA-25..30"],
           ["scoring.HybridScorer", "Noisy-OR combination with the model; fallback to rules without features or when no model is live", "test_scoring"],
           ["schemas.models validators", "Amount, token, country, currency, channel, PAN-like values, control characters, feature vector", "test_exp11_black_box, test_workflows"],
           ["geo.haversine_km, to_inr", "Distance between known cities, unknown city handling, fixed demo FX", "test_scoring, test_india_and_alerts"],
           ["integrity.row_hash + audit chain", "Hash chain verifies; edits and deletions are detected", "test_india_and_alerts"],
           ["core.security", "Argon2 hashes, token signing and expiry", "test_auth"],
           ["ml_service.ModelService", "Loads only verified artifacts inside the artifacts directory; refuses tampered or foreign files; prediction failure falls back to rules", "test_ml"]],
          [2300, 5326, 1400], size=19), SPACER(),
    H2("B. Integration testing"),
    P("Integration tests drive complete workflows through the API and check the database and audit trail afterwards, for example: submit a transaction → alert and cardholder message created → cardholder replies “not me” → card blocked → analyst verdict → audit chain still verifies. Other covered flows: duplicate and concurrent verdicts (exactly one succeeds), blocked card rejection, assignment rules for analysts and administrators, configuration changes applied to new transactions, user management and last-administrator protection, password and one-time-code sign-in (wrong, expired and reused codes), model deploy, retire, replay and tampered-artifact refusal, migration of a version-1 database in place, rollback when an audit write fails, database failure returning 503, and static-file path traversal."),
    TABLE(suite_rows, [3000, 4826, 1200], size=19, align_right={2}), SPACER(),
    H2("C. Black-box test design"),
    H3("Boundary value analysis"), TABLE(BVA, [1100, 2700, 3126, 2100], size=18), SPACER(),
    H3("Equivalence class partitioning"), TABLE(ECP, [1100, 1300, 4326, 2300], size=18), SPACER(),
    H3("Decision table for the three independent scoring rules"), TABLE(DT, [900, 1700, 2000, 1500, 1500, 1426], size=18), SPACER(),
    P("State-transition cases ST-1 to ST-4 confirm that an alert can be resolved exactly once: any second verdict, in any combination, returns a conflict (409). All cases above were executed by pytest and passed."),
    H2("D. Results"),
    TABLE([["Measure", "Result"],
           ["Back-end tests (pytest)", f"{n_tests} run, {R['backend']['failures']} failed, {R['backend']['skipped']} skipped"],
           ["Back-end statement coverage (pytest-cov)", f"{cov}% of {R['backend']['statements']} statements"],
           ["Front-end tests (Vitest)", f"{fe['tests']} run, {fe['failed']} failed"],
           ["TypeScript strict type check", "passed" if R["typecheck_ok"] else "failed"],
           ["Scoring latency, in-process", f"median {lat['p50']} ms, 95th percentile {lat['p95']} ms over {lat['n']} requests (excludes network)"],
           ["Size of the code base (non-blank lines)", f"{loc['python_app']:,} Python, {loc['frontend_src']:,} TypeScript/CSS, {loc['python_tests']:,} Python test lines"]], [3600, 5426], size=19), SPACER(),
    "FIG:fig_11_1_coverage.png:13.5", CAPTION("Fig. 11.1: Statement coverage by back-end module (measured by pytest-cov)"),
    P("Lowest-covered modules: " + "; ".join(f"{k} {v['percent']}%" for k, v in cov_files[:4]) + ". Statements not covered are mostly defensive branches (unreachable database errors, optional dependency fallbacks) and command-line paths that need a real terminal or mail server."),
    H2("E. Defects found by the tests during development"),
    BUL("The score explanation did not add up when the score was capped at 1.0 (factors summed to more than the score). Found by the persisted-explanation test; fixed by adding an explicit negative “score cap” factor."),
    BUL("A page crashed to a blank screen when the server returned data in an unexpected shape. Found by a front-end test; fixed with an error boundary that shows a recoverable message."),
    BUL("Two simultaneous verdicts on one alert could both appear to succeed. The concurrency test drives eight parallel requests; the review is now an atomic update so exactly one succeeds."),
    H2("Commands to reproduce"),
    P("python -m pytest --cov=app    |    cd frontend && npm test && npm run typecheck    |    python scripts/collect_results.py (records the figures above)", mono=True, size=19, align="left", line=None),
    H2("Limitations"),
    P("The suites do not include load testing, penetration testing, mutation testing, screen-reader accessibility checks or automated browser tests; the user interface was checked through component tests with a mocked API. The model’s quality is reported separately on the ML page (held-out test split), not by these functional tests."),
    RESULT("Unit tests, integration tests and black-box test cases (boundary value, equivalence class, decision table, state transition) were designed and executed with pytest and Vitest, and the measured results and coverage are recorded above."),
]

# ------------------------------------------------------------------ Experiment 12
EI = [("Submit transaction", "H", 6), ("Record analyst verdict", "A", 4), ("Assign or unassign alert", "L", 3), ("Update risk configuration", "A", 4), ("Block or unblock card", "L", 3),
      ("Create or update user, reset password", "A", 4), ("Sign in with password and one-time code", "A", 4), ("Cardholder reply (“Was this you?”)", "A", 4),
      ("Change own password", "L", 3), ("Deploy or retire model", "A", 4), ("Replay benchmark sample", "A", 4)]
EO = [("Score response with factors and decision", "A", 5), ("Overview and report with aggregates", "H", 7), ("Analyst productivity report", "A", 5), ("Transactions CSV export", "L", 4),
      ("Confirmed-label CSV export", "L", 4), ("Cardholder notification message", "A", 5), ("Audit integrity verification result", "A", 5)]
EQ = [("Transaction search and list", "A", 4), ("Transaction detail with history and audit trail", "H", 6), ("Alert queue", "A", 4), ("Cards list", "L", 3), ("Audit log list", "L", 3), ("Users list", "L", 3),
      ("Model registry and metrics", "A", 4), ("Rules and configuration view", "L", 3), ("Cardholder messages outbox", "L", 3), ("Reply-link information (public)", "L", 3), ("Health check", "L", 3)]
ILF = [("transactions (with scoring explanation)", "A", 10), ("customers", "L", 7), ("cards", "L", 7), ("merchants", "L", 7), ("fraud_alerts", "L", 7), ("ml_models", "L", 7), ("users (analysts)", "L", 7),
       ("notifications", "L", 7), ("audit log", "L", 7), ("config", "L", 7)]
EIF = [("ULB benchmark sample file (read-only reference data)", "L", 5)]
ufp = sum(x[2] for g in (EI, EO, EQ, ILF, EIF) for x in g)
GSC = [("Data communications", 4, "Browser to server over REST/JSON"), ("Distributed data processing", 1, "One process; training is offline"), ("Performance", 3, "Latency objective; in-process scoring"),
       ("Heavily used configuration", 2, "Runs on a laptop; no hardware constraint"), ("Transaction rate", 3, "Bursts expected, low sustained rate in the demo"), ("On-line data entry", 5, "All entry through the web interface or API"),
       ("End-user efficiency", 4, "Filters, URL state, confirmation dialogs"), ("On-line update", 4, "Verdicts, blocks and configuration update immediately"), ("Complex processing", 4, "Scoring, geography, ML, access control"),
       ("Reusability", 3, "Scorer interface and services are reusable"), ("Installation ease", 3, "Documented commands; no services to install"), ("Operational ease", 3, "Migrations, health check, audit verification"),
       ("Multiple sites", 1, "Single site"), ("Facilitate change", 4, "Modular layers, configurable thresholds, versioned schema")]
tdi = sum(g[1] for g in GSC)
vaf = round(0.65 + 0.01 * tdi, 2)
afp = round(ufp * vaf, 1)
PROD = 10.0
effort = round(afp / PROD, 1)
kloc = (loc["python_app"] + loc["frontend_src"]) / 1000
cocomo_e = round(2.4 * kloc ** 1.05, 1)
cocomo_t = round(2.5 * cocomo_e ** 0.38, 1)
W = {"EI": ("L 3", "A 4", "H 6"), "EO": ("L 4", "A 5", "H 7"), "EQ": ("L 3", "A 4", "H 6"), "ILF": ("L 7", "A 10", "H 15"), "EIF": ("L 5", "A 7", "H 10")}


def fp_table(name, items, label):
    rows = [[label, "Complexity", "FP"]] + [[a, {"L": "Low", "A": "Average", "H": "High"}[b], str(c)] for a, b, c in items] + [["**Subtotal**", "", f"**{sum(i[2] for i in items)}**"]]
    return TABLE(rows, [5600, 1800, 1626], size=19, align_right={2})


exp12 = [
    new_heading("Experiment 12: Effort Estimation using Function Point (FP) Analysis"),
    AIM("To estimate the size and effort of the Credit Card Fraud Detection System using Function Point analysis."),
    SOFT("Python script (docs/lab-file/build_lab_file.py) for the arithmetic; the same tables can be reproduced in a spreadsheet."),
    H2("Theory"),
    P("Function Point analysis measures the size of software from the functions it gives its users, independent of the programming language. Five kinds of function are counted: **external inputs (EI)** that bring data in or change data, **external outputs (EO)** that present derived or calculated data, **external inquiries (EQ)** that retrieve data without calculation, **internal logical files (ILF)** that the system maintains, and **external interface files (EIF)** that it only reads. Each function is rated Low, Average or High complexity and given a weight (EI 3/4/6, EO 4/5/7, EQ 3/4/6, ILF 7/10/15, EIF 5/7/10). The sum is the **unadjusted function points (UFP)**. Fourteen general system characteristics (GSC), each rated 0 to 5, give the total degree of influence TDI, the **value adjustment factor VAF = 0.65 + 0.01 × TDI**, and **AFP = UFP × VAF**. Effort follows from AFP and a productivity figure."),
    H2("Function count for the working system"),
    fp_table("EI", EI, "External inputs"), SPACER(), fp_table("EO", EO, "External outputs"), SPACER(), fp_table("EQ", EQ, "External inquiries"), SPACER(),
    fp_table("ILF", ILF, "Internal logical files"), SPACER(), fp_table("EIF", EIF, "External interface file"), SPACER(),
    TABLE([["Function type", "Count", "UFP"]] + [[n, str(len(g)), str(sum(x[2] for x in g))] for n, g in (("EI", EI), ("EO", EO), ("EQ", EQ), ("ILF", ILF), ("EIF", EIF))] + [["**Unadjusted function points (UFP)**", "", f"**{ufp}**"]],
          [5600, 1800, 1626], size=19, align_right={1, 2}), SPACER(),
    P("Complexity ratings are the team’s judgement from the number of data element types and files referenced by each function; they are assumptions, not measurements."),
    H2("General system characteristics"),
    TABLE([["No.", "Characteristic", "Rating (0 to 5)", "Reason"]] + [[str(i + 1), g[0], str(g[1]), g[2]] for i, g in enumerate(GSC)] + [["", "**Total degree of influence (TDI)**", f"**{tdi}**", ""]], [600, 3000, 1400, 4026], size=19), SPACER(),
    P(f"VAF = 0.65 + 0.01 × {tdi} = **{vaf}**.    AFP = {ufp} × {vaf} = **{afp} function points**."),
    H2("Effort estimate"),
    P(f"**Assumption:** a productivity of {PROD:g} function points per person-month (a commonly quoted planning figure for small business applications; replace it with your own team’s data if you have any). Effort = {afp} ÷ {PROD:g} = **{effort} person-months**. With a team of three working in parallel this is about {round(effort / 3, 1)} months before allowing for overlap, testing and documentation."),
    P(f"**Cross-check (not a replacement):** the implemented code has {loc['python_app'] + loc['frontend_src']:,} non-blank lines of application code ({kloc:.2f} KLOC). Basic COCOMO, organic mode, gives effort = 2.4 × KLOC^1.05 = **{cocomo_e} person-months** and development time = 2.5 × effort^0.38 = **{cocomo_t} months**. Function points count what the design specifies; COCOMO counts what was written, so the two are expected to differ."),
    P("Limits of this estimate: it is a size and effort estimate made from the finished design for a classroom project, not a bid. It excludes documentation effort, learning time and rework, and the productivity figure is assumed."),
    RESULT(f"The system was sized at {ufp} unadjusted function points ({afp} adjusted, VAF {vaf}), giving an estimated effort of {effort} person-months at the assumed productivity of {PROD:g} FP per person-month."),
]

# ------------------------------------------------------------------ Experiment 13
act_rows = [["ID", "Activity", "Pred.", "O", "M", "P", "TE", "SD", "ES", "EF", "LS", "LF", "Slack"]]
for i in ORDER:
    a = ACTS[i]
    act_rows.append([a["id"], a["name"], ",".join(a["pred"]) or "-", f'{a["o"]:g}', f'{a["m"]:g}', f'{a["p"]:g}', str(a["te"]), str(a["sd"]), str(a["es"]), str(a["ef"]), str(a["ls"]), str(a["lf"]), str(a["slack"])])
z = (16 - END) / SD
prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))
exp13 = [
    new_heading("Experiment 13: Time Line Chart: Gantt Chart and PERT Chart"),
    AIM("To prepare a time line (Gantt) chart and a PERT chart for the Credit Card Fraud Detection System project."),
    SOFT("Python with Graphviz and Matplotlib (docs/lab-file/diagrams.py); the same network can be drawn in MS Project or any planning tool."),
    H2("Theory"),
    P("A **Gantt chart** shows each activity as a bar on a calendar, so start, duration and overlap are visible. **PERT** (Program Evaluation and Review Technique) draws activities as a network with dependencies and uses three duration estimates: optimistic O, most likely M and pessimistic P. The expected time is **TE = (O + 4M + P) / 6** and the standard deviation **SD = (P − O) / 6**. A forward pass gives each activity’s earliest start (ES) and finish (EF); a backward pass from the project end gives the latest start (LS) and finish (LF). **Slack = LS − ES**. Activities with zero slack form the **critical path**, which fixes the project duration (**CPM**). The SD of the path is the square root of the sum of the variances of its activities."),
    H2("Activities and estimates"),
    P("Durations are in weeks. The schedule is a planning baseline for the project; week 1 is the project start date and should be mapped to your semester calendar.", keep=True),
    TABLE(act_rows, [450, 2650, 650, 380, 380, 380, 520, 520, 520, 520, 520, 520, 520], size=15, align_right=set(range(3, 13))), SPACER(),
    H2("Gantt chart"),
    "FIG:fig_13_1_gantt.png:15.5", CAPTION("Fig. 13.1: Gantt chart (earliest-start schedule; critical activities in red)"),
    H2("PERT network"),
    "FIG:fig_13_2_pert.png:15.0", CAPTION("Fig. 13.2: PERT network with ES, EF, LS, LF and slack (critical path in red)"),
    H2("Analysis"),
    P(f"**Critical path:** {' → '.join(CRIT)}. **Expected project duration:** {END:.2f} weeks. **Standard deviation of the path:** {SD} weeks. Using the normal approximation, the probability of finishing within 16 weeks is about {prob * 100:.0f}% (z = {z:.2f}). Activities with the most slack (for example the Gantt/PERT charts, A6 and the ML pipeline) can absorb delay without moving the end date; any delay in backend, frontend, integration testing, estimation or the final compilation delays the whole project."),
    RESULT(f"The Gantt and PERT charts were prepared; the critical path is {' → '.join(CRIT)} with an expected duration of {END:.2f} weeks."),
]

# ------------------------------------------------------------------ appendix
appendix = [
    new_heading("Appendix A: Running the Working Demonstrator"),
    P("**Prerequisites:** Python 3.11 or newer and Node.js 20 or newer. No database server, Docker or Redis.", after=80),
    P("pip install -r requirements.txt  |  cd frontend && npm install && npm run build  |  python -m app.cli create-user --email you@example.com --name \"Your Name\" --role admin  |  uvicorn app.main:app --host 127.0.0.1 --port 8000", mono=True, size=19, align="left", line=None),
    P("Open http://127.0.0.1:8000. Set FRAUD_LOGIN_OTP=true to require an e-mail code at sign-in (printed in the server terminal in development, or sent by SMTP when FRAUD_OTP_DELIVERY=smtp is configured). Set FRAUD_AUTH_REQUIRED=false for a no-login demo on a machine only you use. The model is trained with python -m ml.train --csv data/creditcard.csv (the dataset is not distributed with the project; download it from Kaggle).", after=80),
    P("**Suggested demonstration path:** Overview → Alerts and cases → open a held transaction (score factors, cardholder, history) → assign to yourself → Cardholder messages → open the reply link and answer “not me” → return to the alert and record a verdict → Cards (blocked token) → Audit log → Verify integrity → ML model → Replay 25 rows → Reports."),
    P("**Honest limits to state during the viva:** synthetic data only; the model was trained on a 2013 European dataset and applies to benchmark-feature transactions; notifications are simulated; SQLite instead of PostgreSQL; no TLS; not a payment system and not PCI DSS certified."),
]

add(exp11 + exp12 + exp13 + appendix)
out = HERE / "SE_Lab_File_Credit_Card_Fraud_Detection_updated.docx"
doc.save(str(out))
print("saved", out.name, "| UFP", ufp, "VAF", vaf, "AFP", afp, "effort", effort, "| COCOMO", cocomo_e, cocomo_t)
