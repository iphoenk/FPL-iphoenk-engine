from src.engines.prediction_evaluation import _decision_validation


def _actual(points):
    return [{"element": element, "points": value, "minutes": 90, "started": 1, "clean_sheet": 0} for element, value in points.items()]


def test_missing_decision_snapshot_is_never_retroactively_reconstructed():
    out = _decision_validation(None, _actual({1: 10, 2: 5}))
    assert out["captain_regret"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"
    assert out["xi_regret"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"
    assert out["transfer_comparator_realized_net_gain"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"


def test_captain_and_xi_regret_use_only_frozen_decision_universe():
    owned = [
        {"element": 1, "position": "GK"},
        {"element": 2, "position": "GK"},
        {"element": 3, "position": "DEF"},
        {"element": 4, "position": "DEF"},
        {"element": 5, "position": "DEF"},
        {"element": 6, "position": "DEF"},
        {"element": 7, "position": "DEF"},
        {"element": 8, "position": "MID"},
        {"element": 9, "position": "MID"},
        {"element": 10, "position": "MID"},
        {"element": 11, "position": "MID"},
        {"element": 12, "position": "MID"},
        {"element": 13, "position": "FWD"},
        {"element": 14, "position": "FWD"},
        {"element": 15, "position": "FWD"},
    ]
    selected = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    snapshot = {
        "lineup": {
            "starting_xi": [x for x in owned if x["element"] in selected],
            "owned_squad": owned,
            "captain": 13,
            "captain_candidates": [13, 14],
        },
        "comparator": {"comparisons": []},
    }
    points = {i: 2 for i in range(1, 16)}
    points[14] = 12
    points[15] = 9
    points[2] = 8
    out = _decision_validation(snapshot, _actual(points))
    assert out["captain_regret"]["status"] == "SETTLED"
    assert out["captain_regret"]["value"] == 10.0
    assert out["xi_regret"]["status"] == "SETTLED"
    assert out["xi_regret"]["value"] > 0


def test_transfer_net_gain_does_not_substitute_optimizer_penalty_for_hit_cost():
    snapshot = {
        "lineup": {"starting_xi": [], "owned_squad": [], "captain": None, "captain_candidates": []},
        "comparator": {"comparisons": [{
            "player_out": 1,
            "player_in": 2,
            "state": "REVIEW",
            "exact_hit_cost": None,
            "hit_cost_state": "UNAVAILABLE_EXACT_HIT_COST",
        }]},
    }
    out = _decision_validation(snapshot, _actual({1: 2, 2: 10}))
    metric = out["transfer_comparator_realized_net_gain"]
    assert metric["status"] == "PARTIAL_GROSS_ONLY"
    assert metric["value"] is None
    assert metric["comparisons"][0]["realized_gross_points_delta_1gw"] == 8.0
    assert metric["comparisons"][0]["net_gain_state"] == "UNAVAILABLE_EXACT_HIT_COST"
