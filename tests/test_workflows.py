import threading

import pytest

from conftest import tx


def post(c, **kw):
    return c.post("/api/transactions", json=tx(**kw))


# ---- validation ----
@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -1}, {"amount": 1_000_001}, {"amount": "abc"}, {"card_token": "abc"}, {"card_token": "has space1"},
    {"card_token": "4111111111111111"}, {"card_token": "<script>alert1</script>"}, {"merchant": "  "}, {"merchant": "Shop 4111 1111 1111 1111"},
    {"country": "USA"}, {"country": "1!"}, {"channel": "FAX"}, {"cvv": "123"},
])
def test_invalid_ingest_is_rejected_with_field_details(empty_client, bad):
    r = post(empty_client, **bad)
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error" and body["details"]
    assert empty_client.get("/api/transactions").json()["total"] == 0  # nothing persisted


def test_approved_transaction_has_no_alert_and_cannot_be_reviewed(empty_client):
    out = post(empty_client, amount=20, channel="POS").json()
    assert out["decision"] == "APPROVE" and out["alert_created"] is False
    assert empty_client.get("/api/alerts").json() == []
    r = empty_client.post(f"/api/alerts/{out['id']}/review", json={"verdict": "FALSE_POSITIVE"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_alert"


def test_scoring_explanation_is_persisted(empty_client):
    out = post(empty_client, country="xx").json()
    assert out["decision"] == "DECLINE"
    d = empty_client.get(f"/api/transactions/{out['id']}").json()
    assert {f["code"] for f in d["factors"]} >= {"base", "blocked_country", "high_amount"}
    assert abs(sum(f["points"] for f in d["factors"]) - d["score"]) < 1e-9
    assert d["scorer"] == "heuristic-v1" and d["source"] == "LIVE"


# ---- review state machine ----
def test_review_missing_transaction_is_404(empty_client):
    assert empty_client.post("/api/alerts/999/review", json={"verdict": "FALSE_POSITIVE"}).status_code == 404
    assert empty_client.get("/api/transactions/999").status_code == 404


def test_invalid_verdict_rejected(empty_client):
    tid = post(empty_client).json()["id"]
    assert empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": "MAYBE"}).status_code == 422


def test_second_review_conflicts_and_keeps_first_verdict(empty_client):
    tid = post(empty_client).json()["id"]
    assert empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": "FALSE_POSITIVE", "note": "customer confirmed"}).status_code == 200
    r = empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": "CONFIRMED_FRAUD"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_reviewed"
    d = empty_client.get(f"/api/transactions/{tid}").json()
    assert d["review"] == "FALSE_POSITIVE" and d["review_note"] == "customer confirmed"
    assert d["card"]["blocked"] is False  # the rejected second verdict had no side effect


def test_confirmed_fraud_blocks_card_and_blocked_card_is_rejected_and_audited(empty_client):
    tid = post(empty_client).json()["id"]
    out = empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": "CONFIRMED_FRAUD"}).json()
    assert out["card_blocked"] and out["card_currently_blocked"]
    assert post(empty_client).status_code == 409
    actions = [a["action"] for a in empty_client.get("/api/audit").json()["items"]]
    assert {"transaction_scored", "review_recorded", "card_blocked", "transaction_rejected_blocked"} <= set(actions)
    detail = empty_client.get(f"/api/transactions/{tid}").json()
    assert detail["card"]["blocked"] and detail["card"]["block_reason"].startswith("Confirmed fraud")
    assert any(a["action"] == "review_recorded" for a in detail["audit"])


def test_false_positive_on_already_blocked_card_reports_not_blocked_by_review(empty_client):
    tid = post(empty_client).json()["id"]
    empty_client.post("/api/cards/SYNTH-TEST-7788/block")  # blocked after scoring, before review
    out = empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": "FALSE_POSITIVE"}).json()
    assert out["card_blocked"] is False and out["card_currently_blocked"] is True


def test_concurrent_reviews_exactly_one_wins(empty_client):
    tid = post(empty_client).json()["id"]
    codes = []

    def go(verdict):
        codes.append(empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": verdict}).status_code)

    ts = [threading.Thread(target=go, args=(v,)) for v in ["CONFIRMED_FRAUD", "FALSE_POSITIVE"] * 4]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200] + [409] * 7
    audit = [a for a in empty_client.get("/api/audit?limit=200").json()["items"] if a["action"] == "review_recorded"]
    assert len(audit) == 1


# ---- cards ----
def test_block_is_idempotent_and_audited_once(empty_client):
    a = empty_client.post("/api/cards/SYNTH-AAAA/block", json={"reason": "lost"}).json()
    b = empty_client.post("/api/cards/SYNTH-AAAA/block").json()
    assert a == {"token": "SYNTH-AAAA", "blocked": True, "changed": True} and b["changed"] is False
    assert sum(x["action"] == "card_blocked" for x in empty_client.get("/api/audit").json()["items"]) == 1
    assert empty_client.post("/api/cards/bad token/block").status_code in (404, 422)
    assert empty_client.post("/api/cards/abc/block").status_code == 422


# ---- config ----
GOOD = {"approve_max": 0.3, "hold_max": 0.7, "high_amount": 1000, "blocked_countries": "xx, ru,xx"}


def test_config_update_applies_to_scoring_and_is_audited(empty_client):
    out = empty_client.put("/api/config", json=GOOD).json()
    assert out["blocked_countries"] == "XX,RU" and out["velocity_limit"] == 4 and out["high_amount"] == 1000
    r = post(empty_client, amount=1200, channel="POS", card_token="SYNTH-CFG2").json()
    assert any(f["code"] == "high_amount" for f in r["factors"])
    assert any(a["action"] == "config_updated" for a in empty_client.get("/api/audit").json()["items"])


@pytest.mark.parametrize("patch", [
    {"approve_max": 0.7, "hold_max": 0.7}, {"approve_max": -0.1}, {"hold_max": 1.5}, {"high_amount": 0}, {"blocked_countries": "XXX"},
    {"blocked_countries": "X1"}, {"velocity_limit": 0}, {"unknown": 1},
])
def test_invalid_config_rejected_and_unchanged(empty_client, patch):
    before = empty_client.get("/api/config").json()
    assert empty_client.put("/api/config", json={**GOOD, **patch}).status_code == 422
    assert empty_client.get("/api/config").json() == before


# ---- list / filters / reports ----
def test_transaction_listing_filters_sort_and_pagination(client):
    page = client.get("/api/transactions?page_size=10&sort=score&order=desc").json()
    assert page["page_size"] == 10 and len(page["items"]) == 10 and page["total"] > 10 and page["pages"] >= 2
    scores = [r["score"] for r in page["items"]]
    assert scores == sorted(scores, reverse=True)
    only = client.get("/api/transactions?decision=DECLINE&source=SEED").json()
    assert only["total"] > 0 and all(r["decision"] == "DECLINE" and r["source"] == "SEED" for r in only["items"])
    assert client.get("/api/transactions?q=SYNTH-1001").json()["total"] >= 0
    assert client.get("/api/transactions?q=%25").json()["total"] == 0  # LIKE wildcards are escaped
    assert client.get("/api/transactions?sort=password").status_code == 422
    assert client.get("/api/transactions?page_size=1000").status_code == 422


def test_search_matches_merchant_and_id(empty_client):
    tid = post(empty_client, merchant="Quirky Widgets").json()["id"]
    assert empty_client.get("/api/transactions?q=quirky").json()["total"] == 1
    assert empty_client.get(f"/api/transactions?q=%23{tid}").json()["items"][0]["id"] == tid


def test_report_numbers_match_transactions(empty_client):
    a = post(empty_client, card_token="SYNTH-R001").json()["id"]
    post(empty_client, card_token="SYNTH-R002")
    post(empty_client, card_token="SYNTH-R003", amount=10, channel="POS")
    empty_client.post(f"/api/alerts/{a}/review", json={"verdict": "CONFIRMED_FRAUD"})
    r = empty_client.get("/api/reports").json()
    assert r["transactions"] == 3 and r["alert_count"] == 2 and r["alert_backlog"] == 1
    assert r["confirmed_fraud"] == 1 and r["false_positives"] == 0 and r["confirmed_share"] == 1.0
    assert r["by_decision"] == {"APPROVE": 1, "HOLD": 2} and r["by_source"] == {"LIVE": 3}
    assert sum(d["total"] for d in r["trend"]) == 3 and r["limitations"]
    assert "recall" not in str(r).lower().replace("recall and the true", "")  # no invented detection metrics
    assert empty_client.get("/api/reports?date_from=2999-01-01").json()["transactions"] == 0


def test_report_with_no_data_has_null_ratios(empty_client):
    r = empty_client.get("/api/reports").json()
    assert r["transactions"] == 0 and r["confirmed_share"] is None and r["alert_rate"] == 0


def test_seed_rows_are_labelled_and_live_rows_separate(client):
    by = client.get("/api/reports").json()["by_source"]
    assert by.get("SEED", 0) > 0 and "LIVE" not in by
    post(client)
    assert client.get("/api/reports?source=LIVE").json()["transactions"] == 1


def test_csv_export_neutralises_formulas(empty_client):
    post(empty_client, merchant="=HYPERLINK(\"http://x\")")
    text = empty_client.get("/api/reports/export.csv").text
    assert text.splitlines()[0].startswith("id,created,token")
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_audit_details_are_json_and_html_is_not_interpreted_server_side(empty_client):
    post(empty_client, merchant="<img src=x onerror=alert(1)>")
    d = empty_client.get("/api/transactions?q=img").json()["items"][0]
    assert d["merchant"] == "<img src=x onerror=alert(1)>"  # stored verbatim; the UI renders it as text
    for a in empty_client.get("/api/audit").json()["items"]:
        assert isinstance(a["detail"], dict)


def test_responses_have_security_headers_and_no_wildcard_cors(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in r.headers
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_rules_catalogue_reflects_scorer_and_config(client):
    r = client.get("/api/rules").json()
    assert r["trained_model"] is False and r["scorer"] == "heuristic-v1"
    assert {f["code"] for f in r["factors"]} == {"base", "high_amount", "blocked_country", "online_channel", "high_velocity"}
    assert all(isinstance(f["points"], float) for f in r["factors"])
