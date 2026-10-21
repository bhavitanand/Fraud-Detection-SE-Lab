import pytest

from app.services.scoring import HeuristicScorer, RiskConfig, ScoringInput, decide

CFG = RiskConfig()
S = HeuristicScorer()


def score(**kw):
    base = dict(amount=50, country="US", channel="POS", prior_tx_24h=0)
    return S.score(ScoringInput(**{**base, **kw}), CFG)


def test_baseline_only():
    r = score()
    assert r.score == 0.04 and [f.code for f in r.factors] == ["base"]


def test_each_factor_adds_its_documented_points():
    assert score(amount=1500.01).score == 0.39
    assert score(amount=1500).score == 0.04  # strictly greater than the limit
    assert score(country="xx").score == 0.79
    assert score(channel="ONLINE").score == 0.14
    assert score(prior_tx_24h=3).score == 0.04 and score(prior_tx_24h=4).score == 0.29


def test_score_is_capped_at_one_and_factors_explain_total():
    r = score(amount=9000, country="XX", channel="ONLINE", prior_tx_24h=9)
    assert r.score == 1.0
    assert {f.code for f in r.factors} == {"base", "high_amount", "blocked_country", "online_channel", "high_velocity", "score_cap"}
    assert round(sum(f.points for f in r.factors), 3) == r.score


@pytest.mark.parametrize("value,expected", [(0.0, "APPROVE"), (0.25, "APPROVE"), (0.2501, "HOLD"), (0.65, "HOLD"), (0.6501, "DECLINE"), (1.0, "DECLINE")])
def test_decision_boundaries(value, expected):
    assert decide(value, CFG) == expected


def test_custom_thresholds_change_decisions():
    assert decide(0.3, RiskConfig(approve_max=0.5, hold_max=0.9)) == "APPROVE"


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
