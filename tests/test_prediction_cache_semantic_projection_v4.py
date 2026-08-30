from __future__ import annotations

from copy import deepcopy

from src.services.prediction_model_cache import semantic_fingerprint


def _inputs():
    bootstrap = {
        "elements": [
            {
                "id": 1,
                "code": 1001,
                "web_name": "Player",
                "first_name": "A",
                "second_name": "Player",
                "team": 1,
                "element_type": 3,
                "now_cost": 75,
                "selected_by_percent": "10.0",
                "creativity": "20.0",
                "threat": "30.0",
                "minutes": 180,
                "starts": 2,
                "expected_goals": "0.5",
                "expected_assists": "0.3",
                "defensive_contribution": 4,
                "saves": 0,
                "bps": 30,
                "goals_conceded": 1,
                "status": "a",
                "chance_of_playing_next_round": None,
                "corners_and_indirect_freekicks_order": None,
                "direct_freekicks_order": None,
                "penalties_order": None,
                "transfers_in_event": 100,
                "event_points": 5,
            }
        ],
        "teams": [
            {
                "id": 1,
                "name": "Arsenal",
                "short_name": "ARS",
                "strength_defence_home": 1200,
                "strength_defence_away": 1180,
                "strength_overall_home": 1250,
                "strength_overall_away": 1220,
                "pulse_id": 1,
            },
            {
                "id": 2,
                "name": "Chelsea",
                "short_name": "CHE",
                "strength_defence_home": 1100,
                "strength_defence_away": 1080,
                "strength_overall_home": 1140,
                "strength_overall_away": 1110,
                "pulse_id": 2,
            },
        ],
        "events": [
            {
                "id": 1,
                "finished": True,
                "average_entry_score": 55,
                "highest_score": 120,
                "most_selected": 999,
            },
            {
                "id": 2,
                "finished": False,
                "average_entry_score": 0,
                "highest_score": 0,
                "most_selected": 888,
            },
        ],
    }
    fixtures = [
        {
            "id": 10,
            "event": 2,
            "finished": False,
            "started": False,
            "team_h": 1,
            "team_a": 2,
            "team_h_score": None,
            "team_a_score": None,
            "kickoff_time": "2026-09-01T15:00:00Z",
            "team_h_difficulty": 3,
            "team_a_difficulty": 4,
            "pulse_id": 9999,
            "stats": [{"identifier": "goals_scored", "h": [], "a": []}],
        }
    ]
    return bootstrap, fixtures


def _fingerprint(bootstrap, fixtures):
    return semantic_fingerprint(bootstrap, fixtures, stats_gw=2)


def test_volatile_non_model_official_metadata_does_not_false_invalidate_cache():
    bootstrap, fixtures = _inputs()
    baseline = _fingerprint(bootstrap, fixtures)

    changed_bootstrap = deepcopy(bootstrap)
    changed_fixtures = deepcopy(fixtures)
    changed_bootstrap["events"][0]["average_entry_score"] = 99
    changed_bootstrap["events"][0]["highest_score"] = 200
    changed_bootstrap["events"][0]["most_selected"] = 123
    changed_bootstrap["teams"][0]["name"] = "Reporting label only"
    changed_bootstrap["teams"][0]["pulse_id"] = 777
    changed_bootstrap["elements"][0]["transfers_in_event"] = 999999
    changed_fixtures[0]["pulse_id"] = 12345
    changed_fixtures[0]["stats"] = [{"identifier": "bonus", "h": [{"value": 3}], "a": []}]
    changed_fixtures[0]["started"] = True

    assert _fingerprint(changed_bootstrap, changed_fixtures) == baseline


def test_every_consumed_official_dimension_still_invalidates_exact_cache():
    bootstrap, fixtures = _inputs()
    baseline = _fingerprint(bootstrap, fixtures)

    ownership = deepcopy(bootstrap)
    ownership["elements"][0]["selected_by_percent"] = "10.1"
    assert _fingerprint(ownership, fixtures) != baseline

    event_state = deepcopy(bootstrap)
    event_state["events"][1]["finished"] = True
    assert _fingerprint(event_state, fixtures) != baseline

    difficulty = deepcopy(fixtures)
    difficulty[0]["team_h_difficulty"] = 2
    assert _fingerprint(bootstrap, difficulty) != baseline

    strength = deepcopy(bootstrap)
    strength["teams"][0]["strength_defence_home"] = 1300
    assert _fingerprint(strength, fixtures) != baseline
