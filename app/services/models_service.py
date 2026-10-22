"""Model registry workflow: list, deploy, retire, benchmark replay. Training happens offline (python -m ml.train)."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from app.core.errors import Conflict, NotFound
from app.db.session import transaction
from app.repositories import db_access as repo

from .common import now_iso
from .ml_service import ARTIFACTS_DIR, ModelService


def register_from_meta(conn: sqlite3.Connection, meta: dict, status: str = "candidate") -> int:
    t = meta["metrics"]["test"]["at_app_threshold"]
    with transaction(conn):
        mid = repo.insert_model(
            conn, name=meta["name"], version=meta["version"], algorithm=meta["algorithm"], artifact_file=meta["artifact_file"],
            artifact_sha256=meta["artifact_sha256"], pr_auc=meta["metrics"]["test"]["pr_auc"], precision_score=t["precision"], recall_score=t["recall"], f1_score=t["f1"],
            metrics_json=json.dumps(meta), status=status, trained_at=meta["trained_at"], registered_at=now_iso())
        repo.insert_audit(conn, now_iso(), "system", "model_registered", {"model_id": mid, "name": meta["name"], "status": status}, f"model:{mid}")
    return mid


def bootstrap_registry(conn: sqlite3.Connection, artifacts_dir: Path = ARTIFACTS_DIR) -> None:
    """Register artifacts shipped in ml/artifacts that are not yet known. The first one becomes active if nothing is."""
    for meta_file in sorted(artifacts_dir.glob("*.json")):
        try:
            meta = json.loads(meta_file.read_text())
            if not (artifacts_dir / meta["artifact_file"]).is_file():
                continue
            if conn.execute("SELECT 1 FROM ml_models WHERE artifact_sha256=?", (meta["artifact_sha256"],)).fetchone():
                continue
            register_from_meta(conn, meta, "active" if repo.active_model(conn) is None else "candidate")
        except (KeyError, ValueError, sqlite3.IntegrityError):
            continue


def deploy(conn: sqlite3.Connection, svc: ModelService, model_id: int, actor: str) -> dict:
    with transaction(conn):
        m = repo.get_model(conn, model_id)
        if m is None:
            raise NotFound(f"Model {model_id} not found")
        if m["status"] == "active":
            raise Conflict("This model is already active.", code="already_active")
        if not svc.available:
            raise Conflict("scikit-learn is not installed on the server, so models cannot be deployed.", code="ml_unavailable")
        for other in repo.list_models(conn):
            if other["status"] == "active":
                repo.set_model_status(conn, other["model_id"], "retired")
        repo.set_model_status(conn, model_id, "active")
        repo.insert_audit(conn, now_iso(), actor, "model_deployed", {"model_id": model_id, "name": m["name"]}, f"model:{model_id}")
    live = svc.load(repo.active_model(conn))
    if not live:  # artifact failed verification: roll the registry back so status never lies about what scores traffic
        with transaction(conn):
            repo.set_model_status(conn, model_id, "candidate")
            repo.insert_audit(conn, now_iso(), actor, "model_deploy_failed", {"model_id": model_id}, f"model:{model_id}")
        raise Conflict("The model artifact failed integrity checks and was not deployed.", code="artifact_invalid")
    return repo.get_model(conn, model_id)


def retire(conn: sqlite3.Connection, svc: ModelService, model_id: int, actor: str) -> dict:
    with transaction(conn):
        m = repo.get_model(conn, model_id)
        if m is None:
            raise NotFound(f"Model {model_id} not found")
        if m["status"] != "active":
            raise Conflict("Only the active model can be retired.", code="not_active")
        repo.set_model_status(conn, model_id, "retired")
        repo.insert_audit(conn, now_iso(), actor, "model_retired", {"model_id": model_id, "name": m["name"]}, f"model:{model_id}")
    svc.load(None)  # scoring falls back to rules only
    return repo.get_model(conn, model_id)


def benchmark_rows(artifacts_dir: Path = ARTIFACTS_DIR) -> list[dict]:
    p = artifacts_dir / "benchmark_sample.csv"
    if not p.is_file():
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def benchmark_summary(conn: sqlite3.Connection) -> dict:
    """Confusion matrix of replayed benchmark rows: flagged (HOLD/DECLINE) vs ground truth. The sample is enriched with fraud."""
    r = conn.execute("""SELECT COUNT(*), COALESCE(SUM(benchmark_label=1 AND decision!='APPROVE'),0), COALESCE(SUM(benchmark_label=0 AND decision!='APPROVE'),0),
        COALESCE(SUM(benchmark_label=1 AND decision='APPROVE'),0), COALESCE(SUM(benchmark_label=0 AND decision='APPROVE'),0)
        FROM transactions WHERE source='BENCH'""").fetchone()
    n, tp, fp, fn, tn = r
    return {"replayed": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "note": "Replay sample is enriched with fraud (about 20%) and is not representative of real prevalence (~0.13%). Official metrics are the held-out test figures above."}


BENCH_POOL = 12


def replay(conn: sqlite3.Connection, scorer, actor: str, count: int) -> dict:
    """Send the next `count` rows of the enriched benchmark sample through the live scoring path (rules + active ML model)."""
    from . import transactions_service as txs
    rows = benchmark_rows()
    if not rows:
        raise Conflict("No benchmark sample is installed (run python -m ml.train).", code="no_sample")
    cursor = int(repo.get_meta(conn, "bench_cursor") or 0)
    if cursor >= len(rows):
        raise Conflict("The benchmark sample has been fully replayed.", code="sample_exhausted")
    free = [f"BENCH-{i:04d}" for i in range(1, BENCH_POOL + 1) if not (repo.get_card(conn, f"BENCH-{i:04d}") or {}).get("blocked")]
    if not free:
        raise Conflict("All benchmark cards are blocked. Unblock some on the Cards page.", code="cards_blocked")
    batch, flagged = rows[cursor:cursor + count], 0
    for k, r in enumerate(batch):
        feats = tuple(float(r[f"V{i}"]) for i in range(1, 29))
        out = txs.ingest(conn, txs.NewTx(free[(cursor + k) % len(free)], max(float(r["Amount"]), 0.01), "EUR", "ULB benchmark", "EU", "ONLINE", None, feats, "BENCH", int(float(r["Class"]))), scorer, actor)
        flagged += out["decision"] != "APPROVE"
    with transaction(conn):
        repo.set_meta(conn, "bench_cursor", str(cursor + len(batch)))
        repo.insert_audit(conn, now_iso(), actor, "benchmark_replayed", {"rows": len(batch), "flagged": flagged}, "benchmark")
    return {"replayed": len(batch), "flagged": flagged, "remaining": len(rows) - cursor - len(batch)}
