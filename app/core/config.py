"""Runtime settings, read once from environment variables (no secrets in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    auth_required: bool = True
    secret_key: str | None = field(default=None, repr=False)
    cors_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    seed_demo: bool = True
    frontend_dist: Path = ROOT / "frontend" / "dist"
    token_ttl_minutes: int = 480
    login_otp: bool = False  # second step: 6-digit code sent to the user's e-mail
    otp_delivery: str = "console"  # "console" (dev: printed to the server terminal) or "smtp"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    smtp_from: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv("FRAUD_CORS_ORIGINS")
        return cls(
            db_path=Path(os.getenv("FRAUD_DB", ROOT / "fraud_demo.sqlite")),
            auth_required=_flag("FRAUD_AUTH_REQUIRED", True),
            secret_key=os.getenv("FRAUD_SECRET_KEY") or None,
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins else cls.cors_origins,
            seed_demo=_flag("FRAUD_SEED_DEMO", True),
            login_otp=_flag("FRAUD_LOGIN_OTP", False),
            otp_delivery=os.getenv("FRAUD_OTP_DELIVERY", "console").lower(),
            smtp_host=os.getenv("FRAUD_SMTP_HOST") or None,
            smtp_port=int(os.getenv("FRAUD_SMTP_PORT", "587")),
            smtp_user=os.getenv("FRAUD_SMTP_USER") or None,
            smtp_password=os.getenv("FRAUD_SMTP_PASSWORD") or None,
            smtp_from=os.getenv("FRAUD_SMTP_FROM") or None,
        )
