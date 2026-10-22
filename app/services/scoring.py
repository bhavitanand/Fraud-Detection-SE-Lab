"""Scoring interface, the transparent rule baseline, and the hybrid (rules + ML) scorer.

Every point in the score appears as a named factor, so factors always sum to the score.
The optional ML component is a model trained offline on the public ULB benchmark (see ml/ and README);
it only applies to rows that carry the 28 anonymised benchmark features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .geo import haversine_km


@dataclass(frozen=True)
class RiskConfig:
    approve_max: float = 0.25
    hold_max: float = 0.65
    high_amount: float = 50000.0  # INR
    blocked_countries: tuple[str, ...] = ("XX", "KP", "IR")
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
    amount_inr: float
    country: str
    channel: str
    prior_tx_24h: int  # transactions on the same token in the previous 24 hours
    home_country: str = "IN"
    history_count: int = 0  # prior transactions on this card (same currency)
    history_avg_inr: float = 0.0
    seen_countries: frozenset = frozenset()
    seen_merchant: bool = True  # False only when the merchant is new for a card with history
    city: str | None = None
    last_city: str | None = None
    hours_since_last: float | None = None
    rules_applicable: bool = True  # False for benchmark rows that lack real merchant/location fields
    anon_features: tuple[float, ...] | None = None
    amount_raw: float = 0.0


@dataclass(frozen=True)
class ScoreResult:
    score: float
    factors: list[Factor] = field(default_factory=list)
    version: str = ""
    model_id: int | None = None


class Scorer(Protocol):
    version: str

    def score(self, tx: ScoringInput, cfg: RiskConfig) -> ScoreResult: ...


class HeuristicScorer:
    version = "heuristic-v2"
    BASE, HIGH_AMOUNT, BLOCKED_COUNTRY, ONLINE, VELOCITY = 0.04, 0.35, 0.75, 0.10, 0.25
    UNUSUAL_AMOUNT, NEW_COUNTRY, NEW_MERCHANT, IMPOSSIBLE_TRAVEL = 0.20, 0.15, 0.05, 0.35
    UNUSUAL_MULTIPLE, UNUSUAL_MIN_INR, MIN_HISTORY, MAX_KMH, MIN_KM = 5.0, 2000.0, 3, 900.0, 200.0

    def score(self, tx: ScoringInput, cfg: RiskConfig) -> ScoreResult:
        factors = [Factor("base", "Baseline risk", self.BASE)]
        if tx.rules_applicable:
            if tx.amount_inr > cfg.high_amount:
                factors.append(Factor("high_amount", f"Amount above ₹{cfg.high_amount:,.0f}", self.HIGH_AMOUNT))
            if tx.country.upper() in cfg.blocked_countries:
                factors.append(Factor("blocked_country", f"Country {tx.country.upper()} is on the blocked list", self.BLOCKED_COUNTRY))
            if tx.channel == "ONLINE":
                factors.append(Factor("online_channel", "Online (card-not-present) channel", self.ONLINE))
            if tx.prior_tx_24h >= cfg.velocity_limit:
                factors.append(Factor("high_velocity", f"{tx.prior_tx_24h} earlier transactions on this card in 24h (limit {cfg.velocity_limit})", self.VELOCITY))
            if tx.history_count >= self.MIN_HISTORY and tx.amount_inr > self.UNUSUAL_MIN_INR and tx.amount_inr > self.UNUSUAL_MULTIPLE * tx.history_avg_inr:
                factors.append(Factor("unusual_amount", f"Amount is {tx.amount_inr / max(tx.history_avg_inr, 1):.0f}x this card's average (₹{tx.history_avg_inr:,.0f})", self.UNUSUAL_AMOUNT))
            if tx.history_count > 0 and tx.country.upper() != tx.home_country and tx.country.upper() not in tx.seen_countries:
                factors.append(Factor("new_country", f"First transaction on this card in {tx.country.upper()} (home: {tx.home_country})", self.NEW_COUNTRY))
            if tx.history_count >= self.MIN_HISTORY + 2 and not tx.seen_merchant:
                factors.append(Factor("new_merchant", "Merchant not seen before on this card", self.NEW_MERCHANT))
            km = haversine_km(tx.last_city, tx.city)
            if km is not None and tx.hours_since_last is not None and km >= self.MIN_KM:
                speed = km / max(tx.hours_since_last, 1 / 60)
                if speed > self.MAX_KMH:
                    factors.append(Factor("impossible_travel", f"{tx.last_city} to {tx.city} ({km:.0f} km) in {tx.hours_since_last * 60:.0f} min", self.IMPOSSIBLE_TRAVEL))
        raw = round(sum(f.points for f in factors), 3)
        if raw > 1.0:  # keep the explanation additive: factors always sum to the reported score
            factors.append(Factor("score_cap", "Score capped at 1.0", round(1.0 - raw, 3)))
        return ScoreResult(min(1.0, raw), factors, self.version)


class HybridScorer:
    """Rules always run. When the input carries benchmark features and an active model is loaded, the model's
    fraud probability is combined with the rule score as a noisy-OR: 1 - (1 - rules) * (1 - p)."""

    def __init__(self, rules: HeuristicScorer, model_service) -> None:
        self.rules, self.models = rules, model_service

    @property
    def version(self) -> str:
        return self.rules.version

    def score(self, tx: ScoringInput, cfg: RiskConfig) -> ScoreResult:
        base = self.rules.score(tx, cfg)
        if tx.anon_features is None:
            return base
        pred = self.models.predict(tx.anon_features, tx.amount_raw)
        if pred is None:  # no active model or ML unavailable: safe fallback to rules only
            return base
        p, model_id, label = pred
        combined = round(min(1.0, 1 - (1 - base.score) * (1 - p)), 3)
        factors = [*base.factors, Factor("ml_model", f"ML model fraud probability {p:.3f} ({label})", round(combined - base.score, 3))]
        return ScoreResult(combined, factors, f"{base.version}+{label}", model_id)


def decide(score: float, cfg: RiskConfig) -> str:
    """Boundaries are inclusive on the lower decision: score == approve_max is APPROVE, == hold_max is HOLD."""
    if score <= cfg.approve_max:
        return "APPROVE"
    return "HOLD" if score <= cfg.hold_max else "DECLINE"
