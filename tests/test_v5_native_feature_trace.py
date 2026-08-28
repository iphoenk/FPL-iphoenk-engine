from src.v5.intelligence.native_feature_trace import build_native_feature_trace


def _prediction():
    return {
        "players": [
            {
                "element": 1,
                "team_id": 10,
                "current_season": {"starts": 2, "minutes": 170},
                "historical_prior": {
                    "source": "historical_store",
                    "start_probability": 0.82,
                    "avg_minutes_when_start": 78,
                },
                "xmins": {
                    "historical_prior": {
                        "available": True,
                        "start_probability": 0.82,
                        "starter_minutes_prior": 78,
                        "evidence_minutes": 1800,
                    }
                },
                "rates": {"historical_attacking_prior_weight": 0.4},
                "role": {
                    "role_start_probability": 0.9,
                    "rotation_risk": 0.1,
                    "set_piece_share": 0.6,
                    "penalty_share": 0.0,
                    "set_piece_source": "role_registry",
                },
                "fixtures": [{"event": 2, "xpts": 5.1}],
                "defensive_contribution": {
                    "source": "player_cbit_cbirt_shrunk_to_position_prior",
                    "expected_points90": 0.8,
                    "evidence_minutes": 900,
                },
            }
        ]
    }


def _enrichment():
    return {
        "advanced_stats": {
            "source": "fpl_core_insights",
            "players": {
                "1": {
                    "shots": 8,
                    "shot_xg": 1.2,
                    "xg": 1.1,
                    "xa": 0.4,
                    "clearances": 12,
                    "blocks": 3,
                    "interceptions": 4,
                    "tackles": 5,
                }
            },
        },
        "current_form": {
            "source": "official_fpl+fpl_core_insights+understat_challenger",
            "players": {"1": {"official_form": 6.2, "points_per_game": 5.5}},
        },
        "schedule": {
            "league_rest_days": {"10": {"minimum_pl_rest_days": 4.0}},
            "cross_competition_rest_days": {"10": {"minimum_cross_competition_rest_days": 2.5}},
        },
        "preseason": {
            "evidence_status": "AVAILABLE",
            "row_count": 20,
            "friendly_fixture_count": 3,
        },
    }


def test_native_trace_separates_authoritative_and_available_only_features():
    trace = build_native_feature_trace(_prediction(), _enrichment())
    states = trace["players"]["1"]["states"]

    assert states["historical_prior"]["state"] == "ACTIVE"
    assert set(states["historical_prior"]["effect_scopes"]) == {
        "AUTHORITATIVE_XMINS",
        "AUTHORITATIVE_XPTS",
    }
    assert states["historical_prior"]["authoritative_effect"] is True

    assert states["role_intelligence"]["state"] == "ACTIVE"
    assert set(states["role_intelligence"]["effect_scopes"]) == {
        "AUTHORITATIVE_XMINS",
        "AUTHORITATIVE_XPTS",
    }
    assert states["team_strength_fixture_context"]["effect_scopes"] == ["AUTHORITATIVE_XPTS"]
    assert states["advanced_defensive_contribution"]["effect_scopes"] == ["AUTHORITATIVE_XPTS"]

    for name in ("advanced_attacking_stats", "current_form_enrichment", "rest_congestion"):
        assert states[name]["state"] == "AVAILABLE"
        assert states[name]["authoritative_effect"] is False
        assert states[name]["consumption_evidence"] == []

    assert states["preseason_player_evidence"]["state"] == "UNAVAILABLE"
    assert "no player attribution" in states["preseason_player_evidence"]["reason"]

    aggregate = trace["aggregate_feature_bundle"]["states"]
    assert aggregate["preseason_player_evidence"]["state"] == "AVAILABLE"
    assert aggregate["preseason_player_evidence"]["authoritative_effect"] is False
    assert {
        "advanced_attacking_stats",
        "current_form_enrichment",
        "rest_congestion",
        "preseason_player_evidence",
    }.issubset(set(trace["unintegrated_features"]))


def test_trace_does_not_claim_empirical_defcon_when_projection_used_fallback():
    prediction = _prediction()
    prediction["players"][0]["defensive_contribution"]["source"] = "position_prior_probability_calibrated"
    trace = build_native_feature_trace(prediction, _enrichment())
    state = trace["players"]["1"]["states"]["advanced_defensive_contribution"]
    assert state["state"] == "AVAILABLE"
    assert state["authoritative_effect"] is False
    assert state["effect_scopes"] == []


def test_trace_is_observability_only_and_never_mutates_prediction_values():
    prediction = _prediction()
    before = prediction["players"][0]["fixtures"][0]["xpts"]
    trace = build_native_feature_trace(prediction, _enrichment())
    assert prediction["players"][0]["fixtures"][0]["xpts"] == before
    assert trace["governance"]["telemetry_does_not_change_prediction_values"] is True
