"""Hash chain for the audit log (tamper-evident, not tamper-proof)."""
from __future__ import annotations

import hashlib

GENESIS = "0" * 64


def row_hash(prev: str, at: str, actor: str, action: str, detail: str, target: str | None) -> str:
    payload = "\x1f".join([prev, at, actor, action, detail, target or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
