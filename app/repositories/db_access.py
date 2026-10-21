"""All SQL lives here. Functions take an open connection; transaction control stays in services."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

# ---------- transactions ----------
SORTABLE = {"id": "id", "created": "created", "amount": "amount", "score": "score", "decision": "decision", "token": "token", "merchant": "merchant"}


def tx_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["reasons"] = json.loads(d["reasons"] or "[]")
    d["factors"] = json.loads(d["factors"] or "[]")
    d["has_alert"] = d["decision"] != "APPROVE"
    return d


def insert_transaction(c: sqlite3.Connection, **v: Any) -> int:
    cur = c.execute(
        """INSERT INTO transactions(token,amount,merchant,country,channel,created,score,decision,reasons,factors,scorer,source,review)
           VALUES(:token,:amount,:merchant,:country,:channel,:created,:score,:decision,:reasons,:factors,:scorer,:source,:review)""",
        {**v, "reasons": json.dumps(v["reasons"]), "factors": json.dumps(v["factors"])},
    )
    return cur.lastrowid


def get_transaction(c: sqlite3.Connection, tx_id: int) -> dict | None:
    return tx_row(c.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone())


def _like(q: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", q) + "%"


def list_transactions(c: sqlite3.Connection, *, q=None, decision=None, review=None, channel=None, country=None, source=None,
                      min_score=None, max_score=None, alerts_only=False, sort="id", order="desc", page=1, page_size=25,
                      date_from=None, date_to=None) -> tuple[list[dict], int]:
    where, args = [], []
    if q:
        where.append("(token LIKE ? ESCAPE '\\' OR merchant LIKE ? ESCAPE '\\' OR CAST(id AS TEXT)=?)")
        args += [_like(q), _like(q), q.lstrip("#")]
    for col, val in (("decision", decision), ("review", review), ("channel", channel), ("country", country), ("source", source)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if min_score is not None:
        where.append("score>=?"); args.append(min_score)
    if max_score is not None:
        where.append("score<=?"); args.append(max_score)
    if alerts_only:
        where.append("decision!='APPROVE'")
    if date_from:
        where.append("substr(created,1,10)>=?"); args.append(date_from)
    if date_to:
        where.append("substr(created,1,10)<=?"); args.append(date_to)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    col = SORTABLE[sort]
    direction = "ASC" if order == "asc" else "DESC"
    total = c.execute(f"SELECT count(*) FROM transactions {clause}", args).fetchone()[0]
    rows = c.execute(f"SELECT * FROM transactions {clause} ORDER BY {col} {direction}, id DESC LIMIT ? OFFSET ?",
                     [*args, page_size, (page - 1) * page_size]).fetchall()
    return [tx_row(r) for r in rows], total


def count_recent(c: sqlite3.Connection, token: str, since_iso: str) -> int:
    return c.execute("SELECT count(*) FROM transactions WHERE token=? AND created>?", (token, since_iso)).fetchone()[0]


def token_history(c: sqlite3.Connection, token: str, exclude_id: int, limit: int = 10) -> list[dict]:
    rows = c.execute("SELECT * FROM transactions WHERE token=? AND id!=? ORDER BY created DESC, id DESC LIMIT ?", (token, exclude_id, limit)).fetchall()
    return [tx_row(r) for r in rows]


def mark_reviewed(c: sqlite3.Connection, tx_id: int, verdict: str, by: str, note: str | None, at: str) -> bool:
    cur = c.execute("UPDATE transactions SET review=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=? AND review='OPEN'",
                    (verdict, by, at, note, tx_id))
    return cur.rowcount == 1


# ---------- cards ----------
def ensure_card(c: sqlite3.Connection, token: str) -> None:
    c.execute("INSERT OR IGNORE INTO cards(token,blocked) VALUES(?,0)", (token,))


def get_card(c: sqlite3.Connection, token: str) -> dict | None:
    r = c.execute("SELECT token,blocked,blocked_at,block_reason,blocked_by FROM cards WHERE token=?", (token,)).fetchone()
    return None if r is None else {**dict(r), "blocked": bool(r["blocked"])}


def set_card_blocked(c: sqlite3.Connection, token: str, blocked: bool, by: str, reason: str | None, at: str) -> bool:
    """Returns True when the state actually changed."""
    ensure_card(c, token)
    if blocked:
        cur = c.execute("UPDATE cards SET blocked=1,blocked_at=?,block_reason=?,blocked_by=? WHERE token=? AND blocked=0", (at, reason, by, token))
    else:
        cur = c.execute("UPDATE cards SET blocked=0,blocked_at=NULL,block_reason=NULL,blocked_by=NULL WHERE token=? AND blocked=1", (token,))
    return cur.rowcount == 1


def list_cards(c: sqlite3.Connection, q: str | None = None, blocked: bool | None = None, limit: int = 500) -> list[dict]:
    where, args = [], []
    if q:
        where.append("c.token LIKE ? ESCAPE '\\'"); args.append(_like(q))
    if blocked is not None:
        where.append("c.blocked=?"); args.append(int(blocked))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = c.execute(f"""SELECT c.token,c.blocked,c.blocked_at,c.block_reason,c.blocked_by,COUNT(t.id) tx_count,
        COALESCE(SUM(t.decision!='APPROVE'),0) alert_count, MAX(t.created) last_seen
        FROM cards c LEFT JOIN transactions t ON t.token=c.token {clause} GROUP BY c.token ORDER BY c.token LIMIT ?""", [*args, limit]).fetchall()
    return [{**dict(r), "blocked": bool(r["blocked"])} for r in rows]


# ---------- config / meta ----------
def get_config_rows(c: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM config")}


def set_config(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute("INSERT INTO config VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(c: sqlite3.Connection, key: str) -> str | None:
    r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------- audit ----------
_REDACT = {"password", "secret", "authorization", "cvv", "pan", "token_secret"}


def insert_audit(c: sqlite3.Connection, at: str, actor: str, action: str, detail: dict, target: str | None) -> None:
    safe = {k: ("[redacted]" if k.lower() in _REDACT else v) for k, v in detail.items()}
    c.execute("INSERT INTO audit(at,actor,action,detail,target) VALUES(?,?,?,?,?)", (at, actor, action, json.dumps(safe), target))


def _audit_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
    return d


def list_audit(c: sqlite3.Connection, *, action=None, actor=None, q=None, limit=50, offset=0) -> tuple[list[dict], int]:
    where, args = [], []
    if action:
        where.append("action=?"); args.append(action)
    if actor:
        where.append("actor=?"); args.append(actor)
    if q:
        where.append("(detail LIKE ? ESCAPE '\\' OR COALESCE(target,'') LIKE ? ESCAPE '\\')"); args += [_like(q), _like(q)]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT count(*) FROM audit {clause}", args).fetchone()[0]
    rows = c.execute(f"SELECT * FROM audit {clause} ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return [_audit_row(r) for r in rows], total


def audit_for_targets(c: sqlite3.Connection, targets: list[str]) -> list[dict]:
    marks = ",".join("?" * len(targets))
    return [_audit_row(r) for r in c.execute(f"SELECT * FROM audit WHERE target IN ({marks}) ORDER BY id DESC LIMIT 50", targets)]


def audit_actions(c: sqlite3.Connection) -> list[str]:
    return [r[0] for r in c.execute("SELECT DISTINCT action FROM audit ORDER BY action")]


# ---------- users ----------
def get_user(c: sqlite3.Connection, username: str) -> dict | None:
    r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(r) if r else None


def insert_user(c: sqlite3.Connection, username: str, pw_hash: str, role: str, created: str) -> None:
    c.execute("INSERT INTO users(username,password_hash,role,created) VALUES(?,?,?,?)", (username, pw_hash, role, created))
