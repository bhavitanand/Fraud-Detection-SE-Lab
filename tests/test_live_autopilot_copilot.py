import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.session import connect
from app.main import create_app
from app.repositories import db_access as repo
from app.services import copilot_service
from conftest import make_settings, tx


def _token(client, tx_id):
    body = next(n["body"] for n in client.get("/api/notifications?limit=100").json()["items"] if n["txn_id"] == tx_id)
    return re.search(r"/confirm/(\S+)$", body).group(1)


def _lower_block_threshold(settings, v="0.5"):
    c = connect(settings.db_path)
    try:
        repo.set_config(c, "auto_block_score", v)
        c.commit()
    finally:
        c.close()


# ---------- autopilot ----------
def test_autopilot_is_off_by_default(client):
    out = client.post("/api/transactions", json=tx(country="KP", card_token="SYNTH-IN-1006", amount=90000)).json()
    assert out["decision"] == "DECLINE" and client.get("/api/cards?q=SYNTH-IN-1006").json()[0]["blocked"] is False


def test_autopilot_blocks_declines_and_closes_alert_from_cardholder_reply(settings):
    with TestClient(create_app(settings)) as c:
        _lower_block_threshold(settings)
        assert c.put("/api/autopilot", json={"enabled": True}).json() == {"autopilot": True}
        out = c.post("/api/transactions", json=tx(country="KP", card_token="SYNTH-IN-1004", amount=90000)).json()
        assert out["decision"] == "DECLINE"
        card = c.get("/api/cards?q=SYNTH-IN-1004").json()[0]
        assert card["blocked"] and card["blocked_by"] == "autopilot"
        assert c.post(f"/api/public/confirm/{_token(c, out['id'])}", json={"reply": "NOT_ME"}).status_code == 200
        d = c.get(f"/api/transactions/{out['id']}").json()
        assert d["review"] == "CONFIRMED_FRAUD" and d["reviewed_by"] == "autopilot"
        assert any(a["action"] == "card_blocked" and a["actor"] == "autopilot" for a in d["audit"])


def test_autopilot_releases_its_own_block_when_cardholder_says_legit(settings):
    with TestClient(create_app(settings)) as c:
        _lower_block_threshold(settings)
        c.put("/api/autopilot", json={"enabled": True})
        out = c.post("/api/transactions", json=tx(country="KP", card_token="SYNTH-IN-1012", amount=90000)).json()
        c.post(f"/api/public/confirm/{_token(c, out['id'])}", json={"reply": "LEGIT"})
        assert c.get(f"/api/transactions/{out['id']}").json()["review"] == "FALSE_POSITIVE"
        assert c.get("/api/cards?q=SYNTH-IN-1012").json()[0]["blocked"] is False


def test_autopilot_never_overrides_a_manual_block(settings):
    with TestClient(create_app(settings)) as c:
        c.put("/api/autopilot", json={"enabled": True})
        out = c.post("/api/transactions", json=tx(card_token="SYNTH-IN-1005")).json()  # HOLD, below the auto-block score
        assert out["alert_created"] and out["score"] < 0.9
        c.post("/api/cards/SYNTH-IN-1005/block", json={"reason": "analyst call"})
        c.post(f"/api/public/confirm/{_token(c, out['id'])}", json={"reply": "LEGIT"})
        assert c.get("/api/cards?q=SYNTH-IN-1005").json()[0]["blocked"] is True


# ---------- live engine ----------
def test_live_engine_streams_scores_and_reports_kpis(settings):
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/live/start", json={"cards": 30, "rate": 25, "days": 9}).status_code == 200
        assert c.post("/api/live/start", json={}).json()["error"]["code"] == "already_running"
        for _ in range(120):
            st = c.get("/api/live/status").json()
            if not st["running"]:
                break
            time.sleep(0.5)
        assert st["state"] == "completed" and st["processed"] > 100 and st["error"] is None and st["autopilot"] is True
        k = st["kpis"]
        assert k["transactions"] > 100 and k["frauds"] >= 0 and "Not real-world" in k["note"]
        assert c.get("/api/transactions?source=SIM&page_size=5").json()["total"] > 100


def test_live_status_is_idle_before_start(client):
    st = client.get("/api/live/status").json()
    assert st["state"] == "idle" and st["running"] is False and st["kpis"] is None


# ---------- copilot ----------
def test_offline_search_parses_filters_and_runs_parameterised_query(client):
    client.post("/api/transactions", json=tx(card_token="SYNTH-CP-0001", amount=75000, channel="ONLINE", country="IN", merchant="Test Mart"))
    r = client.post("/api/copilot/chat", json={"question": "show held online orders above ₹50,000"}).json()
    assert r["provider"] == "offline" and r["filter"]["decision"] == "HOLD" and r["filter"]["min_amount"] == 50000
    assert r["count"] >= 1 and all(x["amount"] >= 50000 and x["decision"] == "HOLD" for x in r["rows"])


def test_clean_filter_drops_unknown_keys_and_bad_values():
    f = copilot_service.clean_filter({"decision": "approve", "city": "Pune", "sql": "DROP TABLE x", "min_amount": "abc", "limit": 9999, "channel": "FAX", "card_last4": "12'; --"})
    assert f == {"decision": "APPROVE", "city": "Pune", "limit": 50}


def test_search_text_cannot_inject_sql(client):
    r = client.post("/api/copilot/chat", json={"question": "at x'; DROP TABLE transactions; --"})
    assert r.status_code == 200 and client.get("/api/transactions").status_code == 200


def test_case_summary_offline_has_actionable_text(client):
    out = client.post("/api/transactions", json=tx(card_token="SYNTH-CP-0002")).json()
    s = client.get(f"/api/transactions/{out['id']}/copilot").json()
    assert s["provider"] == "offline" and s["summary"] and s["recommendation"] and "Was this you" in s["customer_message"]


def _gemini_transport(payload, status=200):
    def handler(request: httpx.Request):
        assert request.headers["x-goog-api-key"] == "k" and "key=" not in str(request.url)
        return httpx.Response(status, json={"candidates": [{"content": {"parts": [{"text": payload}]}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gemini_path_is_used_when_a_key_is_set_and_output_is_validated(tmp_path):
    s = make_settings(tmp_path, gemini_api_key="k")
    with TestClient(create_app(s)) as c:
        out = c.post("/api/transactions", json=tx(card_token="SYNTH-CP-0003")).json()
        conn = connect(s.db_path)
        good = '{"summary":"s","recommendation":"r","customer_message":"m"}'
        assert copilot_service.case_summary(conn, out["id"], s, _gemini_transport(good))["provider"] == "gemini"
        bad = copilot_service.case_summary(conn, out["id"], s, _gemini_transport('{"summary":"only"}'))
        assert bad["provider"] == "offline"
        chat = copilot_service.chat(conn, "x", s, ["Pune"], _gemini_transport('{"decision":"DECLINE","drop":"1"}')) if False else \
            copilot_service.chat(conn, "declined ones", s, ["Pune"], _gemini_transport('{"decision":"DECLINE","drop":"1"}'))
        assert chat["provider"] == "gemini" and chat["filter"] == {"decision": "DECLINE"}
        conn.close()


def test_gemini_failure_falls_back_to_offline(tmp_path):
    s = make_settings(tmp_path, gemini_api_key="k")
    with TestClient(create_app(s)) as c:
        out = c.post("/api/transactions", json=tx(card_token="SYNTH-CP-0004")).json()
        conn = connect(s.db_path)
        r = copilot_service.case_summary(conn, out["id"], s, _gemini_transport("{}", status=500))
        assert r["provider"] == "offline" and r["fallback_reason"] == "HTTPStatusError"
        conn.close()


# ---------- live ML scorer ----------
def test_shipped_live_model_scores_with_top_reasons_and_blocked_country_policy(tmp_path):
    pytest.importorskip("xgboost")
    with TestClient(create_app(make_settings(tmp_path, live_model=True))) as c:
        models = c.get("/api/models").json()["items"]
        assert any(m["kind"] == "live" and m["status"] == "active" for m in models)
        ok = c.post("/api/transactions", json=tx(card_token="SYNTH-IN-1007", amount=450, merchant="Swiggy", channel="ONLINE", location="Jaipur")).json()
        assert ok["scorer"].startswith("ml-primary") and ok["decision"] == "APPROVE"
        ml = next(f for f in ok["factors"] if f["code"] == "ml_model")
        assert "top" in ml["detail"] and "rule_signals" in ml["detail"]
        risky = c.post("/api/transactions", json=tx(card_token="SYNTH-IN-1009", amount=95000, merchant="Unknown Online Store", channel="ONLINE", country="AE", location="Dubai")).json()
        top = next(f for f in risky["factors"] if f["code"] == "ml_model")["detail"]["top"]
        assert top and {"feature", "impact"} <= set(top[0])
        bad = c.post("/api/transactions", json=tx(card_token="SYNTH-IN-1008", amount=90000, country="KP")).json()
        assert bad["decision"] == "DECLINE"


def test_re_exported_artifact_refreshes_the_registered_hash(tmp_path):
    pytest.importorskip("xgboost")
    s = make_settings(tmp_path, live_model=True)
    with TestClient(create_app(s)):
        pass
    c = connect(s.db_path)
    c.execute("UPDATE ml_models SET artifact_sha256='stale' WHERE kind='live'")
    c.commit()
    c.close()
    with TestClient(create_app(s)) as cl:  # restart: the registry heals itself and the model loads again
        live = [m for m in cl.get("/api/models").json()["items"] if m["kind"] == "live"]
        assert len(live) == 1 and live[0]["status"] == "active"
        assert cl.get("/api/live/status").json()["model"]["name"] == "india_xgboost_v1"
