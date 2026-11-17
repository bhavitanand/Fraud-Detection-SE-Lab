"""Feature engineering for the live (India) fraud model. One function is used for BOTH training and live scoring, so there is no train/serve skew.

All inputs come from a ScoringInput, i.e. exactly what the pipeline knows about a card and a transaction at decision time.
"""
from __future__ import annotations

import math

from app.services.geo import CITIES, haversine_km

FEATURES = [
    "log_amount", "amount_vs_avg", "amount_vs_limit", "is_online", "is_pos", "is_atm", "hour_sin", "hour_cos", "is_night", "prior_tx_24h", "history_len",
    "is_foreign", "new_country", "new_merchant", "km_from_last", "hours_since_last", "speed_kmh", "merchant_risk", "location_known",
]
# Human-readable groups used for explanations. Each group lists the feature names that are neutralised together.
GROUPS: dict[str, list[str]] = {
    "Transaction amount": ["log_amount"],
    "Amount compared with the card's usual spend": ["amount_vs_avg"],
    "Amount compared with the credit limit": ["amount_vs_limit"],
    "Channel (online / in-store / ATM)": ["is_online", "is_pos", "is_atm"],
    "Time of day": ["hour_sin", "hour_cos", "is_night"],
    "Transactions on this card in the last 24 hours": ["prior_tx_24h"],
    "Length of card history": ["history_len"],
    "Foreign or new country": ["is_foreign", "new_country"],
    "Merchant never used before on this card": ["new_merchant"],
    "Distance, speed and time since the last transaction": ["km_from_last", "hours_since_last", "speed_kmh"],
    "Merchant risk level": ["merchant_risk"],
    "Location available": ["location_known"],
}


def vectorize(tx) -> list[float]:
    """ScoringInput -> feature vector (same order as FEATURES)."""
    avg = tx.history_avg_inr
    amount_vs_avg = math.log1p(min(tx.amount_inr / max(avg, 300.0), 200.0)) if tx.history_count >= 1 else 0.0
    amount_vs_limit = min(tx.amount_inr / tx.credit_limit, 2.0) if tx.credit_limit > 0 else 0.0
    hrs = tx.hours_since_last
    km = haversine_km(tx.last_city, tx.city)
    speed = (km / max(hrs, 1 / 60)) if (km is not None and hrs is not None) else 0.0
    country = tx.country.upper()
    ang = 2 * math.pi * tx.hour / 24.0
    return [
        math.log1p(tx.amount_inr), amount_vs_avg, amount_vs_limit,
        1.0 if tx.channel == "ONLINE" else 0.0, 1.0 if tx.channel == "POS" else 0.0, 1.0 if tx.channel == "ATM" else 0.0,
        math.sin(ang), math.cos(ang), 1.0 if (tx.hour < 5 or tx.hour == 23) else 0.0,
        float(min(tx.prior_tx_24h, 15)), math.log1p(tx.history_count),
        1.0 if country != tx.home_country else 0.0,
        1.0 if (tx.history_count > 0 and country != tx.home_country and country not in tx.seen_countries) else 0.0,
        1.0 if (tx.history_count >= 1 and not tx.seen_merchant) else 0.0,
        min(km or 0.0, 3000.0) / 1000.0, math.log1p(hrs) if hrs is not None else math.log1p(72.0), min(speed, 2000.0) / 1000.0,
        float(tx.merchant_risk), 1.0 if (tx.city in CITIES) else 0.0,
    ]
