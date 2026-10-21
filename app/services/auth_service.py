from __future__ import annotations

import secrets
import sqlite3
import time

from app.core import security
from app.core.errors import Conflict, Invalid, TooManyAttempts, Unauthorized
from app.db.session import transaction
from app.repositories import db_access as repo

from .common import now_iso

MAX_FAILS, LOCK_SECONDS = 5, 60
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


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> None:
    if role not in ("analyst", "admin"):
        raise Invalid("role must be 'analyst' or 'admin'")
    if len(password) < 10:
        raise Invalid("password must be at least 10 characters")
    with transaction(conn):
        if repo.get_user(conn, username):
            raise Conflict(f"user '{username}' already exists")
        repo.insert_user(conn, username, security.hash_password(password), role, now_iso())
        repo.insert_audit(conn, now_iso(), "system", "user_created", {"username": username, "role": role}, f"user:{username}")


def login(conn: sqlite3.Connection, username: str, password: str, secret: str, ttl: int) -> dict:
    key = username.lower()
    count, until = _fails.get(key, (0, 0.0))
    if count >= MAX_FAILS and time.time() < until:
        raise TooManyAttempts("Too many failed sign-in attempts. Wait a minute and try again.")
    user = repo.get_user(conn, username)
    if not user or user["disabled"] or not security.verify_password(password, user["password_hash"]):
        _fails[key] = (count + 1, time.time() + LOCK_SECONDS)
        with transaction(conn):
            repo.insert_audit(conn, now_iso(), "anonymous", "login_failed", {"username": username[:64]}, f"user:{username[:64]}")
        raise Unauthorized("Invalid username or password.")
    _fails.pop(key, None)
    with transaction(conn):
        repo.insert_audit(conn, now_iso(), user["username"], "login", {}, f"user:{user['username']}")
    return {"access_token": security.issue_token(secret, user["username"], user["role"], ttl), "token_type": "bearer",
            "user": {"username": user["username"], "role": user["role"]}}
