from copy import deepcopy

from src.v5.intelligence.fixture_congestion_overlay import build_fixture_congestion_overlay
from src.v5.intelligence.native_feature_trace import build_native_feature_trace
from src.v5.intelligence.xmins import estimate_xmins


def _bootstrap_player():
    return {
        "id": 1,
        "team": 10,
        "starts": 2,
        "minutes": 170,
        "status": "a",
        "chance_of_playing_next_round": None,
    }


def _fixtures():
    return [
        {"event": 1, "team_h": 10, "team_a": 20, "kickoff_time": "2026-09-05T18:00:00Z"},
        {"event": 2, "team_h": 30, "team_a": 10, "kickoff_time": "2026-09-10T18:00:00Z"},
        {"event": 3, "team_h": 10, "team_a": 40, "kickoff_time": "2026-09-17T18:00:00Z"},
    ]


def _enrichment():
    return {
        "advanced_stats": {},
        "current_form": {"players": {}},
        "preseason": {"evidence_status": "UNAVAILABLE"},
        "schedule": {
            "cross_competition_fixtures": [
                {
                    "fpl_team_id": 10,
                    "kickoff_time": "2026-09-12T18:00:00Z",
                    "competition_class": "EUROPE",
                    "source": "api_football",
                }
            ]
        },
    }


def _prediction():
    source = _bootstrap_player()
    context = {
        "team_matches_played": 2,
        "role_start_probability": 0.9,
        "rotation_risk": 0.5,
    }
    baseline = estimate_xmins(source, context)
    return {
        "team_strength": {"teams": [{"team_id": 10, "matches_played": 2}]},
        "players": [
            {
                "element": 1,
                "team_id": 10,
                "current_season": {"starts": 2, "minutes": 170},
                "historical_prior": None,
                "rates": {"historical_attacking_prior_weight": 0.0},
                "role": {
                    "role_start_probability": 0.9,
                    "rotation_risk": 0.5,
                    "set_piece_share": 0.0,
                    "penalty_share": 0.0,
                },
                "xmins": baseline,
                "xpts_by_gw": [
                    {
                        "gw": 2,
                        "fixtures": [
                            {
                                "gw": 2,
                                "event": 2,
                                "kickoff_time": "2026-09-10T18:00:00Z",
                                "xpts": 5.0,
                            }
                        ],
                    }
                ],
                "fixtures": [{"event": 2, "xpts": 5.0}],
                "defensive_contribution": {},
            }
        ],
    }


def test_fixture_congestion_overlay_changes_shadow_xmins_only():
    prediction = _prediction()
    before = deepcopy(prediction)
    overlay = build_fixture_congestion_overlay(
        prediction,
        {"elements": [_bootstrap_player()]},
        _fixtures(),
        _enrichment(),
    )
    row = overlay["players"]["1"]
    fixture = row["fixtures"][0]

    assert overlay["application_mode"] == "SHADOW_ONLY"
    assert row["applied_fixtures"] == 1
    assert fixture["congestion"]["factor"] == 0.96
    assert fixture["shadow"]["expected_minutes"] < fixture["baseline"]["expected_minutes"]
    assert fixture["delta"]["expected_minutes"] < 0
    assert fixture["authoritative_xmins_replaced"] is False
    assert row["authoritative_xpts_replaced"] is False
    assert prediction == before
    assert overlay["governance"]["authoritative_prediction_unchanged"] is True


def test_feature_trace_reports_rest_congestion_as_shadow_not_authoritative():
    prediction = _prediction()
    overlay = build_fixture_congestion_overlay(
        prediction,
        {"elements": [_bootstrap_player()]},
        _fixtures(),
        _enrichment(),
    )
    prediction["players"][0]["fixture_congestion_overlay"] = overlay["players"]["1"]
    trace = build_native_feature_trace(prediction, _enrichment())
    state = trace["players"]["1"]["states"]["rest_congestion"]

    assert state["state"] == "ACTIVE"
    assert state["effect_scopes"] == ["SHADOW_OVERLAY"]
    assert state["authoritative_effect"] is False
    assert "rest_congestion" in trace["shadow_only_features"]
    assert "rest_congestion" in trace["unintegrated_features"]
    assert "rest_congestion" not in trace["available_only_features"]
