from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request

from app.core import security
from app.core.config import Settings
from app.core.errors import Forbidden, Unauthorized
from app.db.session import connect
from app.repositories import db_access as repo
from app.services.scoring import Scorer


@dataclass(frozen=True)
class User:
    username: str
    role: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_scorer(request: Request) -> Scorer:
    return request.app.state.scorer


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)) -> User:
    if not settings.auth_required:
        return User("local-demo", "admin")  # explicit local-only mode; /api/health reports it
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized("Authentication required.")
    claims = security.decode_token(request.app.state.secret, header[7:].strip())
    if not claims:
        raise Unauthorized("Session expired or invalid. Sign in again.")
    user = repo.get_user(conn, claims["sub"])  # re-check on every request so disabled users lose access immediately
    if not user or user["disabled"]:
        raise Unauthorized("Account is unavailable.")
    return User(user["username"], user["role"])


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise Forbidden("Administrator role required.")
    return user
