"""Deterministic SYNTHETIC demo data for an Indian card portfolio, labelled source='SEED'.

Names, cities and phone numbers are invented. Merchant and bank names are used only as illustrative labels for a classroom demo;
no affiliation or real data is implied. The data goes through the real scoring/alert/notification code paths.
"""
from __future__ import annotations

import random
import re
import sqlite3
from datetime import timedelta

from app.db.session import transaction
from app.repositories import db_access as repo

from . import notifications_service, transactions_service as txs
from .common import iso, now_dt
from .scoring import HeuristicScorer

CUSTOMERS = [  # name, city, state
    ("Aarav Sharma", "Delhi", "Delhi"), ("Priya Nair", "Kochi", "Kerala"), ("Rohan Mehta", "Mumbai", "Maharashtra"), ("Ananya Iyer", "Chennai", "Tamil Nadu"),
    ("Vikram Singh", "Jaipur", "Rajasthan"), ("Sneha Kulkarni", "Pune", "Maharashtra"), ("Arjun Reddy", "Hyderabad", "Telangana"), ("Meera Banerjee", "Kolkata", "West Bengal"),
    ("Karan Malhotra", "Gurugram", "Haryana"), ("Ishita Gupta", "Lucknow", "Uttar Pradesh"), ("Rahul Verma", "Noida", "Uttar Pradesh"), ("Divya Patel", "Ahmedabad", "Gujarat"),
    ("Siddharth Rao", "Bengaluru", "Karnataka"), ("Kavya Menon", "Bengaluru", "Karnataka"),
]
ISSUERS = ["HDFC Bank", "SBI Card", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank"]
NETWORKS = ["Visa", "Mastercard", "RuPay"]
# name, MCC, label, city, risk, typical amount range in INR
MERCHANTS = [
    ("Swiggy", "5812", "Restaurants and food delivery", "Bengaluru", "LOW", (180, 1200)), ("Zomato", "5812", "Restaurants and food delivery", "Gurugram", "LOW", (200, 1500)),
    ("BigBasket", "5411", "Grocery", "Bengaluru", "LOW", (400, 3500)), ("Reliance Smart", "5411", "Grocery", "Mumbai", "LOW", (300, 4000)),
    ("IRCTC", "4112", "Railways", "Delhi", "LOW", (350, 4500)), ("MakeMyTrip", "4722", "Travel agencies", "Gurugram", "MEDIUM", (2500, 18000)),
    ("IndiGo", "4511", "Airlines", "Gurugram", "MEDIUM", (3500, 15000)), ("Flipkart", "5311", "Online marketplace", "Bengaluru", "MEDIUM", (500, 9000)),
    ("Amazon India", "5399", "Online marketplace", "Bengaluru", "MEDIUM", (400, 12000)), ("Croma", "5732", "Electronics", "Mumbai", "MEDIUM", (3000, 40000)),
    ("Myntra", "5651", "Apparel", "Bengaluru", "MEDIUM", (600, 6000)), ("Nykaa", "5977", "Beauty", "Mumbai", "LOW", (350, 4000)),
    ("Apollo Pharmacy", "5912", "Pharmacy", "Chennai", "LOW", (120, 2500)), ("Indian Oil", "5541", "Fuel", "Delhi", "LOW", (500, 4000)),
    ("BookMyShow", "7832", "Cinema and events", "Mumbai", "LOW", (250, 3000)), ("Jio Recharge", "4814", "Telecom", "Mumbai", "LOW", (149, 999)),
    ("Tanishq", "5944", "Jewellery", "Mumbai", "HIGH", (20000, 150000)), ("GiftCard Hub (demo)", "5999", "Gift cards", "Delhi", "HIGH", (3000, 25000)),
]
HOME_BY_CITY = {c: (n, s) for n, c, s in CUSTOMERS}


def seed_demo_data(conn: sqlite3.Connection) -> None:
    rng, scorer = random.Random(20261022), HeuristicScorer()
    start = now_dt().replace(microsecond=0) - timedelta(days=13)
    with transaction(conn):
        for name, code, label, city, risk, _ in MERCHANTS:
            repo.insert_merchant(conn, name, code, label, city, risk)
        cards: list[dict] = []
        for i, (name, city, state) in enumerate(CUSTOMERS):
            first = name.split()[0].lower()
            phone = f"+91 {rng.choice('6789')}{rng.randrange(10**4):04d} {rng.randrange(10**5):05d}"
            cid = repo.insert_customer(conn, name, f"{first}.{i}@example.com", phone, city, state, iso(start))
            token = f"SYNTH-IN-{1001 + i}"
            repo.insert_card(conn, token, cid, rng.choice(NETWORKS), rng.choice(ISSUERS), "CREDIT", f"{rng.randrange(1, 13):02d}/{rng.randrange(27, 32)}", rng.choice([75000, 100000, 150000, 300000]))
            cards.append({"token": token, "city": city, "name": name})

    events: list[tuple] = []  # (when, token, amount, merchant, country, city, channel)
    cheap = [m for m in MERCHANTS if m[5][1] <= 6000]
    for c in cards:
        for _ in range(rng.randint(6, 9)):  # ordinary behaviour at home
            m = rng.choice(cheap)
            when = start + timedelta(minutes=rng.randrange(0, 13 * 24 * 60))
            events.append((when, c["token"], float(round(rng.uniform(*m[5]), 0)), m[0], "IN", c["city"], "ONLINE" if m[0] in ("Swiggy", "Zomato", "BigBasket", "Flipkart", "Amazon India", "Myntra", "Nykaa", "Jio Recharge", "IRCTC", "MakeMyTrip", "IndiGo", "BookMyShow") else rng.choice(["POS", "POS", "WALLET"])))
    base = start + timedelta(days=9)  # fraud-like scenarios, recent enough to stay open
    s = cards
    events += [
        (base + timedelta(hours=1), s[0]["token"], 1450.0, "Indian Oil", "IN", "Delhi", "POS"),
        (base + timedelta(hours=1, minutes=25), s[0]["token"], 8200.0, "Croma", "IN", "Mumbai", "POS"),  # impossible travel
        (base + timedelta(hours=5), s[1]["token"], 96000.0, "GiftCard Hub (demo)", "AE", "Dubai", "ONLINE"),  # foreign, high, new country
        (base + timedelta(hours=7), s[2]["token"], 68500.0, "Tanishq", "IN", "Mumbai", "POS"),  # high amount
        (base + timedelta(days=1), s[3]["token"], 52000.0, "Flipkart", "IN", "Chennai", "ONLINE"),  # unusual vs average, high
        (base + timedelta(days=1, hours=3), s[4]["token"], 4100.0, "Unknown Online Store", "XX", None, "ONLINE"),  # blocked country
    ]
    for k in range(6):  # velocity burst on one card
        events.append((base + timedelta(days=2, minutes=7 * k), s[5]["token"], float(rng.randrange(900, 2400)), rng.choice(["Amazon India", "Flipkart", "Myntra"]), "IN", "Pune", "ONLINE"))
    events += [
        (base + timedelta(days=2, hours=6), s[6]["token"], 130000.0, "Tanishq", "SG", "Singapore", "POS"),
        (base + timedelta(days=3, hours=2), s[7]["token"], 15500.0, "MakeMyTrip", "US", "New York", "ONLINE"),
        (base + timedelta(days=3, hours=9), s[8]["token"], 74000.0, "Croma", "IN", "Gurugram", "ONLINE"),
    ]
    events += [  # older incidents so the demo has resolved cases and review outcomes
        (start + timedelta(days=2, hours=3), s[9]["token"], 88000.0, "Croma", "IN", "Lucknow", "ONLINE"),
        (start + timedelta(days=3, hours=1), s[10]["token"], 5200.0, "Unknown Online Store", "XX", None, "ONLINE"),
        (start + timedelta(days=4, hours=2), s[11]["token"], 61000.0, "Tanishq", "IN", "Ahmedabad", "POS"),
        (start + timedelta(days=5), s[12]["token"], 120000.0, "GiftCard Hub (demo)", "AE", "Dubai", "ONLINE"),
        (start + timedelta(days=6), s[13]["token"], 54000.0, "Amazon India", "IN", "Bengaluru", "ONLINE"),
        (start + timedelta(days=6, hours=2), s[2]["token"], 3100.0, "Unknown Online Store", "KP", None, "ONLINE"),
    ]
    events.sort(key=lambda e: e[0])

    ids: list[tuple[int, tuple]] = []
    for ev in events:
        when, token, amount, merchant, country, city, channel = ev
        out = txs.ingest(conn, txs.NewTx(token, amount, "INR", merchant, country, channel, city, source="SEED"), scorer, "seed", at=when)
        ids.append((out["id"], ev))

    cutoff = now_dt() - timedelta(days=4)
    for tx_id, ev in ids:  # cardholder replies and analyst verdicts for older alerts; the newest stay OPEN
        tx = repo.get_transaction(conn, tx_id)
        if not tx["has_alert"] or ev[0] >= cutoff:
            continue
        row = conn.execute("SELECT body FROM notifications WHERE txn_id=? AND kind='fraud_alert'", (tx_id,)).fetchone()
        m = re.search(r"/confirm/(\S+)$", row["body"]) if row else None
        if m and rng.random() < 0.4:
            notifications_service.record_reply(conn, m.group(1), "NOT_ME" if tx["decision"] == "DECLINE" or rng.random() < 0.5 else "LEGIT", at=ev[0] + timedelta(minutes=30))
        if rng.random() < 0.85:
            fraud = tx["decision"] == "DECLINE" or "impossible" in " ".join(tx["reasons"]).lower() or rng.random() < 0.3
            txs.review(conn, tx_id, "CONFIRMED_FRAUD" if fraud else "FALSE_POSITIVE", None, "seed", at=ev[0] + timedelta(hours=2))
    with transaction(conn):
        repo.insert_audit(conn, iso(now_dt()), "system", "demo_data_seeded", {"customers": len(CUSTOMERS), "transactions": len(events), "note": "synthetic demo data"}, "seed")
        repo.set_meta(conn, "seeded", "1")
