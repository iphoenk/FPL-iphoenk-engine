import pytest

from src.engines.v4_recommendation_sanity import sanity_report


def _player(e, name, team, role=.45, unc=.12, raw_xg=.25, raw_xa=.18, prior_xg=.20, prior_xa=.16, weight=.10):
    return {
        "element": e,
        "name": name,
        "position": "MID",
        "xpts_3": 12.0,
        "xpts_5": 20.0,
        "xpts_10": 40.0,
        "xpts_15": 60.0,
        "uncertainty": unc,
        "priors": {"xg90_prior": prior_xg, "xa90_prior": prior_xa, "role_prior": role},
        "fixtures": [{
            "xpts": 4.0,
            "xmins": {"start_probability": .90, "dnp_probability": .02},
            "rates": {"raw_xg90": raw_xg, "raw_xa90": raw_xa, "current_season_weight": weight},
        }] * 5,
    }


def _universe(e, name, team):
    return {
        "element": e,
        "name": name,
        "team": team,
        "team_id": e,
        "position": "MID",
        "ownership": "20.0",
        "transfers_in_event": 50000,
        "transfers_out_event": 5000,
    }


def test_v46_prefers_supported_single_move_over_spiky_multi_move():
    players = [
        _player(1, "OwnedA", "A"), _player(2, "OwnedB", "B"), _player(3, "OwnedC", "C"),
        _player(11, "StrongIn", "D", role=.55, raw_xg=.28, raw_xa=.20),
        _player(12, "SpikeIn", "E", role=.30, unc=.35, raw_xg=1.4, raw_xa=.8, prior_xg=.06, prior_xa=.06),
        _player(13, "OkayIn", "F", role=.25, unc=.18, raw_xg=.30, raw_xa=.20),
    ]
    universe = {"players": [_universe(p["element"], p["name"], p["name"]) for p in players]}
    package = {
        "overall_verdict": "MATERIAL_UPGRADE",
        "best_by_replacement_count": {
            "1": {"replacements": 1, "out": [{"element": 1}], "in": [{"element": 11}], "adjusted_utility_gain_5": 4.5, "classification": "MATERIAL_UPGRADE"},
            "2": {"replacements": 2, "out": [{"element": 1}, {"element": 2}], "in": [{"element": 12}, {"element": 13}], "adjusted_utility_gain_5": 8.0, "classification": "MATERIAL_UPGRADE"},
        },
    }
    out = sanity_report({"point_in_time": True, "players": players}, universe, package, {})
    assert out["best_by_replacement_count"]["1"]["classification"] == "MATERIAL_UPGRADE"
    assert out["best_by_replacement_count"]["2"]["classification"] != "MATERIAL_UPGRADE"
    assert out["recommended_package"]["replacements"] == 1
    assert out["guardrails"]["rate_spike_detection"] is True


def test_v46_requires_point_in_time():
    with pytest.raises(RuntimeError):
        sanity_report({"point_in_time": False, "players": []}, {"players": []}, {"best_by_replacement_count": {}}, {})
