"""Lab Experiment 11: systematic black-box test design (syllabus Unit IV) run with pytest.

Technique ids (BVA-n, ECP-n, DT-n) are referenced from the test-case tables in the lab file.
"""
import pytest

from app.services.scoring import HeuristicScorer, RiskConfig, ScoringInput, decide
from conftest import tx

CFG, S = RiskConfig(), HeuristicScorer()


def verdict(**kw):
    inp = ScoringInput(**{**dict(amount_inr=100, country="IN", channel="POS", prior_tx_24h=0), **kw})
    r = S.score(inp, CFG)
    return r.score, decide(r.score, CFG)


# ---------------- Boundary value analysis (BVA) ----------------
@pytest.mark.parametrize("case,amount,ok", [
    ("BVA-1 below minimum", 0, False), ("BVA-2 minimum", 0.01, True), ("BVA-3 just above minimum", 0.02, True),
    ("BVA-4 just below maximum", 99_999_999.99, True), ("BVA-5 maximum", 100_000_000, True), ("BVA-6 above maximum", 100_000_000.01, False)])
def test_bva_amount_field(empty_client, case, amount, ok):
    assert (empty_client.post("/api/transactions", json=tx(amount=amount)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,token,ok", [
    ("BVA-7 3 chars", "ABC", False), ("BVA-8 4 chars", "ABCD", True), ("BVA-9 5 chars", "ABCDE", True),
    ("BVA-10 39 chars", "A" * 39, True), ("BVA-11 40 chars", "A" * 40, True), ("BVA-12 41 chars", "A" * 41, False)])
def test_bva_card_token_length(empty_client, case, token, ok):
    assert (empty_client.post("/api/transactions", json=tx(card_token=token)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,country,ok", [("BVA-13 1 letter", "I", False), ("BVA-14 2 letters", "IN", True), ("BVA-15 3 letters", "IND", False)])
def test_bva_country_length(empty_client, case, country, ok):
    assert (empty_client.post("/api/transactions", json=tx(country=country)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,n,ok", [("BVA-16 27 features", 27, False), ("BVA-17 28 features", 28, True), ("BVA-18 29 features", 29, False)])
def test_bva_anonymised_feature_count(empty_client, case, n, ok):
    assert (empty_client.post("/api/transactions", json=tx(anon_features=[0.0] * n)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,amount,flagged", [("BVA-19 just below threshold", 49_999.99, False), ("BVA-20 at threshold", 50_000, False), ("BVA-21 just above threshold", 50_000.01, True)])
def test_bva_high_amount_rule(case, amount, flagged):
    assert ("high_amount" in {f.code for f in S.score(ScoringInput(amount_inr=amount, country="IN", channel="POS", prior_tx_24h=0), CFG).factors}) is flagged, case


@pytest.mark.parametrize("case,prior,flagged", [("BVA-22 limit-1", 3, False), ("BVA-23 limit", 4, True), ("BVA-24 limit+1", 5, True)])
def test_bva_velocity_rule(case, prior, flagged):
    assert ("high_velocity" in {f.code for f in S.score(ScoringInput(amount_inr=10, country="IN", channel="POS", prior_tx_24h=prior), CFG).factors}) is flagged, case


@pytest.mark.parametrize("case,score,expected", [
    ("BVA-25", 0.2499, "APPROVE"), ("BVA-26", 0.25, "APPROVE"), ("BVA-27", 0.2501, "HOLD"),
    ("BVA-28", 0.6499, "HOLD"), ("BVA-29", 0.65, "HOLD"), ("BVA-30", 0.6501, "DECLINE")])
def test_bva_decision_thresholds(case, score, expected):
    assert decide(score, CFG) == expected, case


# ---------------- Equivalence class partitioning (ECP) ----------------
@pytest.mark.parametrize("case,channel,ok", [("ECP-1", "POS", True), ("ECP-2", "ONLINE", True), ("ECP-3", "ATM", True), ("ECP-4", "WALLET", True),
                                             ("ECP-5 invalid", "FAX", False), ("ECP-6 invalid case", "online", False), ("ECP-7 invalid empty", "", False)])
def test_ecp_channel(empty_client, case, channel, ok):
    assert (empty_client.post("/api/transactions", json=tx(channel=channel)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,currency,ok", [(f"ECP-{8 + i}", c, True) for i, c in enumerate(["INR", "USD", "EUR", "GBP", "AED", "SGD"])] + [("ECP-14 invalid", "JPY", False), ("ECP-15 invalid", "inr", False)])
def test_ecp_currency(empty_client, case, currency, ok):
    assert (empty_client.post("/api/transactions", json=tx(currency=currency)).status_code == 200) is ok, case


@pytest.mark.parametrize("case,token,ok", [
    ("ECP-16 valid synthetic token", "SYNTH-IN-1001", True), ("ECP-17 underscores and hyphens", "a_b-c_9", True),
    ("ECP-18 contains space", "BAD TOKEN", False), ("ECP-19 contains symbol", "BAD$TOKEN", False), ("ECP-20 markup", "<b>abc</b>", False),
    ("ECP-21 16-digit card number", "4111111111111111", False), ("ECP-22 19-digit card number", "4" * 19, False)])
def test_ecp_card_token_classes(empty_client, case, token, ok):
    assert (empty_client.post("/api/transactions", json=tx(card_token=token)).status_code == 200) is ok, case


# ---------------- Decision-table testing (DT) over the three independent rules ----------------
# conditions: blocked country (C1), amount above limit (C2), online channel (C3); action: score and decision
DT = [
    ("DT-1", False, False, False, 0.04, "APPROVE"), ("DT-2", False, False, True, 0.14, "APPROVE"), ("DT-3", False, True, False, 0.39, "HOLD"),
    ("DT-4", False, True, True, 0.49, "HOLD"), ("DT-5", True, False, False, 0.79, "DECLINE"), ("DT-6", True, False, True, 0.89, "DECLINE"),
    ("DT-7", True, True, False, 1.0, "DECLINE"), ("DT-8", True, True, True, 1.0, "DECLINE")]


@pytest.mark.parametrize("case,c1,c2,c3,score,decision", DT)
def test_decision_table_rules_to_decision(case, c1, c2, c3, score, decision):
    got = verdict(country="KP" if c1 else "IN", amount_inr=60_000 if c2 else 100, channel="ONLINE" if c3 else "POS")
    assert got == (score, decision), case


# ---------------- State-transition cases for the alert life cycle ----------------
@pytest.mark.parametrize("case,first,second,expected", [
    ("ST-1 fraud then fraud", "CONFIRMED_FRAUD", "CONFIRMED_FRAUD", 409), ("ST-2 fraud then false positive", "CONFIRMED_FRAUD", "FALSE_POSITIVE", 409),
    ("ST-3 false positive then fraud", "FALSE_POSITIVE", "CONFIRMED_FRAUD", 409), ("ST-4 false positive twice", "FALSE_POSITIVE", "FALSE_POSITIVE", 409)])
def test_alert_resolves_exactly_once(empty_client, case, first, second, expected):
    tid = empty_client.post("/api/transactions", json=tx()).json()["id"]
    assert empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": first}).status_code == 200
    assert empty_client.post(f"/api/alerts/{tid}/review", json={"verdict": second}).status_code == expected, case
