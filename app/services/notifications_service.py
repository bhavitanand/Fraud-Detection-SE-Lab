"""Simulated cardholder notifications (outbox) with a one-time reply link. Nothing is sent over SMS or e-mail."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import timedelta

from app.core.errors import Conflict, NotFound
from app.db.session import transaction
from app.repositories import db_access as repo

from .common import iso, now_dt, now_iso

REPLY_TTL_HOURS = 72


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def queue_fraud_alert(conn: sqlite3.Connection, *, at=None, tx_id: int, card: dict, customer: dict | None, amount: float, currency: str, merchant: str, city: str | None, decision: str) -> None:
    """Call inside the ingest transaction. Raw reply token only appears in the outbox body (demo inbox), never in logs."""
    if not customer:
        return
    token = secrets.token_urlsafe(24)
    when = at or now_dt()
    sym = "₹" if currency == "INR" else currency + " "
    body = (f"Hello {customer['name'].split()[0]}, a payment of {sym}{amount:,.2f} at {merchant}{' (' + city + ')' if city else ''} on your card ending "
            f"{card['token'][-4:]} was {'held for review' if decision == 'HOLD' else 'declined'}. Was this you? Reply: /confirm/{token}")
    repo.insert_notification(conn, created=iso(when), channel="SMS" if customer.get("phone") else "EMAIL", recipient=customer.get("phone") or customer.get("email") or "n/a",
                             subject=None, body=body, kind="fraud_alert", txn_id=tx_id, reply_token_hash=_hash(token), expires_at=iso(when + timedelta(hours=REPLY_TTL_HOURS)))


def describe_reply_link(conn: sqlite3.Connection, token: str) -> dict:
    n = _lookup(conn, token)
    tx = repo.get_transaction(conn, n["txn_id"])
    return {"amount": tx["amount"], "currency": tx["currency"], "merchant": tx["merchant"], "location": tx["location"], "created": tx["created"],
            "card_last4": tx["token"][-4:], "already_replied": n["reply"] is not None, "reply": n["reply"]}


def _lookup(conn: sqlite3.Connection, token: str, allow_expired: bool = False) -> dict:
    n = repo.get_notification_by_hash(conn, _hash(token)) if 10 <= len(token) <= 80 else None
    if not n or n["kind"] != "fraud_alert":
        raise NotFound("This link is not valid.")
    if n["expires_at"] and n["expires_at"] < now_iso() and not allow_expired:
        raise Conflict("This link has expired.", code="link_expired")
    return n


def record_reply(conn: sqlite3.Connection, token: str, reply: str, at=None) -> dict:
    """reply: LEGIT or NOT_ME. NOT_ME blocks the card as a precaution; the alert stays OPEN for an analyst verdict."""
    with transaction(conn):
        n = _lookup(conn, token, allow_expired=at is not None)
        at = iso(at) if at else now_iso()
        if not repo.mark_notification_replied(conn, n["id"], reply, at):
            raise Conflict("You have already responded to this message.", code="already_replied")
        tx = repo.get_transaction(conn, n["txn_id"])
        repo.record_cardholder_response(conn, tx["id"], reply, at)
        repo.insert_audit(conn, at, "cardholder", "cardholder_replied", {"transaction_id": tx["id"], "reply": reply}, f"transaction:{tx['id']}")
        blocked = False
        if reply == "NOT_ME":
            blocked = repo.set_card_blocked(conn, tx["token"], True, "cardholder", f"Cardholder reported transaction #{tx['id']} as not theirs", at)
            if blocked:
                repo.insert_audit(conn, at, "cardholder", "card_blocked", {"token": tx["token"], "reason": "cardholder reported not me"}, f"card:{tx['token']}")
    return {"ok": True, "reply": reply, "card_blocked": reply == "NOT_ME"}
