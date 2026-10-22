"""Ordered, append-only schema migrations tracked in schema_version."""
from __future__ import annotations

import sqlite3

from app.core.integrity import GENESIS, row_hash

from .session import transaction

MIGRATIONS: list[tuple[int, str, list]] = [
    (1, "baseline (original single-file schema)", [
        "CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, token TEXT NOT NULL, amount REAL NOT NULL,
           merchant TEXT NOT NULL, country TEXT NOT NULL, channel TEXT NOT NULL, created TEXT NOT NULL, score REAL NOT NULL,
           decision TEXT NOT NULL, reasons TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'OPEN')""",
        "CREATE TABLE IF NOT EXISTS cards(token TEXT PRIMARY KEY, blocked INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL)",
    ]),
    (2, "factors, provenance, review metadata, users, indexes", [
        "ALTER TABLE transactions ADD COLUMN factors TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE transactions ADD COLUMN scorer TEXT NOT NULL DEFAULT 'heuristic-v1'",
        "ALTER TABLE transactions ADD COLUMN source TEXT NOT NULL DEFAULT 'LIVE'",
        "ALTER TABLE transactions ADD COLUMN reviewed_at TEXT",
        "ALTER TABLE transactions ADD COLUMN reviewed_by TEXT",
        "ALTER TABLE transactions ADD COLUMN review_note TEXT",
        "ALTER TABLE cards ADD COLUMN blocked_at TEXT",
        "ALTER TABLE cards ADD COLUMN block_reason TEXT",
        "ALTER TABLE cards ADD COLUMN blocked_by TEXT",
        "ALTER TABLE audit ADD COLUMN target TEXT",
        # Legacy approvals carried review='OPEN' although no alert exists.
        "UPDATE transactions SET review='NOT_REQUIRED' WHERE decision='APPROVE' AND review='OPEN'",
        # The three rows the original app seeded are identifiable; everything else is left as LIVE.
        """UPDATE transactions SET source='SEED' WHERE (token,merchant) IN
           (('SYNTH-1042','Corner Cafe'),('SYNTH-2088','Demo Electronics'),('SYNTH-3091','Demo Travel'))""",
        """CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
           role TEXT NOT NULL CHECK(role IN ('analyst','admin')), created TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0)""",
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS ix_tx_token_created ON transactions(token, created)",
        "CREATE INDEX IF NOT EXISTS ix_tx_decision_review ON transactions(decision, review)",
        "CREATE INDEX IF NOT EXISTS ix_tx_created ON transactions(created)",
        "CREATE INDEX IF NOT EXISTS ix_audit_target ON audit(target)",
    ]),
]


def _backfill_audit_chain(conn: sqlite3.Connection) -> None:
    prev = GENESIS
    for r in conn.execute("SELECT id,at,actor,action,detail,target FROM audit ORDER BY id").fetchall():
        h = row_hash(prev, r["at"], r["actor"], r["action"], r["detail"], r["target"])
        conn.execute("UPDATE audit SET prev_hash=?, row_hash=? WHERE id=?", (prev, h, r["id"]))
        prev = h


MIGRATIONS.append((3, "Indian domain model: customers, merchants, cards, alerts, models, notifications, OTP, audit hash chain", [
    "CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, phone TEXT, city TEXT, state TEXT, home_country TEXT NOT NULL DEFAULT 'IN', created TEXT NOT NULL)",
    """CREATE TABLE merchants(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, category_code TEXT, category_label TEXT,
       city TEXT, country TEXT NOT NULL DEFAULT 'IN', risk_level TEXT NOT NULL DEFAULT 'MEDIUM' CHECK(risk_level IN ('LOW','MEDIUM','HIGH')))""",
    """CREATE TABLE ml_models(model_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, version TEXT NOT NULL, algorithm TEXT NOT NULL,
       artifact_file TEXT NOT NULL, artifact_sha256 TEXT NOT NULL UNIQUE, pr_auc REAL, precision_score REAL, recall_score REAL, f1_score REAL,
       metrics_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN ('candidate','active','retired')),
       trained_at TEXT NOT NULL, registered_at TEXT NOT NULL)""",
    """CREATE TABLE cards_new(card_id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, customer_id INTEGER REFERENCES customers(id),
       card_network TEXT, issuer TEXT, card_type TEXT NOT NULL DEFAULT 'CREDIT', expiry_date TEXT, credit_limit REAL,
       blocked INTEGER NOT NULL DEFAULT 0, blocked_at TEXT, block_reason TEXT, blocked_by TEXT)""",
    "INSERT INTO cards_new(token,blocked,blocked_at,block_reason,blocked_by) SELECT token,blocked,blocked_at,block_reason,blocked_by FROM cards",
    "DROP TABLE cards",
    "ALTER TABLE cards_new RENAME TO cards",
    "ALTER TABLE users ADD COLUMN name TEXT",
    "ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'",
    "ALTER TABLE transactions ADD COLUMN location TEXT",
    "ALTER TABLE transactions ADD COLUMN merchant_id INTEGER REFERENCES merchants(id)",
    "ALTER TABLE transactions ADD COLUMN model_id INTEGER REFERENCES ml_models(model_id)",
    "ALTER TABLE transactions ADD COLUMN card_id INTEGER REFERENCES cards(card_id)",
    "ALTER TABLE transactions ADD COLUMN benchmark_label INTEGER",
    "UPDATE transactions SET card_id=(SELECT card_id FROM cards c WHERE c.token=transactions.token)",
    """CREATE TABLE fraud_alerts(alert_id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
       assigned_to TEXT REFERENCES users(username), risk_score REAL NOT NULL,
       status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CONFIRMED_FRAUD','FALSE_POSITIVE')),
       resolution_note TEXT, created_at TEXT NOT NULL, resolved_at TEXT, resolved_by TEXT,
       cardholder_response TEXT CHECK(cardholder_response IN ('LEGIT','NOT_ME')), cardholder_responded_at TEXT)""",
    """INSERT INTO fraud_alerts(txn_id,risk_score,status,resolution_note,created_at,resolved_at,resolved_by)
       SELECT id,score,review,review_note,created,reviewed_at,reviewed_by FROM transactions WHERE decision!='APPROVE'""",
    "DROP INDEX IF EXISTS ix_tx_decision_review",
    "ALTER TABLE transactions DROP COLUMN review",
    "ALTER TABLE transactions DROP COLUMN reviewed_at",
    "ALTER TABLE transactions DROP COLUMN reviewed_by",
    "ALTER TABLE transactions DROP COLUMN review_note",
    "CREATE INDEX ix_tx_decision ON transactions(decision)",
    "CREATE INDEX ix_tx_card ON transactions(card_id, created)",
    "CREATE INDEX ix_alert_status ON fraud_alerts(status, assigned_to)",
    """CREATE TABLE notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('EMAIL','SMS')),
       recipient TEXT NOT NULL, subject TEXT, body TEXT NOT NULL, kind TEXT NOT NULL, txn_id INTEGER REFERENCES transactions(id),
       reply_token_hash TEXT UNIQUE, expires_at TEXT, replied_at TEXT, reply TEXT)""",
    """CREATE TABLE otp_challenges(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, code_hash TEXT NOT NULL, created TEXT NOT NULL,
       expires_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0)""",
    "ALTER TABLE audit ADD COLUMN prev_hash TEXT",
    "ALTER TABLE audit ADD COLUMN row_hash TEXT",
    _backfill_audit_chain,
    """CREATE VIEW v_transactions AS SELECT t.*, CASE WHEN a.alert_id IS NULL THEN 'NOT_REQUIRED' ELSE a.status END AS review,
       a.alert_id AS alert_id, a.assigned_to AS assigned_to, a.resolved_at AS reviewed_at, a.resolved_by AS reviewed_by,
       a.resolution_note AS review_note, a.cardholder_response AS cardholder_response
       FROM transactions t LEFT JOIN fraud_alerts a ON a.txn_id=t.id""",
    "CREATE VIEW analysts AS SELECT rowid AS analyst_id, COALESCE(name, username) AS name, username AS email, role FROM users",
]))
LATEST = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    return 0 if not row else (conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    for version, description, statements in MIGRATIONS:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM schema_version WHERE version=?", (version,)).fetchone():
                continue  # re-checked under the write lock so concurrent starters don't double-apply
            for stmt in statements:
                conn.execute(stmt) if isinstance(stmt, str) else stmt(conn)
            conn.execute("INSERT INTO schema_version(version, description) VALUES(?,?)", (version, description))
    return current_version(conn)
