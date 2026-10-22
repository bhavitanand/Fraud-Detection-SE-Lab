"""Static reference data for the India-focused demo: cities, indicative FX rates, distance."""
from __future__ import annotations

import math

# name -> (latitude, longitude, ISO country)
CITIES: dict[str, tuple[float, float, str]] = {
    "Delhi": (28.61, 77.21, "IN"), "Gurugram": (28.46, 77.03, "IN"), "Noida": (28.54, 77.39, "IN"), "Mumbai": (19.08, 72.88, "IN"),
    "Pune": (18.52, 73.86, "IN"), "Bengaluru": (12.97, 77.59, "IN"), "Chennai": (13.08, 80.27, "IN"), "Hyderabad": (17.39, 78.49, "IN"),
    "Kolkata": (22.57, 88.36, "IN"), "Ahmedabad": (23.02, 72.57, "IN"), "Jaipur": (26.91, 75.79, "IN"), "Lucknow": (26.85, 80.95, "IN"),
    "Kochi": (9.93, 76.27, "IN"), "Chandigarh": (30.73, 76.78, "IN"), "Dubai": (25.20, 55.27, "AE"), "Singapore": (1.35, 103.82, "SG"),
    "London": (51.51, -0.13, "GB"), "New York": (40.71, -74.01, "US"), "Bangkok": (13.76, 100.50, "TH"),
}

# Fixed, indicative rates used only to compare amounts with INR thresholds. Not live FX.
FX_TO_INR: dict[str, float] = {"INR": 1.0, "USD": 83.0, "EUR": 90.0, "GBP": 105.0, "AED": 22.6, "SGD": 62.0}


def to_inr(amount: float, currency: str) -> float:
    return amount * FX_TO_INR.get(currency, 1.0)


def haversine_km(a: str | None, b: str | None) -> float | None:
    if not a or not b or a not in CITIES or b not in CITIES:
        return None
    (la1, lo1, _), (la2, lo2, _) = CITIES[a], CITIES[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371.0 * math.asin(math.sqrt(h)), 1)
