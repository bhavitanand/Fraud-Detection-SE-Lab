from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def now_iso() -> str:
    return iso(now_dt())


def hours_ago_iso(hours: int) -> str:
    return iso(now_dt() - timedelta(hours=hours))
