"""Autopilot: the rules that let the system act on obvious cases without a human.

Policy (all steps are audited with actor "autopilot"):
  1. A DECLINE with score >= auto_block_score  -> the card is blocked at once (temporary, reversible).
  2. The cardholder answers the alert:
       NOT_ME -> alert closed as CONFIRMED_FRAUD, block kept
       LEGIT  -> alert closed as FALSE_POSITIVE, and the card is unblocked if autopilot was the one that blocked it
  3. No answer -> the alert stays OPEN for a human analyst. Only grey cases reach the queue.
Disabled by default; switch it on in Live mode or with config key autopilot_enabled=1.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.errors import Conflict
from app.db.session import transaction
from app.repositories import db_access as repo

from .common import iso, now_dt

ACTOR = "autopilot"
BLOCK_PREFIX = "Autopilot:"


def _cfg(conn: sqlite3.Connection) -> dict[str, str]:
    return repo.get_config_rows(conn)


def enabled(conn: sqlite3.Connection) -> bool:
    return _cfg(conn).get("autopilot_enabled", "0") == "1"


def set_enabled(conn: sqlite3.Connection, on: bool, actor: str) -> None:
    with transaction(conn):
        repo.set_config(conn, "autopilot_enabled", "1" if on else "0")
        repo.insert_audit(conn, iso(now_dt()), actor, "autopilot_toggled", {"enabled": on}, "config")


def on_scored(conn: sqlite3.Connection, out: dict, token: str, at) -> None:
    cfg = _cfg(conn)
    if cfg.get("autopilot_enabled", "0") != "1" or out["decision"] != "DECLINE":
        return
    if out["score"] < float(cfg.get("auto_block_score", "0.90")):
        return
    when = iso(at)
    with transaction(conn):
        reason = f"{BLOCK_PREFIX} score {out['score']:.2f} on transaction #{out['id']}"
        if repo.set_card_blocked(conn, token, True, ACTOR, reason, when):
            repo.insert_audit(conn, when, ACTOR, "card_blocked", {"token": token, "reason": reason, "auto": True}, f"card:{token}")


def on_reply(conn: sqlite3.Connection, tx_id: int, reply: str, at) -> None:
    if not enabled(conn):
        return
    from . import transactions_service
    verdict = "CONFIRMED_FRAUD" if reply == "NOT_ME" else "FALSE_POSITIVE"
    when = datetime.fromisoformat(at) if isinstance(at, str) else at
    try:
        transactions_service.review(conn, tx_id, verdict, "Closed automatically from the cardholder's reply.", ACTOR, when)
    except Conflict:
        return  # an analyst got there first
    with transaction(conn):
        conn.execute("UPDATE fraud_alerts SET auto_resolved=1 WHERE txn_id=?", (tx_id,))
        if reply == "LEGIT":
            tx = repo.get_transaction(conn, tx_id)
            card = repo.get_card(conn, tx["token"])
            if card and card["blocked"] and (card.get("block_reason") or "").startswith(BLOCK_PREFIX):
                stamp = iso(when)
                if repo.set_card_blocked(conn, tx["token"], False, ACTOR, None, stamp):
                    repo.insert_audit(conn, stamp, ACTOR, "card_unblocked", {"token": tx["token"], "reason": "cardholder confirmed the payment", "auto": True}, f"card:{tx['token']}")
