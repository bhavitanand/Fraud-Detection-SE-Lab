from __future__ import annotations

import sqlite3

from app.core.errors import Conflict, NotFound
from app.db.session import transaction
from app.repositories import db_access as repo
from app.schemas.models import TransactionIn

from .common import hours_ago_iso, now_iso
from .scoring import Scorer, ScoringInput, decide
from .settings_service import load_risk_config


def ingest(conn: sqlite3.Connection, tx: TransactionIn, scorer: Scorer, actor: str, source: str = "LIVE") -> dict:
    token, rejected = tx.card_token, False
    with transaction(conn):  # check-block, score, insert, card upsert and audit commit (or roll back) together
        card = repo.get_card(conn, token)
        if card and card["blocked"]:
            repo.insert_audit(conn, now_iso(), actor, "transaction_rejected_blocked", {"card_token": token, "amount": tx.amount}, f"card:{token}")
            rejected = True
        else:
            cfg = load_risk_config(conn)
            result = scorer.score(ScoringInput(tx.amount, tx.country.upper(), tx.channel, repo.count_recent(conn, token, hours_ago_iso(24))), cfg)
            decision = decide(result.score, cfg)
            factors = [f.as_dict() for f in result.factors]
            tx_id = repo.insert_transaction(
                conn, token=token, amount=tx.amount, merchant=tx.merchant, country=tx.country.upper(), channel=tx.channel,
                created=now_iso(), score=result.score, decision=decision, reasons=[f["label"] for f in factors if f["code"] not in ("base", "score_cap")],
                factors=factors, scorer=result.version, source=source, review="NOT_REQUIRED" if decision == "APPROVE" else "OPEN")
            repo.ensure_card(conn, token)
            out = {"id": tx_id, "score": result.score, "decision": decision, "reasons": [f["label"] for f in factors if f["code"] not in ("base", "score_cap")],
                   "factors": factors, "scorer": result.version, "alert_created": decision != "APPROVE"}
            repo.insert_audit(conn, now_iso(), actor, "transaction_scored",
                              {"transaction_id": tx_id, "score": result.score, "decision": decision, "alert_created": out["alert_created"]}, f"transaction:{tx_id}")
    if rejected:
        raise Conflict("Card token is blocked; transaction rejected.", code="card_blocked")
    return out


def review(conn: sqlite3.Connection, tx_id: int, verdict: str, note: str | None, actor: str) -> dict:
    with transaction(conn):
        tx = repo.get_transaction(conn, tx_id)
        if tx is None:
            raise NotFound(f"Transaction {tx_id} not found")
        if not tx["has_alert"]:
            raise Conflict("This transaction was approved and has no alert to review.", code="no_alert")
        if tx["review"] != "OPEN":
            raise Conflict(f"Alert already reviewed as {tx['review']} by {tx['reviewed_by'] or 'unknown'}.", code="already_reviewed")
        at = now_iso()
        if not repo.mark_reviewed(conn, tx_id, verdict, actor, note, at):
            raise Conflict("Alert was reviewed concurrently.", code="already_reviewed")
        repo.insert_audit(conn, at, actor, "review_recorded", {"transaction_id": tx_id, "verdict": verdict, "has_note": bool(note)}, f"transaction:{tx_id}")
        card_blocked = False
        if verdict == "CONFIRMED_FRAUD":
            changed = repo.set_card_blocked(conn, tx["token"], True, actor, f"Confirmed fraud on transaction #{tx_id}", at)
            card_blocked = True
            if changed:
                repo.insert_audit(conn, at, actor, "card_blocked", {"token": tx["token"], "reason": f"Confirmed fraud on transaction #{tx_id}"}, f"card:{tx['token']}")
        card = repo.get_card(conn, tx["token"])
    return {"ok": True, "transaction_id": tx_id, "verdict": verdict, "card_blocked": card_blocked,
            "card_token": tx["token"], "card_currently_blocked": bool(card and card["blocked"])}


def detail(conn: sqlite3.Connection, tx_id: int) -> dict:
    tx = repo.get_transaction(conn, tx_id)
    if tx is None:
        raise NotFound(f"Transaction {tx_id} not found")
    card = repo.get_card(conn, tx["token"]) or {"token": tx["token"], "blocked": False}
    return {**tx, "card": card, "token_history": repo.token_history(conn, tx["token"], tx_id),
            "audit": repo.audit_for_targets(conn, [f"transaction:{tx_id}", f"card:{tx['token']}"])}
