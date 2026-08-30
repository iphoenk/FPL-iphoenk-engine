from copy import deepcopy

from src.runtime_v3.incremental_reuse import (
    _prediction_official_snapshot,
    _prediction_team_state,
    _semantic_hash,
)


def _team_payload():
    return {
        "generated_at": "2026-08-30T00:00:00+00:00",
        "entry": {
            "id": 3462711,
            "summary_overall_points": 94,
            "summary_overall_rank": 1474227,
            "summary_event_points": 23,
            "summary_event_rank": 6315078,
            "fetched_at": "2026-08-30T00:00:00+00:00",
        },
        "totals": {"market_value": 1001, "sell_value": 995, "itb": 5},
        "team_value_ledger": [
            {"element": 572, "purchase_cost": 45, "now_cost": 45, "sell_cost": 45},
            {"element": 411, "purchase_cost": 140, "now_cost": 141, "sell_cost": 140},
        ],
    }


def test_prediction_team_semantic_state_ignores_non_consumed_metadata():
    base = _team_payload()
    changed = deepcopy(base)
    changed["generated_at"] = "2026-08-30T01:00:00+00:00"
    changed["entry"]["summary_overall_points"] = 999
    changed["entry"]["summary_overall_rank"] = 1
    changed["entry"]["summary_event_points"] = 88
    changed["entry"]["summary_event_rank"] = 2
    changed["entry"]["fetched_at"] = "2026-08-30T01:00:00+00:00"
    changed["totals"]["market_value"] = 2000
    changed["totals"]["sell_value"] = 1999

    assert _prediction_team_state(base) == _prediction_team_state(changed)
    assert _semantic_hash(_prediction_team_state(base), top_level=True) == _semantic_hash(
        _prediction_team_state(changed), top_level=True
    )


def test_prediction_team_semantic_state_invalidates_on_owned_sell_value_or_itb():
    base = _team_payload()
    baseline = _semantic_hash(_prediction_team_state(base), top_level=True)

    changed_element = deepcopy(base)
    changed_element["team_value_ledger"][0]["element"] = 109
    assert _semantic_hash(_prediction_team_state(changed_element), top_level=True) != baseline

    changed_sell = deepcopy(base)
    changed_sell["team_value_ledger"][0]["sell_cost"] = 46
    assert _semantic_hash(_prediction_team_state(changed_sell), top_level=True) != baseline

    changed_itb = deepcopy(base)
    changed_itb["totals"]["itb"] = 6
    assert _semantic_hash(_prediction_team_state(changed_itb), top_level=True) != baseline


def test_prediction_official_semantic_state_ignores_health_but_invalidates_material_player_input():
    base = {
        "phase": {"planning_gw": 3},
        "endpoint_health": {"bootstrap": {"latency_ms": 100}},
        "bootstrap": {
            "teams": [
                {
                    "id": 1,
                    "name": "Arsenal",
                    "strength_attack_home": 1300,
                    "strength_attack_away": 1250,
                    "strength_defence_home": 1280,
                    "strength_defence_away": 1220,
                }
            ],
            "elements": [
                {
                    "id": 8,
                    "element_type": 2,
                    "team": 1,
                    "web_name": "Calafiori",
                    "now_cost": 55,
                    "status": "a",
                    "selected_by_percent": "10.0",
                    "starts": 2,
                    "minutes": 180,
                    "expected_goals": "0.10",
                    "expected_assists": "0.20",
                    "bonus": 2,
                    "saves": 0,
                    "chance_of_playing_next_round": 100,
                }
            ],
        },
        "fixtures": [
            {
                "event": 3,
                "kickoff_time": "2026-09-04T19:00:00Z",
                "finished": False,
                "team_h": 1,
                "team_a": 2,
                "team_h_score": None,
                "team_a_score": None,
            }
        ],
    }
    health_only = deepcopy(base)
    health_only["endpoint_health"]["bootstrap"]["latency_ms"] = 9999
    assert _prediction_official_snapshot(base) == _prediction_official_snapshot(health_only)

    material = deepcopy(base)
    material["bootstrap"]["elements"][0]["now_cost"] = 56
    assert _semantic_hash(_prediction_official_snapshot(base), top_level=True) != _semantic_hash(
        _prediction_official_snapshot(material), top_level=True
    )
