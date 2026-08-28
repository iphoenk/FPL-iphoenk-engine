from __future__ import annotations

from src.models.observed_tactical_context import (
    _percentile,
    build_current_recent_rows,
    merge_recent_history,
    player_return_routes,
    summarize_team_history,
)


def _cfg():
    return {
        "contract": "TACTICAL_OBSERVED_CONTEXT_V1",
        "recent_gw_window": 5,
        "classification": {
            "high_percentile": 0.75,
            "maximum_team_signals": 3,
            "maximum_zone_signals": 2,
            "confidence_by_matches": {"1": "LOW", "2": "MEDIUM", "4": "HIGH"},
        },
        "shot_zones": {
            "close_distance_max": 12.0,
            "box_distance_max": 18.0,
            "central_y_min": 35.0,
            "central_y_max": 65.0,
        },
    }


def test_tied_zero_values_are_midrank_not_false_top_percentile():
    assert _percentile(0.0, [0.0, 0.0, 0.0, 0.0]) == 0.5
    assert _percentile(2.0, [0.0, 1.0, 2.0, 3.0]) == 0.625


def test_current_match_events_create_observed_recent_context_without_fake_pressing():
    elements = [
        {"id": 1, "team": 1}, {"id": 2, "team": 1},
        {"id": 3, "team": 2}, {"id": 4, "team": 2},
    ]
    match = {
        "gw": 1,
        "source": "FPL-Core-Insights",
        "dataset": "playermatchstats",
        "fetched_at": "2026-08-28T00:00:00Z",
        "rows": [
            {"player_id": "1", "match_id": "m1", "total_shots": "6", "xg": "1.4", "xa": "0.5", "touches_opposition_box": "18", "chances_created": "5", "final_third_passes": "20", "accurate_crosses": "4", "corners": "5", "recoveries": "8", "tackles": "3", "interceptions": "2"},
            {"player_id": "2", "match_id": "m1", "total_shots": "3", "xg": "0.6", "xa": "0.2", "touches_opposition_box": "9", "chances_created": "2", "final_third_passes": "15", "accurate_crosses": "2", "recoveries": "6", "tackles": "2", "interceptions": "1"},
            {"player_id": "3", "match_id": "m1", "total_shots": "2", "xg": "0.2", "xa": "0.1", "touches_opposition_box": "5", "chances_created": "1", "final_third_passes": "8", "accurate_crosses": "1", "recoveries": "5", "tackles": "2", "interceptions": "1"},
            {"player_id": "4", "match_id": "m1", "total_shots": "1", "xg": "0.1", "xa": "0.0", "touches_opposition_box": "2", "chances_created": "0", "final_third_passes": "5", "recoveries": "4", "tackles": "2", "interceptions": "1"},
        ],
    }
    shots = {
        "dataset": "shots",
        "fetched_at": "2026-08-28T00:00:00Z",
        "rows": [
            {"match_id": "m1", "player_id": "1", "is_home": "True", "start_x": "8", "start_y": "50", "situation": "assisted"},
            {"match_id": "m1", "player_id": "1", "is_home": "True", "start_x": "15", "start_y": "20", "situation": "corner"},
            {"match_id": "m1", "player_id": "3", "is_home": "False", "start_x": "25", "start_y": "50", "situation": "regular"},
        ],
    }
    systems = {
        "1": {"matches": [{"match_id": "m1", "valid": True, "fpl_position_shape": "4-3-3"}]},
        "2": {"matches": [{"match_id": "m1", "valid": True, "fpl_position_shape": "4-4-2"}]},
    }
    rows = build_current_recent_rows(elements, match, shots, systems, _cfg())
    assert set(rows) == {1, 2}
    alpha = rows[1][0]
    beta = rows[2][0]
    assert alpha["formation"] == "4-3-3"
    assert alpha["pressing_pattern"] is None
    assert alpha["possession_pattern"] is None
    assert alpha["chance_creation_zones"]
    assert beta["chance_concession_zones"]
    assert alpha["evidence"]["true_pressing_not_inferred"] is True
    assert alpha["observed_style_proxies"]
    assert all(float(item["observed_value"]) > 0 for item in alpha["observed_style_proxies"])


def test_rolling_history_deduplicates_current_gw_and_keeps_window():
    previous = {
        "teams": {
            "1": [
                {"gw": 1, "match_id": "m1", "opponent_team_id": 2, "formation": "4-3-3"},
                {"gw": 0, "match_id": "m0", "opponent_team_id": 3, "formation": "4-2-3-1"},
            ]
        }
    }
    current = {1: [{"gw": 1, "match_id": "m1", "opponent_team_id": 2, "formation": "3-4-3", "strengths": ["box_pressure"]}]}
    merged = merge_recent_history(previous, current, [1], _cfg())
    assert len(merged["1"]) == 2
    assert merged["1"][0]["formation"] == "3-4-3"
    summary = summarize_team_history(merged["1"], _cfg())
    assert summary["matches"] == 2
    assert summary["confidence"] == "MEDIUM"


def test_player_return_routes_only_use_observed_events():
    player = {
        "advanced_current": {
            "totals": {
                "touches_opposition_box": 8,
                "total_shots": 3,
                "xg": 0.7,
                "chances_created": 4,
                "xa": 0.4,
                "corners": 2,
                "penalties_scored": 0,
                "penalties_missed": 0,
            }
        }
    }
    routes = player_return_routes(player)
    assert routes["progression_route"] == "box_pressure"
    assert {"box_pressure", "shot_volume", "chance_creation", "set_piece_activity"} <= set(routes["return_routes"])
    assert "penalty_route" not in routes["return_routes"]
