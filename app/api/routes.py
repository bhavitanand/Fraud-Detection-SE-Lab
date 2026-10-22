from __future__ import annotations

import logging
import sqlite3
import time
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.core.config import Settings
from app.core.errors import NotFound, TooManyAttempts
from app.db import migrations
from app.repositories import db_access as repo
from app.schemas.models import (AdminPasswordIn, AssignIn, BlockIn, ConfigIn, LoginIn, OtpIn, PasswordChangeIn, ReplyIn, ReviewIn, TransactionIn, UserCreateIn, UserUpdateIn)
from app.services import (auth_service, cards_service, models_service, notifications_service, reports_service, settings_service, transactions_service)
from app.services.geo import CITIES, FX_TO_INR
from app.services.ml_service import ModelService
from app.services.scoring import Scorer

from .deps import User, current_user, get_db, get_models, get_scorer, get_settings, require_admin

log = logging.getLogger("fraud.api")
router = APIRouter(prefix="/api")
TokenPath = Path(min_length=4, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
DATE = r"^\d{4}-\d{2}-\d{2}$"
_public_hits: dict[str, list[float]] = {}


def _public_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in _public_hits.get(ip, []) if now - t < 60]
    if len(hits) >= 20:
        raise TooManyAttempts("Too many requests. Wait a minute.")
    _public_hits[ip] = [*hits, now]


@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings), models: ModelService = Depends(get_models)):
    conn.execute("SELECT 1").fetchone()  # raises sqlite3.Error -> 503 via the global handler
    return {"status": "ok", "database": "sqlite", "schema_version": migrations.current_version(conn), "auth_required": settings.auth_required,
            "login_otp": settings.login_otp, "otp_delivery": settings.otp_delivery, "scoring": "rules" + (" + ML model" if models.active_id else " (no ML model active)"), "ml_available": models.available}


@router.get("/meta")
def meta(_: User = Depends(current_user)):
    return {"cities": [{"name": n, "country": v[2]} for n, v in CITIES.items()], "currencies": list(FX_TO_INR), "channels": ["POS", "ONLINE", "ATM", "WALLET"],
            "fx_note": "Fixed indicative rates used only for rule thresholds (INR); not live FX."}


# ---- auth ----
@router.post("/auth/login")
def login(body: LoginIn, request: Request, conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    return auth_service.login(conn, settings, body.email, body.password, request.app.state.secret)


@router.post("/auth/otp")
def verify_otp(body: OtpIn, request: Request, conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    return auth_service.verify_otp(conn, settings, body.challenge_id, body.code, request.app.state.secret)


@router.get("/auth/me")
def me(user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    return {"email": user.username, "name": user.name, "role": user.role, "auth_required": settings.auth_required}


@router.put("/auth/password")
def change_password(body: PasswordChangeIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    if not settings.auth_required:
        raise NotFound("Password changes are disabled in local no-login mode.")
    auth_service.change_password(conn, user.username, body.current_password, body.new_password)
    return {"ok": True}


# ---- users (administrator) ----
@router.get("/users")
def users(_: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return auth_service.list_users(conn)


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return auth_service.create_user(conn, body.email, body.password, body.role, body.name, actor=user.username)


@router.patch("/users/{email}")
def update_user(body: UserUpdateIn, email: str = Path(max_length=120), user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return auth_service.update_user(conn, email, user.username, body.role, body.disabled, body.name)


@router.put("/users/{email}/password")
def reset_password(body: AdminPasswordIn, email: str = Path(max_length=120), user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    auth_service.reset_password(conn, email, body.new_password, user.username)
    return {"ok": True}


# ---- transactions ----
@router.post("/transactions")
def ingest(body: TransactionIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), scorer: Scorer = Depends(get_scorer)):
    return transactions_service.ingest(conn, transactions_service.from_request(body), scorer, user.username)


@router.get("/transactions")
def list_transactions(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db),
    q: str | None = Query(None, max_length=60), decision: Literal["APPROVE", "HOLD", "DECLINE"] | None = None,
    review: Literal["OPEN", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "NOT_REQUIRED"] | None = None,
    channel: Literal["POS", "ONLINE", "ATM", "WALLET"] | None = None, country: str | None = Query(None, pattern=r"^[A-Za-z]{2}$"),
    source: Literal["SEED", "LIVE", "BENCH"] | None = None, min_score: float | None = Query(None, ge=0, le=1), max_score: float | None = Query(None, ge=0, le=1),
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
           assigned: Literal["me", "unassigned"] | None = None, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items, _total = repo.list_transactions(conn, alerts_only=True, review=None if status == "ALL" else status, decision=decision, page_size=100, sort="score",
                                           assigned_to=user.username if assigned == "me" else assigned)
    return items


@router.post("/alerts/{tx_id}/review")
def review_alert(tx_id: int, body: ReviewIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return transactions_service.review(conn, tx_id, body.verdict, body.note, user.username)


@router.post("/alerts/{tx_id}/assign")
def assign_alert(tx_id: int, body: AssignIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return transactions_service.assign(conn, tx_id, body.assignee, user.username, user.role)


# ---- cardholder notifications (simulated outbox) and the public reply link ----
@router.get("/notifications")
def notifications(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items, total = repo.list_notifications(conn, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset, "note": "Simulated outbox: nothing is sent by SMS or e-mail."}


@router.get("/public/confirm/{token}")
def reply_info(request: Request, token: str = Path(min_length=10, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"), conn: sqlite3.Connection = Depends(get_db)):
    _public_limit(request)
    return notifications_service.describe_reply_link(conn, token)


@router.post("/public/confirm/{token}")
def reply(body: ReplyIn, request: Request, token: str = Path(min_length=10, max_length=80, pattern=r"^[A-Za-z0-9_-]+$"), conn: sqlite3.Connection = Depends(get_db)):
    _public_limit(request)
    return notifications_service.record_reply(conn, token, body.reply)


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


# ---- config / rules ----
@router.get("/config")
def get_config(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return settings_service.config_view(conn)


@router.put("/config")
def put_config(body: ConfigIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return settings_service.update_config(conn, body, user.username)


@router.get("/rules")
def rules(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), scorer: Scorer = Depends(get_scorer), models: ModelService = Depends(get_models)):
    """Read-only catalogue of the scoring factors so the UI never hardcodes weights."""
    cfg = settings_service.config_view(conn)
    r = getattr(scorer, "rules", scorer)
    row = lambda code, label, pts, when: {"code": code, "label": label, "points": getattr(r, pts), "applies_when": when}  # noqa: E731
    return {"scorer": r.version, "trained_model": models.active_id is not None, "config": cfg, "factors": [
        row("base", "Baseline risk", "BASE", "always"),
        row("high_amount", "High amount", "HIGH_AMOUNT", f"amount (converted to INR) > ₹{cfg['high_amount']:,.0f}"),
        row("blocked_country", "Blocked country", "BLOCKED_COUNTRY", f"country in {cfg['blocked_countries'] or '(none)'}"),
        row("online_channel", "Online channel", "ONLINE", "channel = ONLINE"),
        row("high_velocity", "High velocity", "VELOCITY", f">= {cfg['velocity_limit']} earlier transactions on the card in 24h"),
        row("unusual_amount", "Unusual amount", "UNUSUAL_AMOUNT", f"> {r.UNUSUAL_MULTIPLE:g}x the card's average (at least {r.MIN_HISTORY} earlier transactions and amount > ₹{r.UNUSUAL_MIN_INR:,.0f})"),
        row("new_country", "New country", "NEW_COUNTRY", "country differs from the cardholder's home country and was never used on this card"),
        row("new_merchant", "New merchant", "NEW_MERCHANT", f"merchant never used on a card with at least {r.MIN_HISTORY + 2} earlier transactions"),
        row("impossible_travel", "Impossible travel", "IMPOSSIBLE_TRAVEL", f"known cities at least {r.MIN_KM:g} km apart reached faster than {r.MAX_KMH:g} km/h"),
    ], "decision_rule": "score <= approve_max: APPROVE; score <= hold_max: HOLD; otherwise DECLINE. Score is capped at 1.0.",
        "ml_note": "When an active ML model exists and a transaction carries the 28 anonymised benchmark features, its probability p is combined with the rule score as 1-(1-rules)(1-p)."}


# ---- ML model registry ----
@router.get("/models")
def models_list(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), models: ModelService = Depends(get_models)):
    return {"items": repo.list_models(conn), "ml_available": models.available, "benchmark": models_service.benchmark_summary(conn),
            "training_note": "Training runs offline: python -m ml.train --csv data/creditcard.csv --register. The web app never reads arbitrary files."}


@router.post("/models/{model_id}/deploy")
def deploy_model(model_id: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db), models: ModelService = Depends(get_models)):
    return models_service.deploy(conn, models, model_id, user.username)


@router.post("/models/{model_id}/retire")
def retire_model(model_id: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db), models: ModelService = Depends(get_models)):
    return models_service.retire(conn, models, model_id, user.username)


@router.post("/models/benchmark/replay")
def replay(count: int = Query(10, ge=1, le=25), user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db), scorer: Scorer = Depends(get_scorer)):
    return models_service.replay(conn, scorer, user.username, count)


# ---- reports / labels / audit ----
@router.get("/reports")
def reports(date_from: str | None = Query(None, pattern=DATE), date_to: str | None = Query(None, pattern=DATE), source: Literal["SEED", "LIVE", "BENCH"] | None = None,
            _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return reports_service.build_report(conn, date_from, date_to, source)


@router.get("/reports/export.csv")
def export(date_from: str | None = Query(None, pattern=DATE), date_to: str | None = Query(None, pattern=DATE),
           _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return Response(reports_service.export_csv(conn, date_from, date_to), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


@router.get("/labels/export.csv")
def export_labels(_: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Analyst verdicts stored as labels (1 = confirmed fraud, 0 = false positive) for future model training."""
    return Response(reports_service.export_labels(conn), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="confirmed_labels.csv"'})


@router.get("/audit")
def audit(action: str | None = Query(None, max_length=60), actor: str | None = Query(None, max_length=120), q: str | None = Query(None, max_length=60),
          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), _: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items, total = repo.list_audit(conn, action=action, actor=actor, q=q, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset, "actions": repo.audit_actions(conn)}


@router.get("/audit/verify")
def audit_verify(_: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return repo.verify_audit_chain(conn)
