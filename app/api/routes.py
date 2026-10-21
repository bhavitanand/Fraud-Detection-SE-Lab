from __future__ import annotations

import logging
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.core.config import Settings
from app.core.errors import NotFound
from app.db import migrations
from app.repositories import db_access as repo
from app.schemas.models import BlockIn, ConfigIn, LoginIn, ReviewIn, TransactionIn
from app.services import auth_service, cards_service, reports_service, settings_service, transactions_service
from app.services.scoring import Scorer

from .deps import User, current_user, get_db, get_scorer, get_settings, require_admin

log = logging.getLogger("fraud.api")
router = APIRouter(prefix="/api")
TokenPath = Path(min_length=4, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
DATE = r"^\d{4}-\d{2}-\d{2}$"


@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    conn.execute("SELECT 1").fetchone()  # raises sqlite3.Error -> 503 via the global handler
    return {"status": "ok", "database": "sqlite", "schema_version": migrations.current_version(conn),
            "scoring": "transparent demo heuristic; no trained model", "auth_required": settings.auth_required}


# ---- auth ----
@router.post("/auth/login")
def login(body: LoginIn, request: Request, conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    return auth_service.login(conn, body.username, body.password, request.app.state.secret, settings.token_ttl_minutes)


@router.get("/auth/me")
def me(user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    return {"username": user.username, "role": user.role, "auth_required": settings.auth_required}


# ---- transactions ----
@router.post("/transactions")
def ingest(body: TransactionIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), scorer: Scorer = Depends(get_scorer)):
    return transactions_service.ingest(conn, body, scorer, user.username)


@router.get("/transactions")
def list_transactions(
    _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db),
    q: str | None = Query(None, max_length=60), decision: Literal["APPROVE", "HOLD", "DECLINE"] | None = None,
    review: Literal["OPEN", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "NOT_REQUIRED"] | None = None,
    channel: Literal["POS", "ONLINE", "ATM", "WALLET"] | None = None, country: str | None = Query(None, pattern=r"^[A-Za-z]{2}$"),
    source: Literal["SEED", "LIVE"] | None = None, min_score: float | None = Query(None, ge=0, le=1), max_score: float | None = Query(None, ge=0, le=1),
    date_from: str | None = Query(None, pattern=DATE), date_to: str | None = Query(None, pattern=DATE),
    sort: Literal["id", "created", "amount", "score", "decision", "token", "merchant"] = "id", order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1, le=100000), page_size: int = Query(25, ge=1, le=100),
):
    items, total = repo.list_transactions(conn, q=q, decision=decision, review=review, channel=channel, country=country.upper() if country else None,
                                          source=source, min_score=min_score, max_score=max_score, sort=sort, order=order, page=page,
                                          page_size=page_size, date_from=date_from, date_to=date_to)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": max(1, -(-total // page_size))}


@router.get("/transactions/{tx_id}")
def transaction_detail(tx_id: int, _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return transactions_service.detail(conn, tx_id)


# ---- alerts ----
@router.get("/alerts")
def alerts(status: Literal["OPEN", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "ALL"] = "OPEN", decision: Literal["HOLD", "DECLINE"] | None = None,
           _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items, _total = repo.list_transactions(conn, alerts_only=True, review=None if status == "ALL" else status, decision=decision, page_size=100, sort="score")
    return items


@router.post("/alerts/{tx_id}/review")
def review_alert(tx_id: int, body: ReviewIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return transactions_service.review(conn, tx_id, body.verdict, body.note, user.username)


# ---- cards ----
@router.get("/cards")
def cards(q: str | None = Query(None, max_length=40), blocked: bool | None = None, _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return repo.list_cards(conn, q, blocked)


@router.post("/cards/{token}/block")
def block_card(token: str = TokenPath, body: BlockIn | None = None, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return cards_service.set_blocked(conn, token, True, user.username, body.reason if body else None)


@router.post("/cards/{token}/unblock")
def unblock_card(token: str = TokenPath, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return cards_service.set_blocked(conn, token, False, user.username)


# ---- config ----
@router.get("/config")
def get_config(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return settings_service.config_view(conn)


@router.put("/config")
def put_config(body: ConfigIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return settings_service.update_config(conn, body, user.username)


@router.get("/rules")
def rules(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), scorer: Scorer = Depends(get_scorer)):
    """Read-only catalogue of the scoring factors so the UI never hardcodes weights."""
    cfg = settings_service.config_view(conn)
    w = {k: getattr(scorer, k, None) for k in ("BASE", "HIGH_AMOUNT", "BLOCKED_COUNTRY", "ONLINE", "VELOCITY")}
    return {"scorer": scorer.version, "trained_model": False, "config": cfg, "factors": [
        {"code": "base", "label": "Baseline risk", "points": w["BASE"], "applies_when": "always"},
        {"code": "high_amount", "label": "High amount", "points": w["HIGH_AMOUNT"], "applies_when": f"amount > {cfg['high_amount']:g}"},
        {"code": "blocked_country", "label": "Blocked country", "points": w["BLOCKED_COUNTRY"], "applies_when": f"country in {cfg['blocked_countries'] or '(none)'}"},
        {"code": "online_channel", "label": "Online channel", "points": w["ONLINE"], "applies_when": "channel = ONLINE"},
        {"code": "high_velocity", "label": "High velocity", "points": w["VELOCITY"], "applies_when": f">= {cfg['velocity_limit']} earlier transactions on the token in 24h"},
    ], "decision_rule": "score <= approve_max: APPROVE; score <= hold_max: HOLD; otherwise DECLINE. Score is capped at 1.0."}


# ---- reports / audit ----
@router.get("/reports")
def reports(date_from: str | None = Query(None, pattern=DATE), date_to: str | None = Query(None, pattern=DATE), source: Literal["SEED", "LIVE"] | None = None,
            _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return reports_service.build_report(conn, date_from, date_to, source)


@router.get("/reports/export.csv")
def export(date_from: str | None = Query(None, pattern=DATE), date_to: str | None = Query(None, pattern=DATE),
           _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return Response(reports_service.export_csv(conn, date_from, date_to), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


@router.get("/audit")
def audit(action: str | None = Query(None, max_length=60), actor: str | None = Query(None, max_length=64), q: str | None = Query(None, max_length=60),
          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items, total = repo.list_audit(conn, action=action, actor=actor, q=q, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset, "actions": repo.audit_actions(conn)}
