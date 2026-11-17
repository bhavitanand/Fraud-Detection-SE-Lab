"""Synthetic Indian card-transaction simulator with ground-truth fraud labels.

Why it exists: the only large public labelled dataset (ULB, 2013) has anonymised PCA columns, so a model trained on it cannot use merchant,
city, channel or card history, which are exactly the signals the live Fraud Desk pipeline has. This simulator produces transactions with
those fields for Indian cardholders, plus realistic *hard negatives* (genuine trips, festive jewellery purchases, big online buys, bursts) and
*hard positives* (low-and-slow fraud that looks like normal spending), so detection is neither trivial nor impossible.

It is used in two places with the same event logic:
  * offline, to build a labelled training set (ml/train_india.py);
  * online, by the live demo engine (app/services/live_service.py), which streams events through the real scoring pipeline.

Everything here is synthetic. Fraud prevalence (about 1.2% of transactions) is set for learnability and is higher than real-world rates.
Metrics measured on simulated data describe how well the system finds the *simulated* fraud patterns, not real-world fraud.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.geo import CITIES

INDIAN_CITIES = [c for c, v in CITIES.items() if v[2] == "IN"]
FOREIGN_CITIES = [c for c, v in CITIES.items() if v[2] != "IN"]

# name, category label, MCC, risk, online probability, median amount (INR), sigma (lognormal), popularity, city (None = online brand)
MERCHANTS: list[tuple] = [
    ("Swiggy", "Restaurants and food delivery", "5812", "LOW", 0.97, 420, 0.5, 9, None), ("Zomato", "Restaurants and food delivery", "5812", "LOW", 0.97, 480, 0.5, 8, None),
    ("Blinkit", "Grocery", "5411", "LOW", 1.0, 520, 0.5, 6, None), ("BigBasket", "Grocery", "5411", "LOW", 0.95, 1400, 0.5, 6, None),
    ("DMart", "Grocery", "5411", "LOW", 0.0, 2100, 0.6, 7, None), ("Reliance Smart", "Grocery", "5411", "LOW", 0.0, 1800, 0.6, 5, None),
    ("Uber India", "Transport", "4121", "LOW", 1.0, 340, 0.5, 7, None), ("Ola", "Transport", "4121", "LOW", 1.0, 290, 0.5, 5, None),
    ("IRCTC", "Railways", "4112", "LOW", 1.0, 1100, 0.7, 4, None), ("Indian Oil", "Fuel", "5541", "LOW", 0.0, 1700, 0.5, 6, None),
    ("HPCL", "Fuel", "5541", "LOW", 0.0, 1600, 0.5, 4, None), ("Bharat Petroleum", "Fuel", "5541", "LOW", 0.0, 1650, 0.5, 4, None),
    ("MakeMyTrip", "Travel agencies", "4722", "MEDIUM", 1.0, 7200, 0.7, 3, None), ("IndiGo", "Airlines", "4511", "MEDIUM", 1.0, 6800, 0.6, 3, None),
    ("Air India", "Airlines", "4511", "MEDIUM", 1.0, 9400, 0.6, 2, None), ("Flipkart", "Online marketplace", "5311", "MEDIUM", 1.0, 1900, 0.9, 8, None),
    ("Amazon India", "Online marketplace", "5399", "MEDIUM", 1.0, 1700, 0.9, 9, None), ("Myntra", "Apparel", "5651", "MEDIUM", 1.0, 1900, 0.6, 5, None),
    ("Ajio", "Apparel", "5651", "MEDIUM", 1.0, 1700, 0.6, 3, None), ("Nykaa", "Beauty", "5977", "LOW", 1.0, 1300, 0.6, 3, None),
    ("Meesho", "Online marketplace", "5311", "MEDIUM", 1.0, 700, 0.6, 3, None), ("Croma", "Electronics", "5732", "MEDIUM", 0.35, 14500, 1.0, 2, None),
    ("Reliance Digital", "Electronics", "5732", "MEDIUM", 0.2, 13500, 1.0, 2, None), ("Vijay Sales", "Electronics", "5732", "MEDIUM", 0.1, 12000, 1.0, 1, None),
    ("Tanishq", "Jewellery", "5944", "HIGH", 0.05, 42000, 0.9, 1, None), ("Kalyan Jewellers", "Jewellery", "5944", "HIGH", 0.0, 38000, 0.9, 1, None),
    ("Apollo Pharmacy", "Pharmacy", "5912", "LOW", 0.1, 650, 0.8, 5, None), ("MedPlus", "Pharmacy", "5912", "LOW", 0.1, 480, 0.8, 3, None),
    ("Jio Recharge", "Telecom", "4814", "LOW", 1.0, 359, 0.5, 6, None), ("Airtel", "Telecom", "4814", "LOW", 1.0, 449, 0.5, 4, None),
    ("Tata Power", "Utilities", "4900", "LOW", 1.0, 1900, 0.6, 3, None), ("BookMyShow", "Cinema and events", "7832", "LOW", 1.0, 700, 0.6, 3, None),
    ("Netflix India", "Subscriptions", "4899", "LOW", 1.0, 649, 0.3, 2, None), ("Spotify India", "Subscriptions", "4899", "LOW", 1.0, 119, 0.3, 2, None),
    ("ATM Cash Withdrawal", "Cash withdrawal", "6011", "MEDIUM", 0.0, 6500, 0.6, 3, None),
    ("GiftCard Hub (demo)", "Gift cards", "5999", "HIGH", 1.0, 9000, 0.9, 0, None), ("Paytm Wallet Top-up", "Wallet load", "6540", "HIGH", 1.0, 6000, 0.8, 0, None),
    ("Unknown Online Store", "Unclassified online", "5999", "HIGH", 1.0, 5200, 1.0, 0, None), ("QuickDeals Online (demo)", "Unclassified online", "5999", "HIGH", 1.0, 4200, 1.0, 0, None),
    ("LuckyBazaar (demo)", "Gaming and betting", "7995", "HIGH", 1.0, 3600, 1.0, 0, None),
]
M_BY_NAME = {m[0]: m for m in MERCHANTS}
M_RISK = {m[0]: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[m[3]] for m in MERCHANTS}
POPULAR = [m for m in MERCHANTS if m[7] > 0]
FRAUD_TARGETS_ONLINE = ["Croma", "Reliance Digital", "GiftCard Hub (demo)", "Paytm Wallet Top-up", "Unknown Online Store", "QuickDeals Online (demo)",
                        "LuckyBazaar (demo)", "MakeMyTrip", "Air India", "Flipkart", "Amazon India"]
FRAUD_TARGETS_POS = ["Tanishq", "Kalyan Jewellers", "Croma", "Reliance Digital", "Vijay Sales", "ATM Cash Withdrawal"]
HOUR_W = [1, 0.6, 0.4, 0.3, 0.3, 0.6, 1.5, 3, 4.5, 5, 5.5, 6, 6.5, 6, 5.5, 5.5, 6, 6.5, 7.5, 8, 8, 6.5, 4, 2]

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Vikram", "Siddharth", "Rahul", "Amit", "Priya", "Ananya", "Sneha", "Kavya", "Meera", "Ishita",
         "Divya", "Neha", "Pooja", "Riya", "Aisha", "Tanvi", "Nikhil", "Manish", "Deepak", "Suresh", "Lakshmi", "Sunita", "Anjali", "Harsh"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Patel", "Nair", "Iyer", "Reddy", "Rao", "Menon", "Kulkarni", "Banerjee", "Mehta", "Malhotra", "Joshi", "Das",
        "Chopra", "Kapoor", "Bhatia", "Saxena"]
ISSUERS = ["HDFC Bank", "SBI Card", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank"]
NETWORKS = ["Visa", "Mastercard", "RuPay"]
FRAUD_PATTERNS = ["card_testing", "account_takeover", "cross_border", "stolen_physical", "night_spree", "low_and_slow"]
FRAUD_W = [0.22, 0.28, 0.16, 0.14, 0.08, 0.12]
FRAUD_EPISODE_PER_CARD_DAY = 0.0085  # tuned so about 1.2% of transactions are fraudulent


@dataclass
class SimEvent:
    t: datetime
    amount: float
    merchant: str
    country: str
    city: str | None
    channel: str
    label: int = 0
    pattern: str = "genuine"


@dataclass
class SimCard:
    idx: int
    token: str
    name: str
    home_city: str
    credit_limit: float
    activity: float  # genuine transactions per day
    spend_scale: float
    online_pref: float
    favorites: list[tuple]
    network: str = "Visa"
    issuer: str = "HDFC Bank"
    trip: tuple[str, str, datetime] | None = None  # (city, country, until)
    avg_amount: float = 1500.0
    last_t: datetime | None = None
    state: str = ""
    email: str = ""
    phone: str = ""

    def home_state(self) -> str:
        return self.state


STATE_OF = {"Delhi": "Delhi", "Gurugram": "Haryana", "Noida": "Uttar Pradesh", "Mumbai": "Maharashtra", "Pune": "Maharashtra", "Bengaluru": "Karnataka",
            "Chennai": "Tamil Nadu", "Hyderabad": "Telangana", "Kolkata": "West Bengal", "Ahmedabad": "Gujarat", "Jaipur": "Rajasthan", "Lucknow": "Uttar Pradesh",
            "Kochi": "Kerala", "Chandigarh": "Chandigarh"}
CITY_W = {"Delhi": 12, "Mumbai": 12, "Bengaluru": 11, "Hyderabad": 8, "Chennai": 7, "Kolkata": 6, "Pune": 7, "Gurugram": 6, "Noida": 5, "Ahmedabad": 5,
          "Jaipur": 4, "Lucknow": 4, "Kochi": 3, "Chandigarh": 3}


def make_population(n: int, rng: random.Random, token_prefix: str = "SIM", start_index: int = 0) -> list[SimCard]:
    cards = []
    cities, weights = list(CITY_W), list(CITY_W.values())
    for i in range(n):
        city = rng.choices(cities, weights)[0]
        favs = rng.sample(POPULAR, k=rng.randint(4, 7))
        weights_f = [m[7] * rng.uniform(0.5, 2.0) for m in favs]
        spend = math.exp(rng.gauss(0, 0.45))
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        idx = start_index + i
        c = SimCard(idx=idx, token=f"{token_prefix}-{idx + 1:05d}", name=name, home_city=city, credit_limit=rng.choice([50000, 75000, 100000, 150000, 300000, 500000]),
                    activity=max(0.4, min(4.5, math.exp(rng.gauss(0.3, 0.5)))), spend_scale=spend, online_pref=rng.betavariate(3, 2),
                    favorites=list(zip(favs, weights_f)), network=rng.choice(NETWORKS), issuer=rng.choice(ISSUERS), state=STATE_OF.get(city, ""))
        c.email = f"{name.split()[0].lower()}.{idx}@example.com"
        c.phone = f"+91 {rng.choice('6789')}{rng.randrange(10**4):04d} {rng.randrange(10**5):05d}"
        c.avg_amount = sum(m[5] * w for (m, w) in c.favorites) / sum(w for _, w in c.favorites) * spend
        cards.append(c)
    return cards


def _hour(rng: random.Random, night_bias: bool = False) -> int:
    if night_bias:
        return rng.choice([0, 1, 2, 3, 4, 23])
    return rng.choices(range(24), HOUR_W)[0]


def _at(day_start: datetime, rng: random.Random, hour: int | None = None) -> datetime:
    h = _hour(rng) if hour is None else hour
    return day_start.replace(hour=h, minute=rng.randrange(60), second=rng.randrange(60), microsecond=0)


def _amount(m: tuple, card: SimCard, rng: random.Random, mult: float = 1.0) -> float:
    base = m[5] * (card.spend_scale ** 0.6) * mult
    return float(max(10, round(base * math.exp(rng.gauss(0, m[6])), 0)))


def genuine_event(card: SimCard, t: datetime, rng: random.Random, festive: float = 0.015) -> SimEvent:
    """One ordinary transaction, including the legitimate oddities that make fraud detection hard (trips, festive big purchases, big online buys)."""
    if card.trip and t > card.trip[2]:
        card.trip = None
    if card.trip is None and rng.random() < 0.0035:  # genuine domestic trip
        card.trip = (rng.choice([c for c in INDIAN_CITIES if c != card.home_city]), "IN", t + timedelta(days=rng.randint(2, 5)))
    elif card.trip is None and rng.random() < 0.0012:  # genuine international trip
        fc = rng.choice(FOREIGN_CITIES)
        card.trip = (fc, CITIES[fc][2], t + timedelta(days=rng.randint(3, 8)))
    roll = rng.random()
    if roll < festive:  # festive jewellery / electronics purchase, a legitimate high-value POS payment
        m = M_BY_NAME[rng.choice(["Tanishq", "Kalyan Jewellers", "Croma", "Reliance Digital"])]
        amount, channel = float(round(m[5] * rng.uniform(0.8, 3.0), -2)), "POS"
    elif roll < festive + 0.01:  # big online purchase (phone, laptop)
        m = M_BY_NAME[rng.choice(["Amazon India", "Flipkart", "Croma"])]
        amount, channel = float(round(rng.uniform(30000, 95000), -2)), "ONLINE"
    else:
        pool = card.favorites if rng.random() < 0.78 else [(m, m[7]) for m in POPULAR]
        m = rng.choices([p[0] for p in pool], [p[1] for p in pool])[0]
        amount = _amount(m, card, rng)
        if m[0] == "ATM Cash Withdrawal":
            channel = "ATM"
        else:
            p_online = min(1.0, m[4] * (0.6 + card.online_pref * 0.8))
            channel = "ONLINE" if rng.random() < p_online else "POS"
    if card.trip:
        city, country = card.trip[0], card.trip[1]
        if country != "IN":
            amount = float(round(amount * 1.6, 0))
    else:
        city, country = card.home_city, "IN"
    card.avg_amount = 0.97 * card.avg_amount + 0.03 * amount
    return SimEvent(t, amount, m[0], country, city, channel)


def _pick_other_city(card: SimCard, rng: random.Random, min_km: float = 300.0) -> str:
    from app.services.geo import haversine_km
    far = [c for c in INDIAN_CITIES if (haversine_km(card.home_city, c) or 0) >= min_km]
    return rng.choice(far or [c for c in INDIAN_CITIES if c != card.home_city])


def fraud_episode(card: SimCard, t0: datetime, rng: random.Random, pattern: str | None = None) -> list[SimEvent]:
    """A short burst of fraudulent transactions on a card, starting at t0 (anchored after a genuine transaction)."""
    pattern = pattern or rng.choices(FRAUD_PATTERNS, FRAUD_W)[0]
    ev: list[SimEvent] = []
    t = t0
    avg = max(card.avg_amount, 400.0)

    def add(amount, merchant, country, city, channel):
        ev.append(SimEvent(t, float(round(amount, 0)), merchant, country, city, channel, 1, pattern))

    if pattern == "card_testing":
        city = rng.choice([None, card.home_city, rng.choice(INDIAN_CITIES)])
        for _ in range(rng.randint(2, 5)):
            add(rng.uniform(1, 300), rng.choice(["Unknown Online Store", "QuickDeals Online (demo)", "LuckyBazaar (demo)", "GiftCard Hub (demo)"]), "IN", city, "ONLINE")
            t += timedelta(seconds=rng.randint(40, 240))
        if rng.random() < 0.45:
            add(rng.uniform(5000, 40000), rng.choice(FRAUD_TARGETS_ONLINE), "IN", city, "ONLINE")
    elif pattern == "account_takeover":
        city = card.home_city if rng.random() < 0.4 else rng.choice(INDIAN_CITIES)
        t = t.replace(hour=_hour(rng, night_bias=rng.random() < 0.55))
        for _ in range(rng.randint(1, 3)):
            add(max(rng.uniform(15000, 150000), avg * rng.uniform(3, 12)), rng.choice(FRAUD_TARGETS_ONLINE), "IN", city, "ONLINE")
            t += timedelta(minutes=rng.randint(2, 30))
    elif pattern == "cross_border":
        fc = rng.choice(FOREIGN_CITIES)
        ch = "ONLINE" if rng.random() < 0.7 else "POS"
        for _ in range(rng.randint(1, 2)):
            add(rng.uniform(15000, 200000), rng.choice(FRAUD_TARGETS_ONLINE if ch == "ONLINE" else FRAUD_TARGETS_POS), CITIES[fc][2], fc, ch)
            t += timedelta(minutes=rng.randint(3, 40))
    elif pattern == "stolen_physical":
        city = _pick_other_city(card, rng)
        t += timedelta(minutes=rng.randint(20, 360))
        for _ in range(rng.randint(1, 3)):
            if rng.random() < 0.4:
                add(rng.uniform(10000, 40000), "ATM Cash Withdrawal", "IN", city, "ATM")
            else:
                add(rng.uniform(3000, 80000), rng.choice(FRAUD_TARGETS_POS[:5]), "IN", city, "POS")
            t += timedelta(minutes=rng.randint(5, 60))
    elif pattern == "night_spree":
        t = t.replace(hour=rng.choice([0, 1, 2, 3, 4]))
        for _ in range(rng.randint(2, 4)):
            add(rng.uniform(8000, 60000), rng.choice(FRAUD_TARGETS_POS[:5]), "IN", card.home_city, "POS")
            t += timedelta(minutes=rng.randint(4, 25))
    else:  # low_and_slow: looks like ordinary spending (hard to catch by design)
        m = rng.choice([x for x in POPULAR if x[0] not in [f[0][0] for f in card.favorites]] or POPULAR)
        add(_amount(m, card, rng, rng.uniform(1.0, 2.5)), m[0], "IN", card.home_city, "ONLINE")
    return ev


def generate_card_events(card: SimCard, start: datetime, days: int, rng: random.Random, fraud_scale: float = 1.0) -> list[SimEvent]:
    """All events (genuine + fraud episodes) for one card over [start, start + days), sorted by time."""
    out: list[SimEvent] = []
    t = start
    end = start + timedelta(days=days)
    while True:
        t += timedelta(seconds=rng.expovariate(card.activity / 86400.0))
        if t >= end:
            break
        # re-draw the clock time within the day so activity follows a daily rhythm without distorting the daily count
        tt = _at(t.replace(hour=0, minute=0, second=0), rng)
        g = genuine_event(card, tt, rng)
        out.append(g)
        if rng.random() < (FRAUD_EPISODE_PER_CARD_DAY / max(card.activity, 0.1)) * fraud_scale:
            out.extend(fraud_episode(card, tt + timedelta(minutes=rng.randint(15, 240)), rng))
    out.sort(key=lambda e: e.t)
    return out


# ---------------------------------------------------------------- offline dataset builder
@dataclass
class CardState:
    """Running history of a card, mirroring what the live pipeline reads from the database before scoring."""
    count: int = 0
    total: float = 0.0
    countries: set = field(default_factory=set)
    merchants: set = field(default_factory=set)
    last_t: datetime | None = None
    last_city: str | None = None
    recent: list = field(default_factory=list)


def build_scoring_input(card: SimCard, st: CardState, ev: SimEvent):
    from app.services.scoring import ScoringInput
    st.recent = [x for x in st.recent if x > ev.t - timedelta(hours=24)]
    hours = None if st.last_t is None else max((ev.t - st.last_t).total_seconds() / 3600, 0.0)
    return ScoringInput(
        amount_inr=ev.amount, country=ev.country, channel=ev.channel, prior_tx_24h=len(st.recent), home_country="IN", history_count=st.count,
        history_avg_inr=(st.total / st.count) if st.count else 0.0, seen_countries=frozenset(st.countries), seen_merchant=(ev.merchant in st.merchants) or st.count == 0,
        city=ev.city, last_city=st.last_city, hours_since_last=hours, rules_applicable=True, amount_raw=ev.amount,
        hour=ev.t.hour, merchant_risk=M_RISK.get(ev.merchant, 1), credit_limit=card.credit_limit)


def advance_state(st: CardState, ev: SimEvent) -> None:
    st.count += 1
    st.total += ev.amount
    st.countries.add(ev.country)
    st.merchants.add(ev.merchant)
    st.last_t, st.last_city = ev.t, ev.city
    st.recent.append(ev.t)


def build_dataset(n_cards: int, days: int, seed: int = 20261118, start: datetime | None = None):
    """Returns (rows, cards): rows is a list of (SimEvent, ScoringInput, card_index) in chronological order per card; use ev.t to split."""
    rng = random.Random(seed)
    start = start or datetime(2026, 1, 1)
    cards = make_population(n_cards, rng, "SIM")
    rows = []
    for c in cards:
        st = CardState()
        for ev in generate_card_events(c, start, days, rng):
            rows.append((ev, build_scoring_input(c, st, ev), c.idx))
            advance_state(st, ev)
    rows.sort(key=lambda r: r[0].t)
    return rows, cards
