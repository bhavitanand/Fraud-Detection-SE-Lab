"""Ordered, append-only schema migrations tracked in schema_version."""
from __future__ import annotations

import sqlite3

from .session import transaction

MIGRATIONS: list[tuple[int, str, list[str]]] = [
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
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_version(version, description) VALUES(?,?)", (version, description))
    return current_version(conn)
