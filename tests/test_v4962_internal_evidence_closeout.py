from src.engines.framework_health_audit import _probe_fixture_swing, _probe_sustainability
from src.models.v4_prediction import fixture_run_summary


def _fixture(adj):
    return {
        "xpts": 4.0,
        "calibration": {"fixture_adjustment": adj, "last_season_weight": 0.4},
        "rates": {
            "xg90": 0.4, "xa90": 0.2, "raw_xg90": 0.8, "raw_xa90": 0.3,
            "current_season_weight": 0.2,
        },
        "provenance": {"attacking_rate_shrinkage": True},
    }


def test_fixture_run_summary_uses_canonical_adjustments_only():
    rows = [_fixture(x) for x in ([0.8] * 5 + [1.1] * 5 + [0.95] * 5)]
    out = fixture_run_summary(rows)
    assert out["source"] == "official_fpl_fixture_adjustment"
    assert out["direction"] == "IMPROVING"
    assert out["swing_next5_vs_first5"] == 0.3
    assert len(out["windows"]) == 3
    assert out["decision_usage"] == "multi_horizon_projection_context"


def test_sustainability_probe_proves_shrinkage_is_consumed():
    players = [{"fixtures": [_fixture(1.0)]}, {"fixtures": [_fixture(0.9)]}]
    ok, detail = _probe_sustainability(players)
    assert ok is True
    assert detail["shrinkage_evidence_covered"] == 2
    assert detail["material_shrinkage_players"] == 2
    assert detail["canonical_owner"] == "src.models.v4_prediction.rates"


def test_fixture_swing_probe_requires_explicit_prediction_owned_summary():
    a = fixture_run_summary([_fixture(x) for x in ([0.8] * 5 + [1.1] * 5 + [0.95] * 5)])
    b = fixture_run_summary([_fixture(x) for x in ([1.1] * 5 + [0.85] * 5 + [1.0] * 5)])
    ok, detail = _probe_fixture_swing([{"fixture_run": a}, {"fixture_run": b}])
    assert ok is True
    assert detail["fixture_run_covered"] == 2
    assert detail["distinct_swing_values"] == 2
    assert detail["canonical_owner"] == "src.models.v4_prediction.fixture_run_summary"
