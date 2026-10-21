"""Request models. Response shapes are plain dicts documented in README."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOKEN_RE = r"^[A-Za-z0-9_-]+$"
_PAN_LIKE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str) -> str:
    value = value.strip()
    if _CONTROL.search(value):
        raise ValueError("control characters are not allowed")
    return value


def _reject_pan(value: str) -> str:
    if _PAN_LIKE.search(value):
        raise ValueError("looks like a card number (PAN); use synthetic tokens only")
    return value


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_token: str = Field(min_length=4, max_length=40, pattern=TOKEN_RE)
    amount: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    merchant: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    channel: Literal["POS", "ONLINE", "ATM", "WALLET"]

    @field_validator("card_token")
    @classmethod
    def _no_pan(cls, v: str) -> str:
        return _reject_pan(v)

    @field_validator("merchant")
    @classmethod
    def _merchant(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("must not be blank")
        return _reject_pan(v)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["CONFIRMED_FRAUD", "FALSE_POSITIVE"]
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().replace("\r", "")
        if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", v):
            raise ValueError("control characters are not allowed")
        return _reject_pan(v) or None


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=200)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str | None) -> str | None:
        return (_clean(v) or None) if v is not None else None


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve_max: float = Field(ge=0, lt=1, allow_inf_nan=False)
    hold_max: float = Field(gt=0, le=1, allow_inf_nan=False)
    high_amount: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    blocked_countries: str = Field(max_length=200)
    velocity_limit: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("blocked_countries")
    @classmethod
    def _countries(cls, v: str) -> str:
        codes = [c.strip().upper() for c in v.split(",") if c.strip()]
        bad = [c for c in codes if not re.fullmatch(r"[A-Z]{2}", c)]
        if bad:
            raise ValueError(f"not two-letter country codes: {', '.join(bad[:3])}")
        return ",".join(dict.fromkeys(codes))

    @model_validator(mode="after")
    def _ordering(self) -> "ConfigIn":
        if self.approve_max >= self.hold_max:
            raise ValueError("approve_max must be below hold_max")
        return self


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
