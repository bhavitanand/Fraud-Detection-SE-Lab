from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import timedelta

from app.core import security
from app.core.config import Settings
from app.core.errors import Conflict, Forbidden, Invalid, NotFound, TooManyAttempts, Unauthorized
from app.db.session import transaction
from app.repositories import db_access as repo

from . import mailer
from .common import iso, now_dt, now_iso

MAX_FAILS, LOCK_SECONDS = 5, 60
OTP_MINUTES, OTP_MAX_ATTEMPTS = 5, 5
_fails: dict[str, tuple[int, float]] = {}  # in-memory per-process throttle (demo-grade)


def ensure_secret(conn: sqlite3.Connection, configured: str | None) -> str:
    if configured:
        return configured
    with transaction(conn):
        existing = repo.get_meta(conn, "jwt_secret")
        if existing:
            return existing
        s = secrets.token_urlsafe(48)
        repo.set_meta(conn, "jwt_secret", s)
        return s


def create_user(conn: sqlite3.Connection, email: str, password: str, role: str, name: str | None = None, actor: str = "system") -> dict:
    if role not in ("analyst", "admin"):
        raise Invalid("role must be 'analyst' or 'admin'")
    if len(password) < 10:
        raise Invalid("password must be at least 10 characters")
    email = email.strip().lower()
    with transaction(conn):
        if repo.get_user(conn, email):
            raise Conflict(f"user '{email}' already exists")
        repo.insert_user(conn, email, security.hash_password(password), role, now_iso(), name or email.split("@")[0])
        repo.insert_audit(conn, now_iso(), actor, "user_created", {"email": email, "role": role}, f"user:{email}")
    return {"email": email, "role": role, "name": name or email.split("@")[0]}


def _throttle(key: str) -> None:
    count, until = _fails.get(key, (0, 0.0))
    if count >= MAX_FAILS and time.time() < until:
        raise TooManyAttempts("Too many failed attempts. Wait a minute and try again.")


def _fail(conn: sqlite3.Connection, key: str, action: str) -> None:
    count, _ = _fails.get(key, (0, 0.0))
    _fails[key] = (count + 1, time.time() + LOCK_SECONDS)
    with transaction(conn):
        repo.insert_audit(conn, now_iso(), "anonymous", action, {"email": key[:120]}, f"user:{key[:120]}")


def _session(user: dict, secret: str, ttl: int) -> dict:
    return {"access_token": security.issue_token(secret, user["username"], user["role"], ttl), "token_type": "bearer",
            "user": {"email": user["username"], "name": user.get("name"), "role": user["role"]}}


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{domain}"


def login(conn: sqlite3.Connection, settings: Settings, email: str, password: str, secret: str) -> dict:
    key = email.strip().lower()
    _throttle(key)
    user = repo.get_user(conn, key)
    if not user or user["disabled"] or not security.verify_password(password, user["password_hash"]):
        _fail(conn, key, "login_failed")
        raise Unauthorized("Invalid email or password.")
    if settings.login_otp:
        code = f"{secrets.randbelow(10**6):06d}"
        with transaction(conn):
            oid = repo.insert_otp(conn, user["username"], "", now_iso(), iso(now_dt() + timedelta(minutes=OTP_MINUTES)))
            conn.execute("UPDATE otp_challenges SET code_hash=? WHERE id=?", (_otp_hash(secret, oid, code), oid))
            repo.insert_audit(conn, now_iso(), user["username"], "otp_sent", {"challenge_id": oid}, f"user:{user['username']}")
        mailer.send_otp(settings, user["username"], code, OTP_MINUTES)  # after commit: a failed send never leaves a usable code unseen
        return {"otp_required": True, "challenge_id": oid, "email_hint": _mask(user["username"]), "expires_in": OTP_MINUTES * 60}
    _fails.pop(key, None)
    with transaction(conn):
        repo.insert_audit(conn, now_iso(), user["username"], "login", {}, f"user:{user['username']}")
    return _session(user, secret, settings.token_ttl_minutes)


def _otp_hash(secret: str, oid: int, code: str) -> str:
    return hmac.new(secret.encode(), f"{oid}:{code}".encode(), hashlib.sha256).hexdigest()


def verify_otp(conn: sqlite3.Connection, settings: Settings, challenge_id: int, code: str, secret: str) -> dict:
    ch = repo.get_otp(conn, challenge_id)
    key = (ch or {}).get("email", f"challenge:{challenge_id}")
    _throttle(key)
    if not ch or ch["used"] or ch["expires_at"] < now_iso() or ch["attempts"] >= OTP_MAX_ATTEMPTS:
        _fail(conn, key, "otp_failed")
        raise Unauthorized("This code is invalid or has expired. Sign in again.")
    with transaction(conn):
        repo.bump_otp_attempts(conn, challenge_id)
    if not hmac.compare_digest(ch["code_hash"], _otp_hash(secret, challenge_id, code)):
        _fail(conn, key, "otp_failed")
        raise Unauthorized("Incorrect code.")
    user = repo.get_user(conn, ch["email"])
    if not user or user["disabled"]:
        raise Unauthorized("Account is unavailable.")
    with transaction(conn):
        if not repo.use_otp(conn, challenge_id):
            raise Unauthorized("This code has already been used.")
        repo.insert_audit(conn, now_iso(), user["username"], "login", {"otp": True}, f"user:{user['username']}")
    _fails.pop(key, None)
    return _session(user, secret, settings.token_ttl_minutes)


def change_password(conn: sqlite3.Connection, email: str, current: str, new: str) -> None:
    user = repo.get_user(conn, email)
    if not user or not security.verify_password(current, user["password_hash"]):
        raise Unauthorized("Current password is incorrect.")
    with transaction(conn):
        repo.update_user(conn, user["username"], password_hash=security.hash_password(new))
        repo.insert_audit(conn, now_iso(), user["username"], "password_changed", {}, f"user:{user['username']}")


# ---- administrator user management ----
def list_users(conn: sqlite3.Connection) -> list[dict]:
    return [{"email": u["username"], "name": u["name"], "role": u["role"], "created": u["created"], "disabled": bool(u["disabled"])} for u in repo.list_users(conn)]


def update_user(conn: sqlite3.Connection, email: str, actor: str, role: str | None, disabled: bool | None, name: str | None) -> dict:
    with transaction(conn):
        user = repo.get_user(conn, email)
        if not user:
            raise NotFound(f"User {email} not found")
        would_lose_admin = user["role"] == "admin" and not user["disabled"] and (role == "analyst" or disabled is True)
        if would_lose_admin and repo.count_active_admins(conn) <= 1:
            raise Conflict("There must be at least one active administrator.", code="last_admin")
        fields = {k: v for k, v in (("role", role), ("disabled", int(disabled) if disabled is not None else None), ("name", name)) if v is not None}
        repo.update_user(conn, user["username"], **fields)
        repo.insert_audit(conn, now_iso(), actor, "user_updated", {"email": user["username"], **{k: v for k, v in fields.items()}}, f"user:{user['username']}")
    u = repo.get_user(conn, email)
    return {"email": u["username"], "name": u["name"], "role": u["role"], "disabled": bool(u["disabled"])}


def reset_password(conn: sqlite3.Connection, email: str, new_password: str, actor: str) -> None:
    if len(new_password) < 10:
        raise Invalid("password must be at least 10 characters")
    with transaction(conn):
        user = repo.get_user(conn, email)
        if not user:
            raise NotFound(f"User {email} not found")
        repo.update_user(conn, user["username"], password_hash=security.hash_password(new_password))
        repo.insert_audit(conn, now_iso(), actor, "password_reset", {"email": user["username"]}, f"user:{user['username']}")
    _fails.pop(email.lower(), None)


__all__ = ["Forbidden"]
