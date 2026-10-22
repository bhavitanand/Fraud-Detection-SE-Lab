import re

import pytest
from fastapi.testclient import TestClient

from app.db.session import connect
from app.main import create_app
from app.services import auth_service
from conftest import make_settings, tx

PW = "correct-horse-battery"


def post(c, **kw):
    return c.post("/api/transactions", json=tx(**kw))


# ---- India-specific input handling ----
def test_defaults_are_inr_and_india(empty_client):
    out = empty_client.post("/api/transactions", json={"card_token": "SYNTH-DEF-0001", "amount": 450, "merchant": "Swiggy", "channel": "ONLINE"}).json()
    d = empty_client.get(f"/api/transactions/{out['id']}").json()
    assert d["currency"] == "INR" and d["country"] == "IN" and out["decision"] == "APPROVE"


def test_foreign_currency_is_converted_for_rule_thresholds(empty_client):
    r = post(empty_client, amount=1000, currency="USD", channel="POS").json()  # about 83,000 INR > 50,000
    assert any(f["code"] == "high_amount" for f in r["factors"])
    assert empty_client.post("/api/transactions", json=tx(currency="XYZ")).status_code == 422


def test_location_must_match_country(empty_client):
    r = post(empty_client, location="Delhi", country="US")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "location"
    assert post(empty_client, location="Delhi", country="IN", card_token="SYNTH-LOC-0001").status_code == 200
    assert post(empty_client, location="Neverland", country="IN", card_token="SYNTH-LOC-0002").status_code == 200  # unknown cities are allowed


def test_impossible_travel_between_cities(empty_client):
    post(empty_client, card_token="SYNTH-TRV-0001", amount=500, channel="POS", location="Delhi")
    r = post(empty_client, card_token="SYNTH-TRV-0001", amount=500, channel="POS", location="Mumbai").json()
    assert any(f["code"] == "impossible_travel" for f in r["factors"]) and r["decision"] == "HOLD"


def test_new_country_unusual_amount_and_velocity_from_history(empty_client):
    for i in range(5):
        post(empty_client, card_token="SYNTH-HST-0001", amount=500, channel="POS", merchant="Local Store")
    r = post(empty_client, card_token="SYNTH-HST-0001", amount=40000, channel="POS", country="AE", merchant="Dubai Mall").json()
    got = {f["code"] for f in r["factors"]}
    assert {"unusual_amount", "new_country", "new_merchant", "high_velocity"} <= got
    assert round(sum(f["points"] for f in r["factors"]), 3) == r["score"]


def test_seeded_portfolio_is_indian_and_internally_consistent(client):
    cards = client.get("/api/cards").json()
    assert any(c["customer_city"] == "Delhi" for c in cards) and all(c["token"].startswith("SYNTH-IN-") for c in cards)
    items = client.get("/api/transactions?page_size=100").json()["items"]
    assert items and all(t["currency"] == "INR" and t["source"] == "SEED" for t in items)
    assert {t["merchant"] for t in items} & {"Swiggy", "Flipkart", "IRCTC"}
    for t in items:
        assert round(sum(f["points"] for f in t["factors"]), 3) == t["score"]
    report = client.get("/api/reports").json()
    assert report["alert_backlog"] > 0 and report["reviewed"] > 0 and report["flagged_value_inr"] > 0


def test_transaction_detail_includes_customer_and_merchant_but_not_contact_details(client):
    t = next(x for x in client.get("/api/transactions?decision=HOLD").json()["items"])
    d = client.get(f"/api/transactions/{t['id']}").json()
    assert set(d["customer"]) == {"name", "city", "state", "home_country"} and d["merchant_info"]["name"] == t["merchant"]
    assert "phone" not in str(d["customer"]) and "email" not in str(d["customer"])


# ---- fraud_alerts + cardholder notification ----
def test_alert_row_is_created_only_for_hold_and_decline(empty_client):
    a = post(empty_client, card_token="SYNTH-AL-0001").json()
    b = post(empty_client, card_token="SYNTH-AL-0002", amount=100, channel="POS").json()
    assert a["alert_created"] and a["alert_id"] and not b["alert_created"] and b["alert_id"] is None
    conn = connect(empty_client.app.state.settings.db_path)
    assert conn.execute("select count(*) from fraud_alerts").fetchone()[0] == 1
    assert conn.execute("select risk_score from fraud_alerts").fetchone()[0] == a["score"]


def _outbox_token(c, txn_id):
    notes = c.get("/api/notifications?limit=100").json()["items"]
    body = next(n["body"] for n in notes if n["txn_id"] == txn_id)
    return re.search(r"/confirm/(\S+)$", body).group(1)


def test_cardholder_not_me_reply_blocks_card_once(client):
    out = post(client, card_token="SYNTH-IN-1001", amount=90000, channel="POS", merchant="Tanishq").json()
    assert out["alert_created"]
    note = next(n for n in client.get("/api/notifications").json()["items"] if n["txn_id"] == out["id"])
    assert note["channel"] == "SMS" and "SYNTH-IN-1001"[-4:] in note["body"] and note["recipient"].startswith("+91")
    token = _outbox_token(client, out["id"])
    info = client.get(f"/api/public/confirm/{token}").json()
    assert info["card_last4"] == "1001" and info["already_replied"] is False and "phone" not in str(info)
    r = client.post(f"/api/public/confirm/{token}", json={"reply": "NOT_ME"})
    assert r.status_code == 200 and r.json()["card_blocked"] is True
    assert client.post(f"/api/public/confirm/{token}", json={"reply": "LEGIT"}).json()["error"]["code"] == "already_replied"
    d = client.get(f"/api/transactions/{out['id']}").json()
    assert d["cardholder_response"] == "NOT_ME" and d["review"] == "OPEN" and d["card"]["blocked"]  # the analyst still decides
    assert any(a["action"] == "cardholder_replied" and a["actor"] == "cardholder" for a in d["audit"])


def test_cardholder_legit_reply_does_not_block(client):
    out = post(client, card_token="SYNTH-IN-1004", amount=90000, channel="POS", merchant="Croma").json()
    token = _outbox_token(client, out["id"])
    assert client.post(f"/api/public/confirm/{token}", json={"reply": "LEGIT"}).json()["card_blocked"] is False
    assert not client.get(f"/api/transactions/{out['id']}").json()["card"]["blocked"]


def test_reply_link_rejects_bad_tokens_and_bad_replies(client):
    assert client.get("/api/public/confirm/not-a-real-token-value").status_code == 404
    assert client.get("/api/public/confirm/x").status_code == 422
    out = post(client, card_token="SYNTH-IN-1006", amount=90000, channel="POS").json()
    token = _outbox_token(client, out["id"])
    assert client.post(f"/api/public/confirm/{token}", json={"reply": "MAYBE"}).status_code == 422


def test_expired_reply_link_is_refused(client):
    out = post(client, card_token="SYNTH-IN-1008", amount=90000, channel="POS").json()
    token = _outbox_token(client, out["id"])
    connect(client.app.state.settings.db_path).execute("UPDATE notifications SET expires_at='2000-01-01T00:00:00+00:00' WHERE txn_id=?", (out["id"],))
    assert client.post(f"/api/public/confirm/{token}", json={"reply": "LEGIT"}).json()["error"]["code"] == "link_expired"


def test_no_notification_for_approvals_or_unknown_cardholders(client):
    approved = post(client, card_token="SYNTH-IN-1002", amount=300, channel="POS").json()
    unknown = post(client, card_token="SYNTH-NOCUST-1", amount=90000, channel="POS").json()
    txn_ids = {n["txn_id"] for n in client.get("/api/notifications?limit=100").json()["items"]}
    assert approved["id"] not in txn_ids and unknown["id"] not in txn_ids


def test_public_reply_endpoint_is_rate_limited(client):
    from app.api import routes
    routes._public_hits.clear()
    codes = [client.get("/api/public/confirm/not-a-real-token-value").status_code for _ in range(25)]
    assert codes[:20] == [404] * 20 and set(codes[20:]) == {429}
    routes._public_hits.clear()


# ---- assignment (needs real users) ----
@pytest.fixture
def secured(tmp_path):
    s = make_settings(tmp_path, auth_required=True, seed_demo=False)
    app = create_app(s)
    conn = connect(s.db_path)
    for email, role in (("a1@example.com", "analyst"), ("a2@example.com", "analyst"), ("boss@example.com", "admin")):
        auth_service.create_user(conn, email, PW, role)
    conn.close()
    auth_service._fails.clear()
    with TestClient(app) as c:
        yield c


def H(c, email):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": email, "password": PW}).json()["access_token"]}


def test_assignment_rules(secured):
    a1, a2, boss = H(secured, "a1@example.com"), H(secured, "a2@example.com"), H(secured, "boss@example.com")
    tid = secured.post("/api/transactions", json=tx(), headers=a1).json()["id"]
    assert secured.get("/api/alerts?assigned=unassigned", headers=a1).json()[0]["id"] == tid
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": "a2@example.com"}, headers=a1).status_code == 403  # analysts only take alerts themselves
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": "ghost@example.com"}, headers=boss).status_code == 422
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": "A1@Example.com"}, headers=a1).json()["assigned_to"] == "a1@example.com"
    assert [t["id"] for t in secured.get("/api/alerts?assigned=me", headers=a1).json()] == [tid]
    assert secured.get("/api/alerts?assigned=me", headers=a2).json() == []
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": None}, headers=a2).status_code == 403  # not the assignee
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": "a2@example.com"}, headers=boss).status_code == 200  # admin may reassign
    secured.post(f"/api/alerts/{tid}/review", json={"verdict": "FALSE_POSITIVE"}, headers=a2)
    assert secured.post(f"/api/alerts/{tid}/assign", json={"assignee": "a1@example.com"}, headers=boss).json()["error"]["code"] == "already_reviewed"
    approved = secured.post("/api/transactions", json=tx(card_token="SYNTH-AP-0001", amount=100, channel="POS"), headers=a1).json()["id"]
    assert secured.post(f"/api/alerts/{approved}/assign", json={"assignee": None}, headers=a1).json()["error"]["code"] == "no_alert"
    assert secured.post("/api/alerts/9999/assign", json={"assignee": None}, headers=a1).status_code == 404


def test_productivity_report_counts_each_analyst(secured):
    a1, a2 = H(secured, "a1@example.com"), H(secured, "a2@example.com")
    for i, (h, verdict) in enumerate([(a1, "CONFIRMED_FRAUD"), (a1, "FALSE_POSITIVE"), (a2, "FALSE_POSITIVE")]):
        tid = secured.post("/api/transactions", json=tx(card_token=f"SYNTH-PR-000{i}"), headers=h).json()["id"]
        secured.post(f"/api/alerts/{tid}/review", json={"verdict": verdict}, headers=h)
    prod = {p["analyst"]: p for p in secured.get("/api/reports", headers=a1).json()["productivity"]}
    assert prod["a1@example.com"]["resolved"] == 2 and prod["a1@example.com"]["confirmed"] == 1 and prod["a2@example.com"]["false_positives"] == 1


# ---- audit hash chain ----
def test_audit_chain_verifies_and_detects_tampering(client):
    post(client, card_token="SYNTH-CH-0001")
    ok = client.get("/api/audit/verify").json()
    assert ok["ok"] is True and ok["checked"] > 5
    conn = connect(client.app.state.settings.db_path)
    victim = conn.execute("SELECT id FROM audit WHERE action='transaction_scored' ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.execute("UPDATE audit SET detail='{\"score\": 0.01}' WHERE id=?", (victim,))
    bad = client.get("/api/audit/verify").json()
    assert bad["ok"] is False and bad["first_broken_id"] == victim


def test_audit_chain_detects_deleted_rows(client):
    post(client, card_token="SYNTH-CH-0002")
    conn = connect(client.app.state.settings.db_path)
    mid = conn.execute("SELECT id FROM audit ORDER BY id LIMIT 1 OFFSET 3").fetchone()[0]
    conn.execute("DELETE FROM audit WHERE id=?", (mid,))
    assert client.get("/api/audit/verify").json()["ok"] is False


def test_label_export_contains_only_reviewed_alerts(client):
    text = client.get("/api/labels/export.csv").text.splitlines()
    assert text[0] == "transaction_id,created,amount,currency,source,label" and len(text) > 1
    assert all(line.rsplit(",", 1)[1] in ("0", "1") for line in text[1:])
