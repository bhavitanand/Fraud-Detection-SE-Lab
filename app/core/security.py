"""Password hashing (Argon2 via pwdlib) and signed session tokens (PyJWT, HS256)."""
from __future__ import annotations

import time

import jwt
from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    # Always do one hash verification so unknown users cost the same as wrong passwords.
    return _hasher.verify(password, password_hash or _DUMMY_HASH) and password_hash is not None


def issue_token(secret: str, username: str, role: str, ttl_minutes: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": username, "role": role, "iat": now, "exp": now + ttl_minutes * 60}, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
