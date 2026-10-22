import pytest

from app.services.scoring import HeuristicScorer, HybridScorer, RiskConfig, ScoringInput, decide

CFG = RiskConfig()
S = HeuristicScorer()


def score(**kw):
    base = dict(amount_inr=500, country="IN", channel="POS", prior_tx_24h=0)
    return S.score(ScoringInput(**{**base, **kw}), CFG)


def codes(r):
    return {f.code for f in r.factors}


def test_baseline_only():
    r = score()
    assert r.score == 0.04 and codes(r) == {"base"}


def test_each_basic_factor_adds_its_documented_points():
    assert score(amount_inr=50000.01).score == 0.39
    assert score(amount_inr=50000).score == 0.04  # strictly greater than the INR limit
    assert score(country="xx").score == 0.79 and score(country="kp").score == 0.79
    assert score(channel="ONLINE").score == 0.14
    assert score(prior_tx_24h=3).score == 0.04 and score(prior_tx_24h=4).score == 0.29


def test_unusual_amount_needs_history_and_a_minimum():
    hist = dict(history_count=5, history_avg_inr=800.0)
    assert "unusual_amount" in codes(score(amount_inr=4500, **hist))          # > 5x average and > 2000
    assert "unusual_amount" not in codes(score(amount_inr=4000, **hist))      # exactly 5x is not above
    assert "unusual_amount" not in codes(score(amount_inr=1500, history_count=5, history_avg_inr=100.0))  # below the 2000 floor
    assert "unusual_amount" not in codes(score(amount_inr=9000, history_count=2, history_avg_inr=100.0))  # too little history


def test_new_country_and_new_merchant():
    assert "new_country" in codes(score(country="AE", history_count=1))
    assert "new_country" not in codes(score(country="AE", history_count=1, seen_countries=frozenset({"AE"})))
    assert "new_country" not in codes(score(country="AE", history_count=0))      # first ever transaction has no baseline
    assert "new_country" not in codes(score(country="IN", history_count=4))      # home country
    assert "new_merchant" in codes(score(history_count=5, seen_merchant=False))
    assert "new_merchant" not in codes(score(history_count=4, seen_merchant=False))


def test_impossible_travel_uses_distance_and_speed():
    assert "impossible_travel" in codes(score(city="Mumbai", last_city="Delhi", hours_since_last=0.5))      # ~1,150 km in 30 min
    assert "impossible_travel" not in codes(score(city="Mumbai", last_city="Delhi", hours_since_last=26))   # a day later is plausible
    assert "impossible_travel" not in codes(score(city="Noida", last_city="Delhi", hours_since_last=0.1))   # < 200 km
    assert "impossible_travel" not in codes(score(city="Atlantis", last_city="Delhi", hours_since_last=0.1))  # unknown city: no claim


def test_benchmark_rows_skip_rules():
    r = score(rules_applicable=False, amount_inr=900000, country="XX", channel="ONLINE")
    assert codes(r) == {"base"}


def test_score_is_capped_at_one_and_factors_explain_total():
    r = score(amount_inr=90000, country="XX", channel="ONLINE", prior_tx_24h=9)
    assert r.score == 1.0 and "score_cap" in codes(r)
    assert round(sum(f.points for f in r.factors), 3) == r.score


@pytest.mark.parametrize("value,expected", [(0.0, "APPROVE"), (0.25, "APPROVE"), (0.2501, "HOLD"), (0.65, "HOLD"), (0.6501, "DECLINE"), (1.0, "DECLINE")])
def test_decision_boundaries(value, expected):
    assert decide(value, CFG) == expected


def test_custom_thresholds_change_decisions():
    assert decide(0.3, RiskConfig(approve_max=0.5, hold_max=0.9)) == "APPROVE"


class FakeModels:
    def __init__(self, p):
        self.p = p

    def predict(self, features, amount):
        return (self.p, 7, "fake-model") if self.p is not None else None


def test_hybrid_combines_rules_and_model_as_noisy_or():
    h = HybridScorer(S, FakeModels(0.9))
    inp = ScoringInput(amount_inr=10, country="IN", channel="POS", prior_tx_24h=0, rules_applicable=False, anon_features=(0.0,) * 28, amount_raw=10)
    r = h.score(inp, CFG)
    assert r.score == round(1 - (1 - 0.04) * (1 - 0.9), 3) and r.model_id == 7 and "ml_model" in codes(r)
    assert round(sum(f.points for f in r.factors), 3) == r.score


def test_hybrid_falls_back_to_rules_without_features_or_model():
    plain = ScoringInput(amount_inr=10, country="IN", channel="POS", prior_tx_24h=0)
    assert "ml_model" not in codes(HybridScorer(S, FakeModels(0.9)).score(plain, CFG))
    with_f = ScoringInput(amount_inr=10, country="IN", channel="POS", prior_tx_24h=0, anon_features=(0.0,) * 28)
    r = HybridScorer(S, FakeModels(None)).score(with_f, CFG)
    assert "ml_model" not in codes(r) and r.model_id is None


def test_scorer_is_swappable(tmp_path):
    """A different Scorer implementation plugs in without touching the API."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.scoring import ScoreResult
    from conftest import make_settings, tx

    class Always:
        version = "stub-v0"

        def score(self, t, cfg):
            return ScoreResult(0.9, [], self.version)

    with TestClient(create_app(make_settings(tmp_path, seed_demo=False), scorer=Always())) as c:
        out = c.post("/api/transactions", json=tx(amount=5, channel="POS")).json()
        assert out["decision"] == "DECLINE" and out["scorer"] == "stub-v0"
