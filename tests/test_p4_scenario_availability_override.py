from __future__ import annotations

import pytest

from src.engines.v12_player_minutes import estimate_player_minutes
from src.models.historical_projection import build as build_projection


def _player() -> dict:
    return {
        "id": 1,
        "web_name": "P1",
        "team": 1,
        "element_type": 3,
        "now_cost": 70,
        "status": "a",
        "selected_by_percent": "10",
        "starts": 4,
        "minutes": 330,
        "chance_of_playing_next_round": 100,
        "expected_goals": 1.2,
        "expected_assists": 1.5,
        "bonus": 4,
        "saves": 0,
    }


def _inputs() -> tuple[dict, dict]:
    bootstrap = {
        "teams": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "elements": [_player()],
    }
    strength = {
        "baseline": {"home_goals": 1.3, "away_goals": 1.3},
        "teams": [
            {"team_id": 1, "matches_played": 5},
            {"team_id": 2, "matches_played": 5},
        ],
        "matchups": [
            {
                "event": 5,
                "kickoff_time": "2026-09-20T12:00:00Z",
                "team_h": 1,
                "team_a": 2,
                "home_expected_goals": 1.4,
                "away_expected_goals": 1.0,
                "home_clean_sheet_probability": 0.35,
                "away_clean_sheet_probability": 0.22,
            }
        ],
    }
    return bootstrap, strength


def _projection(*, scenario_overrides=None) -> dict:
    bootstrap, strength = _inputs()
    return build_projection(
        bootstrap,
        strength,
        planning_gw=5,
        prior_payload={"model": "prior", "season": "2025/26", "players": {}},
        horizon=15,
        scenario_overrides=scenario_overrides,
    )


def test_normal_p11_path_is_unchanged_without_scenario_override() -> None:
    player = _player()
    context = {"team_matches_played": 5}
    assert estimate_player_minutes(player, context) == estimate_player_minutes(
        player, context
    )


def test_unauthorized_direct_override_fails_closed() -> None:
    with pytest.raises(
        RuntimeError,
        match="scenario availability override requires explicit authorization",
    ):
        estimate_player_minutes(
            _player(),
            {
                "team_matches_played": 5,
                "scenario_availability_probability_override": 0.0,
            },
        )


def test_owned_unavailable_scenario_flows_through_canonical_p11() -> None:
    normal = _projection()
    scenario = _projection(
        scenario_overrides={
            "1": {
                "override_type": "OWNED_UNAVAILABLE",
                "p_available": 0.0,
            }
        }
    )

    normal_player = normal["players"][0]
    scenario_player = scenario["players"][0]
    xmins = scenario_player["xmins"]

    assert xmins["availability_source"] == "scenario_override"
    assert xmins["expected_minutes"] == pytest.approx(0.0)
    assert xmins["derived_probabilities"]["p_start"] == pytest.approx(0.0)
    assert xmins["derived_probabilities"]["p_cameo"] == pytest.approx(0.0)
    assert xmins["derived_probabilities"]["p_dnp"] == pytest.approx(1.0)
    assert xmins["governance"]["scenario_override_applied"] is True
    assert (
        xmins["governance"]["scenario_override_never_posthoc_mutates_xpts"]
        is True
    )
    assert scenario["governance"]["p4_scenario_override_count"] == 1
    assert scenario["governance"]["p4_scenario_override_private_only"] is True
    assert scenario["governance"]["p4_scenario_override_uses_canonical_p1_1"] is True
    assert (
        scenario["governance"]["p4_scenario_override_posthoc_xpts_mutation"]
        is False
    )

    normal_mean = normal_player["xpts_by_gw"][0]["mean"]
    scenario_mean = scenario_player["xpts_by_gw"][0]["mean"]
    assert scenario_mean < normal_mean


def test_unknown_scenario_override_type_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="unsupported P4 scenario override type"):
        _projection(
            scenario_overrides={
                "1": {
                    "override_type": "POSTHOC_XPTS_HACK",
                    "p_available": 0.0,
                }
            }
        )
