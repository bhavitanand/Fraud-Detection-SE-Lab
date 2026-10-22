import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sklearn")

from app.db.session import connect
from app.main import create_app
from app.services.ml_service import ARTIFACTS_DIR, ModelService
from conftest import make_settings, tx


def models(c):
    return c.get("/api/models").json()


def active(c):
    return next(m for m in models(c)["items"] if m["status"] == "active")


def replay(c, n=25):
    return c.post(f"/api/models/benchmark/replay?count={n}")


def test_shipped_model_is_registered_active_and_documented(empty_client):
    m = active(empty_client)
    assert m["algorithm"] == "random_forest" and 0.5 < m["pr_auc"] <= 1 and m["metrics"]["dataset"]["rows_raw"] == 284807
    assert m["metrics"]["dataset"]["currency"] == "EUR" and m["metrics"]["limitations"] and m["metrics"]["split"]["method"].startswith("chronological")
    t = m["metrics"]["metrics"]["test"]
    assert t["prevalence"] < 0.01 and t["at_app_threshold"]["tp"] + t["at_app_threshold"]["fn"] == 74  # frauds in the held-out test split


def test_model_scores_benchmark_rows_through_live_path_and_summary_matches_rows(empty_client):
    assert replay(empty_client, 25).json()["replayed"] == 25
    rows = empty_client.get("/api/transactions?source=BENCH&page_size=100").json()["items"]
    assert len(rows) == 25 and all(r["currency"] == "EUR" and r["merchant"] == "ULB benchmark" for r in rows)
    assert all("ml_model" in {f["code"] for f in r["factors"]} for r in rows)
    assert all(round(sum(f["points"] for f in r["factors"]), 3) == r["score"] for r in rows)
    assert "benchmark_label" not in rows[0] and "truth" not in str(rows[0]).lower()  # ground truth is never shown to analysts
    s = models(empty_client)["benchmark"]
    assert s["replayed"] == 25 and s["tp"] + s["fp"] + s["fn"] + s["tn"] == 25
    assert s["tp"] + s["fp"] == sum(r["decision"] != "APPROVE" for r in rows)


def test_full_replay_detects_most_fraud_and_then_reports_exhaustion(empty_client):
    for _ in range(12):
        assert replay(empty_client, 25).status_code == 200
    s = models(empty_client)["benchmark"]
    assert s["replayed"] == 300 and s["tp"] + s["fn"] == 60  # 60 frauds in the enriched sample
    assert s["recall"] > 0.6 and s["precision"] > 0.8
    assert replay(empty_client).json()["error"]["code"] == "sample_exhausted"


def test_retired_model_means_rules_only_scoring(empty_client):
    mid = active(empty_client)["model_id"]
    assert empty_client.post(f"/api/models/{mid}/retire").status_code == 200
    assert empty_client.post(f"/api/models/{mid}/retire").json()["error"]["code"] == "not_active"
    replay(empty_client, 5)
    rows = empty_client.get("/api/transactions?source=BENCH").json()["items"]
    assert all("ml_model" not in {f["code"] for f in r["factors"]} and r["decision"] == "APPROVE" for r in rows)
    assert empty_client.get("/api/health").json()["scoring"].endswith("(no ML model active)")
    assert empty_client.post(f"/api/models/{mid}/deploy").status_code == 200
    assert empty_client.post(f"/api/models/{mid}/deploy").json()["error"]["code"] == "already_active"
    assert empty_client.get("/api/health").json()["scoring"].endswith("+ ML model")


def test_deploy_unknown_model_and_audit_trail(empty_client):
    assert empty_client.post("/api/models/999/deploy").status_code == 404
    mid = active(empty_client)["model_id"]
    empty_client.post(f"/api/models/{mid}/retire")
    empty_client.post(f"/api/models/{mid}/deploy")
    actions = [a["action"] for a in empty_client.get("/api/audit").json()["items"]]
    assert {"model_registered", "model_retired", "model_deployed"} <= set(actions)


def test_tampered_registry_hash_blocks_deployment_and_rolls_back(empty_client):
    mid = active(empty_client)["model_id"]
    empty_client.post(f"/api/models/{mid}/retire")
    connect(empty_client.app.state.settings.db_path).execute("UPDATE ml_models SET artifact_sha256=? WHERE model_id=?", ("0" * 64, mid))
    r = empty_client.post(f"/api/models/{mid}/deploy")
    assert r.status_code == 409 and r.json()["error"]["code"] == "artifact_invalid"
    assert next(m for m in models(empty_client)["items"] if m["model_id"] == mid)["status"] == "candidate"
    assert empty_client.app.state.models.active_id is None


def test_model_service_refuses_tampered_or_foreign_artifacts(tmp_path):
    meta = json.loads(next(ARTIFACTS_DIR.glob("*.json")).read_text())
    shutil.copy(ARTIFACTS_DIR / meta["artifact_file"], tmp_path / meta["artifact_file"])
    row = {"model_id": 1, "name": meta["name"], "artifact_file": meta["artifact_file"], "artifact_sha256": meta["artifact_sha256"]}
    svc = ModelService(tmp_path)
    assert svc.load(row) is True and svc.predict(tuple([0.0] * 28), 10.0)[0] <= 1
    with open(tmp_path / meta["artifact_file"], "ab") as f:
        f.write(b"x")  # corrupt after hashing
    assert ModelService(tmp_path).load(row) is False
    assert ModelService(tmp_path).load({**row, "artifact_file": "../../etc/passwd"}) is False
    assert svc.load(None) is False and svc.predict(tuple([0.0] * 28), 1.0) is None


def test_model_prediction_error_falls_back_to_rules(empty_client):
    class Broken:
        def predict_fraud_proba(self, X):
            raise RuntimeError("boom")

    svc = empty_client.app.state.models
    svc._active = (svc._active[0], "broken", Broken())
    assert svc.predict(tuple([0.0] * 28), 5.0) is None
    assert replay(empty_client, 3).status_code == 200  # scoring continues with rules only


def test_anon_features_validation(empty_client):
    assert empty_client.post("/api/transactions", json=tx(anon_features=[0.0] * 27)).status_code == 422
    assert empty_client.post("/api/transactions", json=tx(anon_features=[0.0] * 27 + [1e9])).status_code == 422
    ok = empty_client.post("/api/transactions", json=tx(card_token="SYNTH-ML-0001", anon_features=[0.0] * 28))
    assert ok.status_code == 200 and any(f["code"] == "ml_model" for f in ok.json()["factors"])


def test_app_runs_without_scikit_learn(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelService, "__init__", lambda self, d=ARTIFACTS_DIR: (setattr(self, "dir", d), setattr(self, "_lock", __import__("threading").Lock()),
                                                                                  setattr(self, "_active", None), setattr(self, "available", False)) and None)
    with TestClient(create_app(make_settings(tmp_path, seed_demo=False))) as c:
        h = c.get("/api/health").json()
        assert h["ml_available"] is False and "no ML model" in h["scoring"]
        assert c.post("/api/transactions", json=tx()).status_code == 200
        mid = c.get("/api/models").json()["items"][0]["model_id"]
        assert c.post(f"/api/models/{mid}/deploy").json()["error"]["code"] in ("ml_unavailable", "already_active")
