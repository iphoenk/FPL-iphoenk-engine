from src.v5.intelligence.advanced_prediction import enrich_prediction


def _base_player():
    return {
        "element": 1,
        "current_season": {"minutes": 90},
        "rates": {"xg90": 0.3, "xa90": 0.2, "dc90": 0.4, "sources": {"dc90": "position_prior_probability_calibrated"}},
        "xmins": {
            "start_probability": 0.8,
            "bench_probability": 0.15,
            "dnp_probability": 0.05,
            "starter_minutes_if_start": 75,
            "bench_minutes_if_used": 18,
        },
        "uncertainty": 2.0,
        "mean_xpts": 5.0,
    }


def test_advanced_prediction_never_replaces_base_xpts_and_defcon_prior_not_active():
    base = {"players": [_base_player()]}
    out = enrich_prediction(base, {})
    row = out["players"][0]
    assert row["mean_xpts"] == 5.0
    assert row["advanced"]["authoritative_xpts_replaced"] is False
    assert row["advanced"]["xmins_distribution"]["dnp_probability"] == 0.05
    assert row["advanced"]["defcon_probability"] is None
    assert row["advanced"]["feature_bundle"]["states"]["defcon_probability"]["state"] == "UNAVAILABLE"


def test_empirical_player_defcon_probability_is_active_with_consumption_evidence():
    player = _base_player()
    player["rates"]["dc90"] = 1.1
    player["rates"]["sources"]["dc90"] = "player_cbit_cbirt_shrunk_to_position_prior"
    player["defensive_contribution"] = {
        "model": "poisson_threshold_shrunk_rate_v1",
        "eligible": True,
        "threshold": 10,
        "points_on_threshold": 2,
        "count_rate_per90": 12.5,
        "threshold_probability_90": 0.55,
        "expected_points90": 1.1,
        "evidence_minutes": 900,
        "sample_quality": "ESTABLISHED",
        "source": "player_cbit_cbirt_shrunk_to_position_prior",
    }
    out = enrich_prediction({"players": [player]}, {})
    row = out["players"][0]
    evidence = row["advanced"]["defcon_probability"]
    state = row["advanced"]["feature_bundle"]["states"]["defcon_probability"]
    aggregate = out["advanced_prediction"]["feature_bundle"]["states"]["defcon_probability"]
    assert evidence["threshold_probability_90"] == 0.55
    assert evidence["evidence_minutes"] == 900
    assert state["state"] == "ACTIVE"
    assert state["consumed_by"] == ["advanced_prediction"]
    assert aggregate["state"] == "ACTIVE"
