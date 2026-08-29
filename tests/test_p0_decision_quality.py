from __future__ import annotations

import copy

import pytest

from src.engines.p0_decision_quality import (
    assert_projection_signature_unchanged,
    build_position_projection_diagnostics,
    projection_signature,
    resolve_locked_chip_context,
)
from src.models.xmins_v3 import estimate_xmins


CHIP_POLICY = {
    "chip_governance": {
        "wildcard_context_from_locked_authority": True,
        "auto_activate_chip": False,
    }
}


def test_gw2_wildcard_lock_cannot_leak_into_gw3_planning():
    lock = {
        "authoritative_phase": "pre_deadline_wc",
        "wildcard_active": True,
        "target_gw": 2,
    }
    context = resolve_locked_chip_context(lock, {"used": [{"event": 2, "name": "wildcard"}]}, 3, CHIP_POLICY)
    assert context["planning_gw"] == 3
    assert context["active_chip"] is None
    assert context["override_target_gw"] == 2
    assert context["override_matches_planning_gw"] is False
    assert context["stale_chip_override_suppressed"] is True
    assert context["used_this_gw"] == []


def test_same_gameweek_wildcard_lock_remains_active():
    lock = {
        "authoritative_phase": "pre_deadline_wc",
        "wildcard_active": True,
        "target_gw": 2,
    }
    context = resolve_locked_chip_context(lock, {"used": []}, 2, CHIP_POLICY)
    assert context["active_chip"] == "wildcard"
    assert context["override_matches_planning_gw"] is True
    assert context["stale_chip_override_suppressed"] is False


def test_legacy_untargeted_same_phase_lock_remains_backward_compatible():
    lock = {"authoritative_phase": "pre_deadline_wc", "wildcard_active": True}
    context = resolve_locked_chip_context(lock, {"used": []}, 2, CHIP_POLICY)
    assert context["active_chip"] == "wildcard"
    assert context["override_target_gw"] is None
    assert context["governance"]["legacy_untargeted_lock_behavior_preserved"] is True


def _player(*, starts: int = 3, minutes: int = 250, chance: int | None = 100) -> dict:
    return {
        "starts": starts,
        "minutes": minutes,
        "status": "a",
        "chance_of_playing_next_round": chance,
    }


def test_xmins_explicit_probability_contract_for_starter_profile():
    out = estimate_xmins(
        _player(),
        {
            "team_matches_played": 3,
            "prior_start_probability": 0.90,
            "prior_evidence_minutes": 2200,
            "starter_minutes_prior": 82,
        },
    )
    assert out["probability_sum"] == pytest.approx(1.0, abs=0.001)
    assert out["expected_minutes_if_start"] == out["starter_minutes_if_start"]
    assert out["overall_availability"] == out["availability"]
    derived = (
        out["start_probability"] * out["starter_minutes_if_start"]
        + out["bench_probability"] * out["bench_minutes_if_used"]
    )
    assert out["expected_minutes"] == pytest.approx(derived, abs=0.2)
    assert out["governance"]["expected_minutes_derived_from_explicit_probabilities"] is True


def test_xmins_rotation_risk_reduces_start_probability_and_minutes():
    base_context = {
        "team_matches_played": 3,
        "prior_start_probability": 0.86,
        "prior_evidence_minutes": 1600,
        "starter_minutes_prior": 80,
    }
    secure = estimate_xmins(_player(), base_context)
    rotated = estimate_xmins(_player(), {**base_context, "rotation_risk": 0.85})
    assert rotated["start_probability"] < secure["start_probability"]
    assert rotated["expected_minutes"] < secure["expected_minutes"]
    assert rotated["bench_probability"] >= secure["bench_probability"]


def test_xmins_dnp_profile_is_explicit_when_official_availability_zero():
    out = estimate_xmins(_player(chance=0), {"team_matches_played": 3})
    assert out["overall_availability"] == 0.0
    assert out["start_probability"] == 0.0
    assert out["bench_probability"] == 0.0
    assert out["dnp_probability"] == 1.0
    assert out["expected_minutes"] == 0.0
    assert out["probability_sum"] == 1.0


def _sample_projections() -> dict:
    return {
        "players": [
            {
                "element": 1,
                "position": "DEF",
                "xpts_by_gw": [
                    {
                        "gw": 3,
                        "mean": 5.0,
                        "fixtures": [
                            {
                                "mean": 5.0,
                                "components": {
                                    "appearance": 1.8,
                                    "attack": 0.7,
                                    "clean_sheet": 1.7,
                                    "saves": 0.0,
                                    "defensive_contribution": 0.5,
                                    "bonus": 0.3,
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "element": 2,
                "position": "MID",
                "xpts_by_gw": [
                    {
                        "gw": 3,
                        "mean": 5.5,
                        "fixtures": [
                            {
                                "mean": 5.5,
                                "components": {
                                    "appearance": 1.8,
                                    "attack": 3.2,
                                    "clean_sheet": 0.0,
                                    "saves": 0.0,
                                    "defensive_contribution": 0.2,
                                    "bonus": 0.3,
                                },
                            }
                        ],
                    }
                ],
            },
        ]
    }


def test_position_projection_ablation_is_non_mutating_and_explains_defensive_share():
    projections = _sample_projections()
    before = copy.deepcopy(projections)
    diagnostics = build_position_projection_diagnostics(projections)
    assert projections == before
    assert diagnostics["mutates_xpts"] is False
    defender = diagnostics["positions"]["DEF"]
    assert defender["mean_xpts_per_fixture"] == 5.0
    assert defender["ablation_mean_xpts_per_fixture"]["without_clean_sheet"] == 3.3
    assert defender["defensive_component_share"] == pytest.approx((1.7 + 0.5 + 0.3) / 5.0, abs=0.0001)
    assert diagnostics["comparison_authority"] == "REALIZED_HISTORICAL_VALIDATION_NOT_V4"


def test_tactical_enrichment_guard_fails_if_xpts_changes():
    projections = _sample_projections()
    signature = projection_signature(projections)
    unchanged = copy.deepcopy(projections)
    unchanged["players"][0]["tactical_matchup"] = {"status": "READY"}
    assert_projection_signature_unchanged(signature, unchanged)

    mutated = copy.deepcopy(unchanged)
    mutated["players"][0]["xpts_by_gw"][0]["mean"] = 5.25
    with pytest.raises(RuntimeError, match="tactical enrichment mutated decision-bearing xPts"):
        assert_projection_signature_unchanged(signature, mutated)
