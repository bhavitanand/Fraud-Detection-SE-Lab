"""Database bootstrap: migrate, default config, signing secret, optional synthetic demo data."""
from __future__ import annotations

import logging

from app.core.config import Settings
from app.repositories import db_access as repo
from app.services import auth_service, settings_service
from app.services.models_service import bootstrap_registry
from app.services.seed import seed_demo_data

from .migrations import migrate
from .session import connect

log = logging.getLogger("fraud.db")


def init_database(settings: Settings) -> str:
    """Idempotent. Returns the JWT signing secret."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        version = migrate(conn)
        settings_service.ensure_defaults(conn)
        secret = auth_service.ensure_secret(conn, settings.secret_key)
        bootstrap_registry(conn)
        if settings.seed_demo and repo.get_meta(conn, "seeded") is None:
            seed_demo_data(conn)
        log.info("database ready (schema v%s)", version)
        return secret
    finally:
        conn.close()
