from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.db.session import transaction
from app.repositories import db_access as repo
from app.schemas.models import TransactionIn

from . import notifications_service
from .common import iso, now_dt
from .geo import CITIES, to_inr
from .scoring import Scorer, ScoringInput, decide
from .settings_service import load_risk_config


@dataclass(frozen=True)
class NewTx:
    card_token: str
    amount: float
    currency: str
    merchant: str
    country: str
    channel: str
    location: str | None = None
    anon_features: tuple[float, ...] | None = None
    source: str = "LIVE"
    benchmark_label: int | None = None


def from_request(t: TransactionIn) -> NewTx:
    return NewTx(t.card_token, t.amount, t.currency, t.merchant, t.country.upper(), t.channel, t.location, tuple(t.anon_features) if t.anon_features else None)


def ingest(conn: sqlite3.Connection, tx: NewTx, scorer: Scorer, actor: str, at: datetime | None = None) -> dict:
    if tx.location in CITIES and CITIES[tx.location][2] != tx.country:
        raise Invalid(f"Location {tx.location} is in {CITIES[tx.location][2]}, not {tx.country}.", [{"field": "location", "message": "does not match country"}])
    token, rejected = tx.card_token, False
    now = at or now_dt()
    now_s = iso(now)
    with transaction(conn):  # check-block, score, insert, alert, notification and audit commit (or roll back) together
        card = repo.get_card(conn, token)
        if card and card["blocked"]:
            repo.insert_audit(conn, now_s, actor, "transaction_rejected_blocked", {"card_token": token, "amount": tx.amount, "currency": tx.currency}, f"card:{token}")
            rejected = True
        else:
            cfg = load_risk_config(conn)
            card_id = repo.ensure_card(conn, token)
            card = repo.get_card(conn, token)
            customer = repo.get_customer(conn, card["customer_id"])
            merchant_id = repo.find_or_create_merchant(conn, tx.merchant)
            hist = repo.card_history_stats(conn, card_id, tx.currency)
            last = hist["last"]
            hours_since = None
            if last:
                try:
                    hours_since = max((now - datetime.fromisoformat(last["created"])).total_seconds() / 3600, 0.0)
                except ValueError:
                    hours_since = None
            inp = ScoringInput(
                amount_inr=to_inr(tx.amount, tx.currency), country=tx.country, channel=tx.channel, prior_tx_24h=repo.count_recent(conn, token, iso(now - timedelta(hours=24))),
                home_country=(customer or {}).get("home_country", "IN"), history_count=hist["count"], history_avg_inr=to_inr(hist["avg_amount"], tx.currency),
                seen_countries=frozenset(hist["countries"]), seen_merchant=(merchant_id in hist["merchants"]) or hist["count"] == 0, city=tx.location,
                last_city=last["location"] if last else None, hours_since_last=hours_since, rules_applicable=tx.source != "BENCH",
                anon_features=tx.anon_features, amount_raw=tx.amount)
            result = scorer.score(inp, cfg)
            decision = decide(result.score, cfg)
            factors = [f.as_dict() for f in result.factors]
            reasons = [f["label"] for f in factors if f["code"] not in ("base", "score_cap")]
            created = now_s
            tx_id = repo.insert_transaction(
                conn, token=token, card_id=card_id, amount=tx.amount, currency=tx.currency, merchant=tx.merchant, merchant_id=merchant_id, country=tx.country,
                location=tx.location, channel=tx.channel, created=created, score=result.score, decision=decision, reasons=reasons, factors=factors,
                scorer=result.version, model_id=result.model_id, source=tx.source, benchmark_label=tx.benchmark_label)
            alert_id = repo.create_alert(conn, tx_id, result.score, created) if decision != "APPROVE" else None
            if alert_id:
                notifications_service.queue_fraud_alert(conn, at=now, tx_id=tx_id, card=card, customer=customer, amount=tx.amount, currency=tx.currency,
                                                        merchant=tx.merchant, city=tx.location, decision=decision)
            out = {"id": tx_id, "score": result.score, "decision": decision, "reasons": reasons, "factors": factors, "scorer": result.version,
                   "alert_created": alert_id is not None, "alert_id": alert_id, "currency": tx.currency}
            repo.insert_audit(conn, created, actor, "transaction_scored",
                              {"transaction_id": tx_id, "score": result.score, "decision": decision, "alert_created": out["alert_created"]}, f"transaction:{tx_id}")
    if rejected:
        raise Conflict("Card token is blocked; transaction rejected.", code="card_blocked")
    return out


def review(conn: sqlite3.Connection, tx_id: int, verdict: str, note: str | None, actor: str, at: datetime | None = None) -> dict:
    with transaction(conn):
        tx = repo.get_transaction(conn, tx_id)
        if tx is None:
            raise NotFound(f"Transaction {tx_id} not found")
        if not tx["has_alert"]:
            raise Conflict("This transaction was approved and has no alert to review.", code="no_alert")
        if tx["review"] != "OPEN":
            raise Conflict(f"Alert already reviewed as {tx['review']} by {tx['reviewed_by'] or 'unknown'}.", code="already_reviewed")
        at = iso(at or now_dt())
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


def assign(conn: sqlite3.Connection, tx_id: int, assignee: str | None, actor: str, actor_role: str) -> dict:
    with transaction(conn):
        tx = repo.get_transaction(conn, tx_id)
        if tx is None:
            raise NotFound(f"Transaction {tx_id} not found")
        if not tx["has_alert"]:
            raise Conflict("This transaction has no alert.", code="no_alert")
        if tx["review"] != "OPEN":
            raise Conflict("A reviewed alert can no longer be reassigned.", code="already_reviewed")
        if assignee is not None:
            user = repo.get_user(conn, assignee)
            if not user or user["disabled"]:
                raise Invalid("Assignee must be an active user.", [{"field": "assignee", "message": "unknown or disabled user"}])
            assignee = user["username"]
        if actor_role != "admin" and assignee not in (None, actor):
            raise Forbidden("Analysts can only assign alerts to themselves.")
        if actor_role != "admin" and assignee is None and tx["assigned_to"] not in (None, actor):
            raise Forbidden("Only the assignee or an administrator can unassign this alert.")
        repo.assign_alert(conn, tx_id, assignee)
        repo.insert_audit(conn, iso(now_dt()), actor, "alert_assigned", {"transaction_id": tx_id, "assignee": assignee}, f"transaction:{tx_id}")
    return {"ok": True, "transaction_id": tx_id, "assigned_to": assignee}


def detail(conn: sqlite3.Connection, tx_id: int) -> dict:
    tx = repo.get_transaction(conn, tx_id)
    if tx is None:
        raise NotFound(f"Transaction {tx_id} not found")
    card = repo.get_card(conn, tx["token"]) or {"token": tx["token"], "blocked": False}
    customer = repo.get_customer(conn, card.get("customer_id"))
    merchant = repo.get_merchant(conn, tx.get("merchant_id"))
    safe_customer = {k: customer[k] for k in ("name", "city", "state", "home_country")} if customer else None
    return {**tx, "card": card, "customer": safe_customer, "merchant_info": merchant, "token_history": repo.token_history(conn, tx["token"], tx_id),
            "audit": repo.audit_for_targets(conn, [f"transaction:{tx_id}", f"card:{tx['token']}"])}
