"""Scoring interface + the transparent heuristic baseline.

There is NO trained model in this repository (no labelled dataset is present, and none was downloaded).
`Scorer` is the seam where a trained model can be plugged in later and tested independently of the API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RiskConfig:
    approve_max: float = 0.25
    hold_max: float = 0.65
    high_amount: float = 1500.0
    blocked_countries: tuple[str, ...] = ("XX",)
    velocity_limit: int = 4


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    points: float

    def as_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "points": self.points}


@dataclass(frozen=True)
class ScoringInput:
    amount: float
    country: str
    channel: str
    prior_tx_24h: int  # transactions on the same token in the previous 24 hours


@dataclass(frozen=True)
class ScoreResult:
    score: float
    factors: list[Factor] = field(default_factory=list)
    version: str = ""


class Scorer(Protocol):
    version: str

    def score(self, tx: ScoringInput, cfg: RiskConfig) -> ScoreResult: ...


class HeuristicScorer:
    version = "heuristic-v1"
    BASE, HIGH_AMOUNT, BLOCKED_COUNTRY, ONLINE, VELOCITY = 0.04, 0.35, 0.75, 0.10, 0.25

    def score(self, tx: ScoringInput, cfg: RiskConfig) -> ScoreResult:
        factors = [Factor("base", "Baseline risk", self.BASE)]
        if tx.amount > cfg.high_amount:
            factors.append(Factor("high_amount", f"Amount above {cfg.high_amount:g}", self.HIGH_AMOUNT))
        if tx.country.upper() in cfg.blocked_countries:
            factors.append(Factor("blocked_country", f"Country {tx.country.upper()} is on the blocked list", self.BLOCKED_COUNTRY))
        if tx.channel == "ONLINE":
            factors.append(Factor("online_channel", "Online (card-not-present) channel", self.ONLINE))
        if tx.prior_tx_24h >= cfg.velocity_limit:
            factors.append(Factor("high_velocity", f"{tx.prior_tx_24h} earlier transactions on this token in 24h (limit {cfg.velocity_limit})", self.VELOCITY))
        raw = round(sum(f.points for f in factors), 3)
        if raw > 1.0:  # keep the explanation additive: factors always sum to the reported score
            factors.append(Factor("score_cap", "Score capped at 1.0", round(1.0 - raw, 3)))
        return ScoreResult(min(1.0, raw), factors, self.version)


def decide(score: float, cfg: RiskConfig) -> str:
    """Boundaries are inclusive on the lower decision: score == approve_max is APPROVE, == hold_max is HOLD."""
    if score <= cfg.approve_max:
        return "APPROVE"
    return "HOLD" if score <= cfg.hold_max else "DECLINE"
