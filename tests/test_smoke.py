"""The five original integration scenarios, ported from the hand-rolled ASGI client to pytest fixtures.
Assertions are unchanged except where the API contract deliberately changed (see STATUS.md):
/api/transactions and /api/audit are now paginated objects with an `items` list."""
from conftest import tx


def rows(client, path="/api/transactions"):
    return client.get(path).json()["items"]


def test_dashboard_and_health(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Fraud Desk" in response.text
    assert client.get("/api/health").json()["status"] == "ok"


def test_scoring_review_persistence_and_block(client):
    payload = tx()
    scored_response = client.post("/api/transactions", json=payload)
    assert scored_response.status_code == 200
    scored = scored_response.json()
    assert scored["decision"] == "HOLD"
    assert 0 <= scored["score"] <= 1
    saved = next(r for r in rows(client) if r["id"] == scored["id"])
    assert saved["token"] == payload["card_token"]
    assert saved["decision"] == "HOLD"
    reviewed = client.post(f"/api/alerts/{scored['id']}/review", json={"verdict": "CONFIRMED_FRAUD"})
    assert reviewed.status_code == 200
    assert reviewed.json()["card_blocked"] is True
    card = next(c for c in client.get("/api/cards").json() if c["token"] == payload["card_token"])
    assert card["blocked"]
    assert client.post("/api/transactions", json=payload).status_code == 409
    assert any(r["action"] == "review_recorded" for r in rows(client, "/api/audit"))


def test_threshold_configuration_and_input_validation(client):
    config = client.get("/api/config").json()
    assert float(config["approve_max"]) < float(config["hold_max"])
    invalid = {"card_token": "BAD", "amount": -2, "merchant": "x", "country": "US", "channel": "ONLINE"}
    assert client.post("/api/transactions", json=invalid).status_code == 422
    invalid_config = {"approve_max": 0.8, "hold_max": 0.5, "high_amount": 1500, "blocked_countries": "XX"}
    assert client.put("/api/config", json=invalid_config).status_code == 422
    assert client.get("/api/reports").json()["transactions"] > 0


def test_admin_card_block_and_unblock(client):
    token = "SYNTH-ADMIN-8899"
    assert client.post(f"/api/cards/{token}/block").status_code == 200
    assert next(c for c in client.get("/api/cards").json() if c["token"] == token)["blocked"]
    assert client.post(f"/api/cards/{token}/unblock").status_code == 200
    assert not next(c for c in client.get("/api/cards").json() if c["token"] == token)["blocked"]


def test_false_positive_verdict_is_recorded_without_blocking(client):
    payload = tx(card_token="SYNTH-FP-7788", amount=55000)
    tx_id = client.post("/api/transactions", json=payload).json()["id"]
    reviewed = client.post(f"/api/alerts/{tx_id}/review", json={"verdict": "FALSE_POSITIVE"})
    assert reviewed.status_code == 200
    assert reviewed.json()["card_blocked"] is False
    saved = next(r for r in rows(client) if r["id"] == tx_id)
    assert saved["review"] == "FALSE_POSITIVE"
    card = next(c for c in client.get("/api/cards").json() if c["token"] == payload["card_token"])
    assert not card["blocked"]
