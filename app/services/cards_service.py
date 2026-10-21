from __future__ import annotations

import sqlite3

from app.db.session import transaction
from app.repositories import db_access as repo

from .common import now_iso


def set_blocked(conn: sqlite3.Connection, token: str, blocked: bool, actor: str, reason: str | None = None) -> dict:
    with transaction(conn):
        at = now_iso()
        changed = repo.set_card_blocked(conn, token, blocked, actor, reason or ("Manual block" if blocked else None), at)
        if changed:
            repo.insert_audit(conn, at, actor, "card_blocked" if blocked else "card_unblocked", {"token": token, **({"reason": reason} if reason else {})}, f"card:{token}")
    card = repo.get_card(conn, token)
    return {"token": token, "blocked": card["blocked"], "changed": changed}
