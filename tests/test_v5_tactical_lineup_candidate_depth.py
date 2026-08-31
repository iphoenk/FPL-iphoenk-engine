from __future__ import annotations

from src.v5.config_cache import load_json_config
from src.v5.decision.tactical_consumption import apply_lineup_overlay, lineup_gap


def _player(element: int, position: str, key: tuple[int, int, int]) -> dict:
    overlap, highlights, confidence_rank = key
    confidence = {0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}.get(confidence_rank, "LOW")
    routes = [f"r{i}" for i in range(overlap)]
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": element,
        "xmins": {"start_probability": 0.9, "dnp_probability": 0.03},
        "xpts_by_gw": [{"gw": 3, "mean": 5.0, "std": 1.0}],
        "tactical_matchup": {
            "status": "READY",
            "player_return_routes": routes,
            "opponent_vulnerabilities": routes,
            "highlights": [f"h{i}" for i in range(highlights)],
            "evidence_confidence": confidence,
        },
    }


def test_tactical_close_call_surface_matches_deployed_production_depth_and_gap():
    cfg = load_json_config("config/v5_decision_registry.json")
    assert int(cfg["lineup"]["alternatives"]["publish_top_n"]) >= 6
    assert lineup_gap() == 0.75


def test_tactical_overlay_can_reach_deeper_close_canonical_alternative():
    players = [
        _player(1, "GK", (0, 1, 1)),
        *[_player(i, "DEF", (0, 1, 1)) for i in range(2, 7)],
        *[_player(i, "MID", (0, 1, 1)) for i in range(7, 12)],
        *[_player(i, "FWD", (0, 1, 1)) for i in range(12, 15)],
        _player(15, "FWD", (1, 1, 2)),
    ]
    prediction = {"planning_gw": 3, "players": players}
    base_ids = list(range(1, 12))
    tactical_winner = [1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 15]
    alternatives = [
        {"rank": 1, "formation": "5-4-1", "selection_score": 50.00, "mean": 55.0, "element_ids": base_ids},
        {"rank": 2, "formation": "5-3-2", "selection_score": 49.95, "mean": 54.9, "element_ids": [1,2,3,4,5,6,7,8,9,12,13]},
        {"rank": 3, "formation": "4-4-2", "selection_score": 49.90, "mean": 54.8, "element_ids": [1,2,3,4,5,7,8,9,10,12,13]},
        {"rank": 4, "formation": "4-3-3", "selection_score": 49.80, "mean": 54.7, "element_ids": tactical_winner},
        {"rank": 5, "formation": "3-4-3", "selection_score": 49.70, "mean": 54.6, "element_ids": [1,2,3,4,7,8,9,10,12,13,14]},
        {"rank": 6, "formation": "3-5-2", "selection_score": 49.60, "mean": 54.5, "element_ids": [1,2,3,4,7,8,9,10,11,12,13]},
    ]
    lineup = {
        "status": "READY",
        "planning_gw": 3,
        "formation": "5-4-1",
        "selection_score": 50.0,
        "starters": [{"element": eid} for eid in base_ids],
        "alternatives": alternatives,
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "main_starting_xi_battle": {"status": "CLOSE"},
    }
    out = apply_lineup_overlay(lineup, prediction)
    assert {row["element"] for row in out["starters"]} == set(tactical_winner)
    assert out["formation"] == "4-3-3"
    assert out["main_starting_xi_battle"]["tactical_tiebreak"]["applied_to_xi"] is True
