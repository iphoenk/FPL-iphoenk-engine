import json
from pathlib import Path

import pytest

from src.models.new_signing_adaptation import (
    annotate_prior_team_context,
    apply_adaptation_to_prior,
    build_adaptation,
    classify,
)

ROOT = Path(__file__).resolve().parents[1]


def _player(element=101, code=9001, team_code=20, starts=0, name="Transfer Test"):
    first, second = name.split(" ", 1)
    return {
        "id": element,
        "code": code,
        "team_code": team_code,
        "first_name": first,
        "second_name": second,
        "starts": starts,
    }


def _prior(element=101, start_probability=0.95, minutes=3000, attack_weight=0.75, starter_minutes=88):
    return {
        "players": {
            str(element): {
                "element": element,
                "start_probability": start_probability,
                "avg_minutes_when_start": starter_minutes,
                "minutes": minutes,
                "attacking_prior_weight": attack_weight,
                "xg90": 0.4,
                "xa90": 0.2,
                "identity_match": "stable_player_code",
            }
        },
        "governance": {},
    }


def test_team_change_is_detected_without_changing_player_identity():
    player = _player(team_code=20)
    prior = _prior()
    previous = {
        "rows": [{
            "code": "9001",
            "first_name": "Transfer",
            "second_name": "Test",
            "team_code": "10",
            "team": "Old Club",
        }]
    }
    out = annotate_prior_team_context(prior, [player], previous)
    row = out["players"]["101"]
    assert row["identity_match"] == "stable_player_code"
    assert row["previous_team_code"] == "10"
    assert row["current_team_code"] == "20"
    assert row["team_change_detected"] is True
    assert out["transfer_context_summary"]["team_changes_detected"] == 1


def test_same_club_prior_is_left_untouched():
    player = _player(team_code=20)
    prior = _prior()
    previous = {"rows": [{"code": "9001", "first_name": "Transfer", "second_name": "Test", "team_code": 20}]}
    annotated = annotate_prior_team_context(prior, [player], previous)
    before = dict(annotated["players"]["101"])
    out = apply_adaptation_to_prior(annotated, [player], team_matches_played=1)
    row = out["players"]["101"]
    assert row["team_change_detected"] is False
    assert row["start_probability"] == before["start_probability"]
    assert row["avg_minutes_when_start"] == before["avg_minutes_when_start"]
    assert row["minutes"] == before["minutes"]
    assert row["attacking_prior_weight"] == before["attacking_prior_weight"]
    assert row["transfer_adaptation"]["state"] == "SAME_CLUB"


def test_intra_pl_transfer_shrinks_role_more_than_portable_skill():
    player = _player(team_code=20)
    prior = _prior(start_probability=0.95, minutes=3000, attack_weight=0.80, starter_minutes=88)
    prior["players"]["101"].update({"previous_team_code": "10", "current_team_code": "20", "team_change_detected": True})
    out = apply_adaptation_to_prior(prior, [player], team_matches_played=1)
    row = out["players"]["101"]
    adaptation = row["transfer_adaptation"]

    assert adaptation["state"] == "INTRA_PL_TRANSFER"
    assert row["start_probability"] == pytest.approx(0.7355, abs=1e-4)
    assert row["avg_minutes_when_start"] == pytest.approx(78.1, abs=0.1)
    assert row["attacking_prior_weight"] == pytest.approx(0.60, abs=1e-4)
    assert row["minutes"] == pytest.approx(1500.0, abs=0.1)
    assert row["raw_pre_transfer_adaptation"]["start_probability"] == 0.95
    assert row["raw_pre_transfer_adaptation"]["attacking_prior_weight"] == 0.80
    assert adaptation["confidence_ceiling"] == "MEDIUM"
    assert adaptation["starter_prior_retention"] < adaptation["attacking_prior_retention"]


def test_old_club_starter_prior_retires_after_four_current_team_matches():
    player = _player(team_code=20, starts=2)
    prior = _prior(start_probability=0.95, minutes=3000, attack_weight=0.80, starter_minutes=88)
    prior["players"]["101"].update({"previous_team_code": "10", "current_team_code": "20", "team_change_detected": True})
    out = apply_adaptation_to_prior(prior, [player], team_matches_played=4)
    row = out["players"]["101"]
    assert row["start_probability"] is None
    assert row["avg_minutes_when_start"] is None
    assert row["attacking_prior_weight"] == pytest.approx(0.60, abs=1e-4)
    assert row["transfer_adaptation"]["old_role_prior_retired"] is True


def test_no_previous_pl_prior_is_explicit_and_never_fabricated():
    player = _player()
    assert classify({}) == "NO_PREVIOUS_PL_PRIOR"
    adaptation = build_adaptation(player, {}, team_matches_played=1)
    assert adaptation["state"] == "NO_PREVIOUS_PL_PRIOR"
    assert adaptation["adapted_prior_start_probability"] is None
    assert adaptation["adapted_starter_minutes_prior"] is None
    assert adaptation["attacking_prior_retention"] == 0.0
    assert adaptation["governance"]["cross_league_prior_not_fabricated"] is True


def test_policy_and_runtime_refresh_are_transfer_window_safe():
    policy = json.loads((ROOT / "config/intelligence/new_signing_adaptation.json").read_text())
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    assert policy["contract"] == "NEW_SIGNING_ADAPTATION_V1"
    assert policy["governance"]["player_quality_and_new_club_role_are_separate"] is True
    assert policy["governance"]["cross_league_prior_requires_verified_source_before_model_use"] is True
    assert profiles["profiles"]["fast_decision"]["reuse_services"]["historical_prior"]["max_age_seconds"] <= 3600
    assert profiles["profiles"]["live"]["reuse_services"]["historical_prior"]["max_age_seconds"] <= 3600
