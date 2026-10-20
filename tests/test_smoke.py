"""Integration tests using FastAPI's in-process client and isolated SQLite files."""
import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from app import main

class ASGIResponse:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = dict(headers)
        self.content = body
        self.text = body.decode("utf-8")

    def json(self):
        return json.loads(self.content)


class ASGIClient:
    """Minimal HTTP test adapter; invokes the app directly without network/deps."""
    def request(self, method, url, json_body=None):
        parsed = urlsplit(url)
        body = b"" if json_body is None else json.dumps(json_body).encode()
        headers = [(b"host", b"testserver")]
        if json_body is not None:
            headers.append((b"content-type", b"application/json"))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "scheme": "http", "path": parsed.path,
                 "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
                 "root_path": "", "headers": headers, "client": ("testclient", 50000),
                 "server": ("testserver", 80)}
        events = [{"type": "http.request", "body": body, "more_body": False}]
        messages = []
        async def receive():
            return events.pop(0) if events else {"type": "http.disconnect"}
        async def send(message):
            messages.append(message)
        async def invoke():
            await main.app(scope, receive, send)
        asyncio.run(invoke())
        start = next(m for m in messages if m["type"] == "http.response.start")
        content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return ASGIResponse(start["status"], [(k.decode(), v.decode()) for k,v in start["headers"]], content)

    def get(self, path): return self.request("GET", path)
    def post(self, path, json=None): return self.request("POST", path, json)
    def put(self, path, json=None): return self.request("PUT", path, json)


class FraudApiTests(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.TemporaryDirectory(prefix="fraud-test-")
        main.DB_PATH = Path(self.db_dir.name) / "test.sqlite"
        main.init()
        self.client = ASGIClient()

    def tearDown(self):
        self.db_dir.cleanup()

    def test_dashboard_and_health(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Fraud Desk", response.text)
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")

    def test_scoring_review_persistence_and_block(self):
        payload = {"card_token": "SYNTH-TEST-7788", "amount": 2400, "merchant": "Synthetic Shop", "country": "US", "channel": "ONLINE"}
        scored_response = self.client.post("/api/transactions", json=payload)
        self.assertEqual(scored_response.status_code, 200)
        scored = scored_response.json()
        self.assertEqual(scored["decision"], "HOLD")
        self.assertGreaterEqual(scored["score"], 0)
        self.assertLessEqual(scored["score"], 1)
        saved = next(row for row in self.client.get("/api/transactions").json() if row["id"] == scored["id"])
        self.assertEqual(saved["token"], payload["card_token"])
        self.assertEqual(saved["decision"], "HOLD")
        reviewed = self.client.post(f"/api/alerts/{scored['id']}/review", json={"verdict": "CONFIRMED_FRAUD"})
        self.assertEqual(reviewed.status_code, 200)
        self.assertTrue(reviewed.json()["card_blocked"])
        card = next(card for card in self.client.get("/api/cards").json() if card["token"] == payload["card_token"])
        self.assertTrue(card["blocked"])
        self.assertEqual(self.client.post("/api/transactions", json=payload).status_code, 409)
        self.assertTrue(any(row["action"] == "review_recorded" for row in self.client.get("/api/audit").json()))

    def test_threshold_configuration_and_input_validation(self):
        config = self.client.get("/api/config").json()
        self.assertLess(float(config["approve_max"]), float(config["hold_max"]))
        invalid = {"card_token": "BAD", "amount": -2, "merchant": "x", "country": "US", "channel": "ONLINE"}
        self.assertEqual(self.client.post("/api/transactions", json=invalid).status_code, 422)
        invalid_config = {"approve_max": 0.8, "hold_max": 0.5, "high_amount": 1500, "blocked_countries": "XX"}
        self.assertEqual(self.client.put("/api/config", json=invalid_config).status_code, 422)
        self.assertGreater(self.client.get("/api/reports").json()["transactions"], 0)

    def test_admin_card_block_and_unblock(self):
        token = "SYNTH-ADMIN-8899"
        self.assertEqual(self.client.post(f"/api/cards/{token}/block").status_code, 200)
        self.assertTrue(next(c for c in self.client.get("/api/cards").json() if c["token"] == token)["blocked"])
        self.assertEqual(self.client.post(f"/api/cards/{token}/unblock").status_code, 200)
        self.assertFalse(next(c for c in self.client.get("/api/cards").json() if c["token"] == token)["blocked"])

    def test_false_positive_verdict_is_recorded_without_blocking(self):
        payload = {"card_token": "SYNTH-FP-7788", "amount": 2200, "merchant": "Synthetic Shop", "country": "US", "channel": "ONLINE"}
        tx_id = self.client.post("/api/transactions", json=payload).json()["id"]
        reviewed = self.client.post(f"/api/alerts/{tx_id}/review", json={"verdict": "FALSE_POSITIVE"})
        self.assertEqual(reviewed.status_code, 200)
        self.assertFalse(reviewed.json()["card_blocked"])
        saved = next(row for row in self.client.get("/api/transactions").json() if row["id"] == tx_id)
        self.assertEqual(saved["review"], "FALSE_POSITIVE")
        card = next(c for c in self.client.get("/api/cards").json() if c["token"] == payload["card_token"])
        self.assertFalse(card["blocked"])


if __name__ == "__main__":
    unittest.main()
