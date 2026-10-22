"""All SQL lives here. Functions take an open connection; transaction control stays in services."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from app.core.integrity import GENESIS, row_hash

# ---------- transactions ----------
SORTABLE = {"id": "id", "created": "created", "amount": "amount", "score": "score", "decision": "decision", "token": "token", "merchant": "merchant"}


def tx_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["reasons"] = json.loads(d["reasons"] or "[]")
    d["factors"] = json.loads(d["factors"] or "[]")
    d["has_alert"] = d["decision"] != "APPROVE"
    d.pop("benchmark_label", None)  # ground truth of benchmark rows is never shown to analysts
    return d


def insert_transaction(c: sqlite3.Connection, **v: Any) -> int:
    cols = ("token", "card_id", "amount", "currency", "merchant", "merchant_id", "country", "location", "channel", "created", "score", "decision",
            "reasons", "factors", "scorer", "model_id", "source", "benchmark_label")
    row = {k: v.get(k) for k in cols}
    row["reasons"], row["factors"] = json.dumps(v["reasons"]), json.dumps(v["factors"])
    cur = c.execute(f"INSERT INTO transactions({','.join(cols)}) VALUES({','.join(':' + k for k in cols)})", row)
    return cur.lastrowid


def create_alert(c: sqlite3.Connection, txn_id: int, score: float, created_at: str) -> int:
    return c.execute("INSERT INTO fraud_alerts(txn_id,risk_score,created_at) VALUES(?,?,?)", (txn_id, score, created_at)).lastrowid


def get_transaction(c: sqlite3.Connection, tx_id: int) -> dict | None:
    return tx_row(c.execute("SELECT * FROM v_transactions WHERE id=?", (tx_id,)).fetchone())


def _like(q: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", q) + "%"


def list_transactions(c: sqlite3.Connection, *, q=None, decision=None, review=None, channel=None, country=None, source=None,
                      min_score=None, max_score=None, alerts_only=False, sort="id", order="desc", page=1, page_size=25,
                      date_from=None, date_to=None, assigned_to=None) -> tuple[list[dict], int]:
    where, args = [], []
    if q:
        where.append("(token LIKE ? ESCAPE '\\' OR merchant LIKE ? ESCAPE '\\' OR CAST(id AS TEXT)=?)")
        args += [_like(q), _like(q), q.lstrip("#")]
    for col, val in (("decision", decision), ("review", review), ("channel", channel), ("country", country), ("source", source)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if assigned_to == "unassigned":
        where.append("assigned_to IS NULL")
    elif assigned_to:
        where.append("assigned_to=?"); args.append(assigned_to)
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
    total = c.execute(f"SELECT count(*) FROM v_transactions {clause}", args).fetchone()[0]
    rows = c.execute(f"SELECT * FROM v_transactions {clause} ORDER BY {col} {direction}, id DESC LIMIT ? OFFSET ?",
                     [*args, page_size, (page - 1) * page_size]).fetchall()
    return [tx_row(r) for r in rows], total


def count_recent(c: sqlite3.Connection, token: str, since_iso: str) -> int:
    return c.execute("SELECT count(*) FROM transactions WHERE token=? AND created>?", (token, since_iso)).fetchone()[0]


def token_history(c: sqlite3.Connection, token: str, exclude_id: int, limit: int = 10) -> list[dict]:
    rows = c.execute("SELECT * FROM v_transactions WHERE token=? AND id!=? ORDER BY created DESC, id DESC LIMIT ?", (token, exclude_id, limit)).fetchall()
    return [tx_row(r) for r in rows]


def card_history_stats(c: sqlite3.Connection, card_id: int, currency: str) -> dict:
    """Behavioural baseline of a card, in one currency, over everything recorded before 'now'."""
    n, avg = c.execute("SELECT count(*), COALESCE(AVG(amount),0) FROM transactions WHERE card_id=? AND currency=?", (card_id, currency)).fetchone()
    countries = {r[0] for r in c.execute("SELECT DISTINCT country FROM transactions WHERE card_id=?", (card_id,))}
    merchants = {r[0] for r in c.execute("SELECT DISTINCT merchant_id FROM transactions WHERE card_id=? AND merchant_id IS NOT NULL", (card_id,))}
    last = c.execute("SELECT created, location FROM transactions WHERE card_id=? ORDER BY created DESC, id DESC LIMIT 1", (card_id,)).fetchone()
    return {"count": n, "avg_amount": avg, "countries": countries, "merchants": merchants, "last": dict(last) if last else None}


def mark_reviewed(c: sqlite3.Connection, tx_id: int, verdict: str, by: str, note: str | None, at: str) -> bool:
    cur = c.execute("UPDATE fraud_alerts SET status=?, resolved_by=?, resolved_at=?, resolution_note=? WHERE txn_id=? AND status='OPEN'", (verdict, by, at, note, tx_id))
    return cur.rowcount == 1


def assign_alert(c: sqlite3.Connection, tx_id: int, assignee: str | None) -> bool:
    return c.execute("UPDATE fraud_alerts SET assigned_to=? WHERE txn_id=? AND status='OPEN'", (assignee, tx_id)).rowcount == 1


def record_cardholder_response(c: sqlite3.Connection, tx_id: int, response: str, at: str) -> bool:
    return c.execute("UPDATE fraud_alerts SET cardholder_response=?, cardholder_responded_at=? WHERE txn_id=? AND cardholder_response IS NULL", (response, at, tx_id)).rowcount == 1


# ---------- customers / merchants ----------
def insert_customer(c: sqlite3.Connection, name: str, email: str | None, phone: str | None, city: str | None, state: str | None, created: str, home_country: str = "IN") -> int:
    return c.execute("INSERT INTO customers(name,email,phone,city,state,home_country,created) VALUES(?,?,?,?,?,?,?)", (name, email, phone, city, state, home_country, created)).lastrowid


def get_customer(c: sqlite3.Connection, customer_id: int | None) -> dict | None:
    if customer_id is None:
        return None
    r = c.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    return dict(r) if r else None


def get_merchant(c: sqlite3.Connection, merchant_id: int | None) -> dict | None:
    if merchant_id is None:
        return None
    r = c.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,)).fetchone()
    return dict(r) if r else None


def find_or_create_merchant(c: sqlite3.Connection, name: str) -> int:
    r = c.execute("SELECT id FROM merchants WHERE name=?", (name,)).fetchone()
    if r:
        return r["id"]
    return c.execute("INSERT INTO merchants(name) VALUES(?)", (name,)).lastrowid


def insert_merchant(c: sqlite3.Connection, name: str, code: str, label: str, city: str, risk: str) -> int:
    return c.execute("INSERT INTO merchants(name,category_code,category_label,city,risk_level) VALUES(?,?,?,?,?)", (name, code, label, city, risk)).lastrowid


# ---------- cards ----------
_CARD_COLS = "card_id,token,customer_id,card_network,issuer,card_type,expiry_date,credit_limit,blocked,blocked_at,block_reason,blocked_by"


def ensure_card(c: sqlite3.Connection, token: str) -> int:
    c.execute("INSERT OR IGNORE INTO cards(token,blocked) VALUES(?,0)", (token,))
    return c.execute("SELECT card_id FROM cards WHERE token=?", (token,)).fetchone()[0]


def insert_card(c: sqlite3.Connection, token: str, customer_id: int, network: str, issuer: str, card_type: str, expiry: str, limit: float) -> int:
    return c.execute("INSERT INTO cards(token,customer_id,card_network,issuer,card_type,expiry_date,credit_limit) VALUES(?,?,?,?,?,?,?)",
                     (token, customer_id, network, issuer, card_type, expiry, limit)).lastrowid


def get_card(c: sqlite3.Connection, token: str) -> dict | None:
    r = c.execute(f"SELECT {_CARD_COLS} FROM cards WHERE token=?", (token,)).fetchone()
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
        where.append("(c.token LIKE ? ESCAPE '\\' OR cu.name LIKE ? ESCAPE '\\')"); args += [_like(q), _like(q)]
    if blocked is not None:
        where.append("c.blocked=?"); args.append(int(blocked))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = c.execute(f"""SELECT c.card_id,c.token,c.card_network,c.issuer,c.card_type,c.credit_limit,c.blocked,c.blocked_at,c.block_reason,c.blocked_by,
        cu.name customer_name, cu.city customer_city, COUNT(t.id) tx_count, COALESCE(SUM(t.decision!='APPROVE'),0) alert_count, MAX(t.created) last_seen
        FROM cards c LEFT JOIN customers cu ON cu.id=c.customer_id LEFT JOIN transactions t ON t.card_id=c.card_id {clause}
        GROUP BY c.card_id ORDER BY c.token LIMIT ?""", [*args, limit]).fetchall()
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
_REDACT = {"password", "secret", "authorization", "cvv", "pan", "token_secret", "otp", "code"}


def insert_audit(c: sqlite3.Connection, at: str, actor: str, action: str, detail: dict, target: str | None) -> None:
    """Must run inside a write transaction: the chain head is read and extended atomically."""
    safe = {k: ("[redacted]" if k.lower() in _REDACT else v) for k, v in detail.items()}
    text = json.dumps(safe, sort_keys=True)
    head = c.execute("SELECT row_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = head["row_hash"] if head and head["row_hash"] else GENESIS
    c.execute("INSERT INTO audit(at,actor,action,detail,target,prev_hash,row_hash) VALUES(?,?,?,?,?,?,?)",
              (at, actor, action, text, target, prev, row_hash(prev, at, actor, action, text, target)))


def verify_audit_chain(c: sqlite3.Connection) -> dict:
    prev, n = GENESIS, 0
    for r in c.execute("SELECT id,at,actor,action,detail,target,prev_hash,row_hash FROM audit ORDER BY id"):
        n += 1
        if r["prev_hash"] != prev or r["row_hash"] != row_hash(prev, r["at"], r["actor"], r["action"], r["detail"], r["target"]):
            return {"ok": False, "checked": n, "first_broken_id": r["id"], "head": prev}
        prev = r["row_hash"]
    return {"ok": True, "checked": n, "first_broken_id": None, "head": prev}


def _audit_row(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in ("id", "at", "actor", "action", "target")}
    d["detail"] = json.loads(r["detail"]) if r["detail"] else {}
    d["hash"] = (r["row_hash"] or "")[:12]
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


# ---------- users (the "Analyst" entity of the ER diagram; login id is the e-mail address) ----------
def get_user(c: sqlite3.Connection, username: str) -> dict | None:
    r = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    return dict(r) if r else None


def insert_user(c: sqlite3.Connection, username: str, pw_hash: str, role: str, created: str, name: str | None = None) -> None:
    c.execute("INSERT INTO users(username,password_hash,role,created,name) VALUES(?,?,?,?,?)", (username, pw_hash, role, created, name))


def list_users(c: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT username,name,role,created,disabled FROM users ORDER BY username")]


def update_user(c: sqlite3.Connection, username: str, **fields: Any) -> bool:
    allowed = {"role", "disabled", "name", "password_hash"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    return c.execute(f"UPDATE users SET {', '.join(k + '=?' for k in sets)} WHERE username=?", [*sets.values(), username]).rowcount == 1


def count_active_admins(c: sqlite3.Connection) -> int:
    return c.execute("SELECT count(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0]


# ---------- OTP ----------
def insert_otp(c: sqlite3.Connection, email: str, code_hash: str, created: str, expires: str) -> int:
    return c.execute("INSERT INTO otp_challenges(email,code_hash,created,expires_at) VALUES(?,?,?,?)", (email, code_hash, created, expires)).lastrowid


def get_otp(c: sqlite3.Connection, otp_id: int) -> dict | None:
    r = c.execute("SELECT * FROM otp_challenges WHERE id=?", (otp_id,)).fetchone()
    return dict(r) if r else None


def bump_otp_attempts(c: sqlite3.Connection, otp_id: int) -> None:
    c.execute("UPDATE otp_challenges SET attempts=attempts+1 WHERE id=?", (otp_id,))


def use_otp(c: sqlite3.Connection, otp_id: int) -> bool:
    return c.execute("UPDATE otp_challenges SET used=1 WHERE id=? AND used=0", (otp_id,)).rowcount == 1


# ---------- notifications (simulated outbox) ----------
def insert_notification(c: sqlite3.Connection, **v: Any) -> int:
    cols = ("created", "channel", "recipient", "subject", "body", "kind", "txn_id", "reply_token_hash", "expires_at")
    return c.execute(f"INSERT INTO notifications({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [v.get(k) for k in cols]).lastrowid


def get_notification_by_hash(c: sqlite3.Connection, token_hash: str) -> dict | None:
    r = c.execute("SELECT * FROM notifications WHERE reply_token_hash=?", (token_hash,)).fetchone()
    return dict(r) if r else None


def mark_notification_replied(c: sqlite3.Connection, nid: int, reply: str, at: str) -> bool:
    return c.execute("UPDATE notifications SET reply=?, replied_at=? WHERE id=? AND reply IS NULL", (reply, at, nid)).rowcount == 1


def list_notifications(c: sqlite3.Connection, limit: int, offset: int) -> tuple[list[dict], int]:
    total = c.execute("SELECT count(*) FROM notifications").fetchone()[0]
    rows = c.execute("SELECT id,created,channel,recipient,subject,body,kind,txn_id,expires_at,replied_at,reply FROM notifications ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [dict(r) for r in rows], total


# ---------- ML model registry ----------
def insert_model(c: sqlite3.Connection, **v: Any) -> int:
    cols = ("name", "version", "algorithm", "artifact_file", "artifact_sha256", "pr_auc", "precision_score", "recall_score", "f1_score", "metrics_json", "status", "trained_at", "registered_at")
    return c.execute(f"INSERT INTO ml_models({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [v.get(k) for k in cols]).lastrowid


def get_model(c: sqlite3.Connection, model_id: int) -> dict | None:
    r = c.execute("SELECT * FROM ml_models WHERE model_id=?", (model_id,)).fetchone()
    return _model_row(r)


def _model_row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
    return d


def list_models(c: sqlite3.Connection) -> list[dict]:
    return [_model_row(r) for r in c.execute("SELECT * FROM ml_models ORDER BY model_id DESC")]


def active_model(c: sqlite3.Connection) -> dict | None:
    return _model_row(c.execute("SELECT * FROM ml_models WHERE status='active' ORDER BY model_id DESC LIMIT 1").fetchone())


def set_model_status(c: sqlite3.Connection, model_id: int, status: str) -> None:
    c.execute("UPDATE ml_models SET status=? WHERE model_id=?", (status, model_id))
