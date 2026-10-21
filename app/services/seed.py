"""Deterministic SYNTHETIC demo data, labelled source='SEED'. Not evaluation data."""
from __future__ import annotations

import random
import sqlite3
from datetime import timedelta

from app.db.session import transaction
from app.repositories import db_access as repo

from .common import iso, now_dt
from .scoring import HeuristicScorer, RiskConfig, ScoringInput, decide

MERCHANTS = ["Corner Cafe", "Demo Market", "Demo Electronics", "Demo Travel", "Sample Fuel", "Test Pharmacy", "Mock Streaming", "Synthetic Books"]
COUNTRIES = ["US", "US", "US", "GB", "IN", "DE", "FR", "XX"]


def seed_demo_data(conn: sqlite3.Connection, count: int = 70) -> None:
    rng, scorer, cfg = random.Random(20261020), HeuristicScorer(), RiskConfig()
    start = now_dt() - timedelta(days=13)
    rows = []
    for i in range(count):
        token = f"SYNTH-{1001 + rng.randrange(18)}"
        amount = round(rng.choice([rng.uniform(5, 180), rng.uniform(5, 180), rng.uniform(30, 900), rng.uniform(1500, 4200)]), 2)
        channel = rng.choice(["POS", "ONLINE", "ONLINE", "ATM", "WALLET"])
        country = rng.choice(COUNTRIES)
        when = start + timedelta(minutes=int((i / count) * 13 * 24 * 60 + rng.randrange(0, 240)))
        prior = sum(1 for r in rows if r["token"] == token and when - r["when"] <= timedelta(hours=24))
        res = scorer.score(ScoringInput(amount, country, channel, prior), cfg)
        rows.append({"token": token, "amount": amount, "merchant": rng.choice(MERCHANTS), "country": country, "channel": channel,
                     "when": when, "res": res, "decision": decide(res.score, cfg)})
    with transaction(conn):
        ids = []
        for r in rows:
            factors = [f.as_dict() for f in r["res"].factors]
            ids.append(repo.insert_transaction(
                conn, token=r["token"], amount=r["amount"], merchant=r["merchant"], country=r["country"], channel=r["channel"],
                created=iso(r["when"]), score=r["res"].score, decision=r["decision"], reasons=[f["label"] for f in factors if f["code"] not in ("base", "score_cap")],
                factors=factors, scorer=r["res"].version, source="SEED", review="NOT_REQUIRED" if r["decision"] == "APPROVE" else "OPEN"))
            repo.ensure_card(conn, r["token"])
        # Review roughly half of the older alerts so the demo has outcomes; the newest alerts stay OPEN.
        cutoff = now_dt() - timedelta(days=3)
        blocked: set[str] = set()
        for tx_id, r in zip(ids, rows):
            if r["decision"] != "APPROVE" and r["when"] < cutoff and rng.random() < 0.55:
                verdict = "CONFIRMED_FRAUD" if rng.random() < (0.7 if r["decision"] == "DECLINE" else 0.35) else "FALSE_POSITIVE"
                repo.mark_reviewed(conn, tx_id, verdict, "seed", None, iso(r["when"] + timedelta(hours=2)))
                if verdict == "CONFIRMED_FRAUD" and r["token"] not in blocked and len(blocked) < 2:
                    blocked.add(r["token"])
                    repo.set_card_blocked(conn, r["token"], True, "seed", f"Confirmed fraud on transaction #{tx_id}", iso(r["when"] + timedelta(hours=2)))
        repo.insert_audit(conn, iso(now_dt()), "system", "demo_data_seeded", {"transactions": count, "note": "synthetic demo data"}, "seed")
        repo.set_meta(conn, "seeded", "1")
