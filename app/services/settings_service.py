from __future__ import annotations

import sqlite3

from app.db.session import transaction
from app.repositories import db_access as repo
from app.schemas.models import ConfigIn

from .common import now_iso
from .scoring import RiskConfig

DEFAULTS = {"approve_max": "0.25", "hold_max": "0.65", "high_amount": "1500", "blocked_countries": "XX", "velocity_limit": "4"}


def ensure_defaults(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        for k, v in DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO config VALUES(?,?)", (k, v))


def load_risk_config(conn: sqlite3.Connection) -> RiskConfig:
    rows = {**DEFAULTS, **repo.get_config_rows(conn)}
    return RiskConfig(
        approve_max=float(rows["approve_max"]), hold_max=float(rows["hold_max"]), high_amount=float(rows["high_amount"]),
        blocked_countries=tuple(c.strip().upper() for c in rows["blocked_countries"].split(",") if c.strip()),
        velocity_limit=int(rows["velocity_limit"]),
    )


def config_view(conn: sqlite3.Connection) -> dict:
    cfg = load_risk_config(conn)
    return {"approve_max": cfg.approve_max, "hold_max": cfg.hold_max, "high_amount": cfg.high_amount,
            "blocked_countries": ",".join(cfg.blocked_countries), "velocity_limit": cfg.velocity_limit}


def update_config(conn: sqlite3.Connection, data: ConfigIn, actor: str) -> dict:
    before = config_view(conn)
    new = data.model_dump()
    if new["velocity_limit"] is None:
        new["velocity_limit"] = before["velocity_limit"]
    with transaction(conn):
        for k, v in new.items():
            repo.set_config(conn, k, str(v))
        repo.insert_audit(conn, now_iso(), actor, "config_updated", {"before": before, "after": new}, "config")
    return config_view(conn)
