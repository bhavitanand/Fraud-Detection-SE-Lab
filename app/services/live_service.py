"""Live mode: a background engine that streams simulated Indian card transactions through the real pipeline.

Everything goes through transactions_service.ingest (same scoring, alerts, notifications, audit as the API).
A simulated cardholder answers alerts, and autopilot_service acts on the answers. Ground-truth labels stay in sim_label
so the dashboard can report precision and recall of the *simulation*; these are not real-world accuracy figures.

The simulated clock starts `days` in the past, replays a short warm-up of genuine history, then streams forward and stops
when it catches up with the real clock.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import random
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from app.core.errors import Conflict
from app.db.session import connect, transaction
from app.repositories import db_access as repo
from ml import simulator as sim

from . import autopilot_service, notifications_service
from .common import iso, now_dt
from .transactions_service import IST, NewTx, ingest

log = logging.getLogger("fraud.live")
SOURCE = "SIM"
REPLY_RE = re.compile(r"/confirm/(\S+)")


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=IST).astimezone(timezone.utc)


class LiveEngine:
    def __init__(self, db_path, scorer) -> None:
        self.db_path, self.scorer = db_path, scorer
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.feed: deque = deque(maxlen=60)
        self.reset_stats()

    # ---- state ----
    def reset_stats(self) -> None:
        self.stats = dict(state="idle", run="", processed=0, approved=0, held=0, declined=0, gate_rejected_fraud=0, gate_rejected_genuine=0,
                          gate_fraud_inr=0.0, replies=0, auto_blocked=0, sim_time=None, sim_end=None, rate=0.0, cards=0, started_at=None, error=None, warmup_total=0)
        self.feed.clear()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        with self._lock:
            return {**self.stats, "running": self.running, "feed": list(self.feed)[::-1][:25]}

    # ---- control ----
    def start(self, cards: int = 150, rate: float = 3.0, days: int = 30, fraud_boost: float = 3.0, seed: int | None = None, autopilot: bool = True, actor: str = "system") -> dict:
        if self.running:
            raise Conflict("Live mode is already running.", code="already_running")
        cards, days = max(20, min(cards, 600)), max(8, min(days, 120))
        rate = max(0.5, min(rate, 25.0))
        self._stop.clear()
        self.reset_stats()
        run = f"L{int(time.time()) % 100000:05d}"
        with self._lock:
            self.stats.update(state="starting", run=run, rate=rate, cards=cards, started_at=iso(now_dt()))
        conn = connect(self.db_path)
        try:
            if autopilot != autopilot_service.enabled(conn):
                autopilot_service.set_enabled(conn, autopilot, actor)
            with transaction(conn):
                repo.set_config(conn, "live_run", run)
        finally:
            conn.close()
        self._thread = threading.Thread(target=self._main, args=(run, cards, rate, days, fraud_boost, seed), daemon=True, name="live-engine")
        self._thread.start()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        with self._lock:
            if self.stats["state"] in ("running", "warming", "starting"):
                self.stats["state"] = "stopped"
        return self.status()

    # ---- engine ----
    def _register(self, conn: sqlite3.Connection, population: list[sim.SimCard]) -> None:
        stamp = iso(now_dt())
        with transaction(conn):
            for m in sim.MERCHANTS:
                row = conn.execute("SELECT id FROM merchants WHERE name=?", (m[0],)).fetchone()
                if row is None:
                    repo.insert_merchant(conn, m[0], m[2], m[1], m[8] or "Online", m[3])
            for c in population:
                cust = repo.insert_customer(conn, c.name, c.email, c.phone, c.home_city, c.state, stamp)
                repo.insert_card(conn, c.token, cust, c.network, c.issuer, "CREDIT", "12/29", float(c.credit_limit))

    def _push_event(self, text: str, level: str = "info", **extra) -> None:
        with self._lock:
            self.feed.append({"at": iso(now_dt()), "text": text, "level": level, **extra})

    def _main(self, run: str, n_cards: int, rate: float, days: int, boost: float, seed: int | None) -> None:
        conn = connect(self.db_path)
        try:
            rng = random.Random(seed if seed is not None else int(time.time()))
            population = sim.make_population(n_cards, rng, "S" + run, 0)
            self._register(conn, population)
            states = {c.idx: sim.CardState() for c in population}
            now_ist = datetime.now(IST).replace(tzinfo=None)
            start = now_ist - timedelta(days=days)
            warm_end = start + timedelta(days=6)
            heap: list = []
            seq = itertools.count()
            by_idx = {c.idx: c for c in population}
            for c in population:
                heapq.heappush(heap, (start + timedelta(hours=rng.uniform(0, 24 / c.activity)), next(seq), "gen", c.idx, None))
                t_f = start + timedelta(days=rng.expovariate(sim.FRAUD_EPISODE_PER_CARD_DAY * boost))
                heapq.heappush(heap, (t_f, next(seq), "fraud_start", c.idx, None))
            with self._lock:
                self.stats.update(state="warming", sim_end=iso(now_ist.replace(tzinfo=timezone.utc)))
            t0, n_done = time.perf_counter(), 0
            while heap and not self._stop.is_set():
                t, _, kind, idx, payload = heapq.heappop(heap)
                if t >= now_ist:
                    break
                card = by_idx[idx]
                warm = t < warm_end
                with self._lock:
                    if not warm and self.stats["state"] == "warming":
                        self.stats["state"] = "running"
                    self.stats["sim_time"] = iso(t.replace(tzinfo=timezone.utc))
                if kind == "gen":
                    ev = sim.genuine_event(card, t, rng)
                    gap = timedelta(days=rng.expovariate(card.activity))
                    nxt = t + max(gap, timedelta(minutes=5))
                    nxt = nxt.replace(hour=sim._hour(rng), minute=rng.randrange(60)) if nxt.date() > t.date() else nxt
                    heapq.heappush(heap, (max(nxt, t + timedelta(minutes=5)), next(seq), "gen", idx, None))
                    self._process(conn, card, states[idx], ev, heap, seq, rng, warm)
                elif kind == "fraud_start":
                    nxt = t + timedelta(days=rng.expovariate(sim.FRAUD_EPISODE_PER_CARD_DAY * boost))
                    heapq.heappush(heap, (nxt, next(seq), "fraud_start", idx, None))
                    if not warm:
                        for ev in sim.fraud_episode(card, t, rng):
                            heapq.heappush(heap, (ev.t, next(seq), "fraud_tx", idx, ev))
                elif kind == "fraud_tx":
                    self._process(conn, card, states[idx], payload, heap, seq, rng, warm)
                elif kind == "reply":
                    self._reply(conn, t, payload, rng, heap, seq, card)
                elif kind == "reissue":
                    self._reissue(conn, t, card)
                if not warm:  # throttle: only the streaming phase is paced
                    n_done += 1
                    due = t0 + n_done / rate
                    delay = due - time.perf_counter()
                    if delay > 0:
                        self._stop.wait(delay)
            with self._lock:
                if self.stats["state"] != "stopped":
                    self.stats["state"] = "stopped" if self._stop.is_set() else "completed"
            self._push_event("Simulation finished" if not self._stop.is_set() else "Simulation stopped", "info")
        except Exception as exc:  # keep the app alive; surface the error in the status
            log.exception("live engine crashed")
            with self._lock:
                self.stats.update(state="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            conn.close()

    def _process(self, conn, card, st, ev, heap, seq, rng, warm: bool) -> None:
        tx = NewTx(card.token, ev.amount, "INR", ev.merchant, ev.country, ev.channel, ev.city, source=SOURCE, sim_label=ev.label, sim_pattern=ev.pattern)
        at = _utc(ev.t)
        try:
            out = ingest(conn, tx, self.scorer, "live-engine", at)
        except Conflict:  # card already blocked: the transaction is refused at the gate
            with self._lock:
                key = "gate_rejected_fraud" if ev.label else "gate_rejected_genuine"
                self.stats[key] += 1
                if ev.label:
                    self.stats["gate_fraud_inr"] += ev.amount
                self.stats["processed"] += 1
            self._push_event(f"Refused at the gate: ₹{ev.amount:,.0f} at {ev.merchant} (card {card.token[-4:]} is blocked)", "block", fraud=bool(ev.label))
            return
        sim.advance_state(st, ev)
        d = out["decision"]
        with self._lock:
            self.stats["processed"] += 1
            self.stats[{"APPROVE": "approved", "HOLD": "held", "DECLINE": "declined"}[d]] += 1
        if warm or d == "APPROVE":
            return
        blocked = repo.get_card(conn, card.token)["blocked"]
        if blocked:
            with self._lock:
                self.stats["auto_blocked"] += 1
            heapq.heappush(heap, (ev.t + timedelta(hours=24), next(seq), "reissue", card.idx, None))  # temporary block: the bank follows up within a day
        self._push_event(f"{d}: ₹{ev.amount:,.0f} at {ev.merchant}{' · ' + ev.city if ev.city else ''} · score {out['score']:.2f}" + (" · card auto-blocked" if blocked else ""),
                         "decline" if d == "DECLINE" else "hold", fraud=bool(ev.label), tx_id=out["id"])
        # the simulated cardholder answers some alerts after a delay
        p_answer = 0.8 if ev.label else 0.6
        if rng.random() < 0.9 and out["alert_id"]:
            right = rng.random() > 0.03
            reply = ("NOT_ME" if ev.label else "LEGIT") if right else ("LEGIT" if ev.label else "NOT_ME")
            if rng.random() < p_answer + (0.15 if ev.label else 0.3):
                delay = timedelta(minutes=rng.uniform(2, 90))
                heapq.heappush(heap, (ev.t + delay, next(seq), "reply", card.idx, (out["id"], reply)))

    def _reissue(self, conn, t: datetime, card) -> None:
        with transaction(conn):
            when = iso(_utc(t))
            if repo.set_card_blocked(conn, card.token, False, "bank-ops", None, when):
                repo.insert_audit(conn, when, "bank-ops", "card_unblocked", {"token": card.token, "reason": "replacement card issued"}, f"card:{card.token}")
        self._push_event(f"Replacement card issued for card ending {card.token[-4:]}", "info")

    def _reply(self, conn, t: datetime, payload, rng, heap, seq, card) -> None:
        tx_id, reply = payload
        row = conn.execute("SELECT body FROM notifications WHERE txn_id=? AND kind='fraud_alert' ORDER BY id DESC LIMIT 1", (tx_id,)).fetchone()
        m = REPLY_RE.search(row["body"]) if row else None
        if not m:
            return
        try:
            notifications_service.record_reply(conn, m.group(1), reply, _utc(t))
        except Conflict:
            return
        with self._lock:
            self.stats["replies"] += 1
        if reply == "NOT_ME":  # the bank issues a replacement card within a day or two
            heapq.heappush(heap, (t + timedelta(hours=rng.uniform(12, 36)), next(seq), "reissue", card.idx, None))
        self._push_event(f"Cardholder replied {'"Not me"' if reply == 'NOT_ME' else '"Yes, it was me"'} on transaction #{tx_id}", "reply", tx_id=tx_id)


# ---- KPIs from simulation ground truth ----
def kpis(conn: sqlite3.Connection, run: str, gate_fraud: int = 0, gate_fraud_inr: float = 0.0, gate_genuine: int = 0) -> dict:
    like = f"S{run}-%" if run else "SIM-%"
    q = lambda sql, *a: conn.execute(sql, (like, *a)).fetchone()
    r = q("""SELECT count(*) n, sum(sim_label=1) frauds, sum(sim_label=1 AND decision!='APPROVE') tp, sum(sim_label=0 AND decision!='APPROVE') fp,
                    sum(sim_label=1 AND decision='DECLINE') f_decl, sum(sim_label=1 AND decision='HOLD') f_hold, sum(sim_label=1 AND decision='APPROVE') f_miss,
                    coalesce(sum(CASE WHEN sim_label=1 AND decision='DECLINE' THEN amount END),0) inr_declined,
                    coalesce(sum(CASE WHEN sim_label=1 AND decision='HOLD' THEN amount END),0) inr_held,
                    coalesce(sum(CASE WHEN sim_label=1 AND decision='APPROVE' THEN amount END),0) inr_missed,
                    avg(latency_ms) lat FROM transactions WHERE token LIKE ? AND source='SIM'""")
    n, frauds, tp, fp = (r["n"] or 0), (r["frauds"] or 0), (r["tp"] or 0), (r["fp"] or 0)
    lat = [x[0] for x in conn.execute("SELECT latency_ms FROM transactions WHERE token LIKE ? AND source='SIM' AND latency_ms IS NOT NULL ORDER BY latency_ms", (like,))]
    a = q("""SELECT count(*) total, sum(f.status='OPEN') open_n, sum(f.auto_resolved=1) auto_n, sum(f.status!='OPEN' AND f.auto_resolved=0) human_n
             FROM fraud_alerts f JOIN transactions t ON t.id=f.txn_id WHERE t.token LIKE ? AND t.source='SIM'""")
    total_alerts, open_n, auto_n = (a["total"] or 0), (a["open_n"] or 0), (a["auto_n"] or 0)
    all_frauds, caught = frauds + gate_fraud, tp + gate_fraud
    prevented = (r["inr_declined"] or 0) + gate_fraud_inr
    exposure = prevented + (r["inr_held"] or 0) + (r["inr_missed"] or 0)
    pct = lambda x, y: round(100 * x / y, 1) if y else None
    return {
        "transactions": n, "frauds": all_frauds, "frauds_caught": caught, "frauds_missed": r["f_miss"] or 0, "false_alarms": fp,
        "precision_pct": pct(tp, tp + fp), "recall_pct": pct(caught, all_frauds), "false_positive_rate_pct": round(100 * fp / max(n - (frauds), 1), 3) if n else None,
        "fraud_inr_prevented": round(prevented), "fraud_inr_held": round(r["inr_held"] or 0), "fraud_inr_missed": round(r["inr_missed"] or 0),
        "prevented_pct": pct(prevented, exposure),
        "alerts": total_alerts, "alerts_open": open_n, "alerts_auto_resolved": auto_n, "autonomy_pct": pct(total_alerts - open_n if total_alerts else 0, total_alerts) if False else pct(auto_n, total_alerts),
        "human_queue": open_n,
        "avg_latency_ms": round(r["lat"], 2) if r["lat"] else None, "p95_latency_ms": round(lat[int(len(lat) * 0.95) - 1], 2) if len(lat) > 20 else None,
        "note": "Computed from simulation ground truth. Not real-world accuracy.",
    }
