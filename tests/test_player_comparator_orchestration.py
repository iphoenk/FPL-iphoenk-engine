from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import (
    build_transfer_economics,
    derive_dynamic_ft_shadow_value,
)
from src.engines.v12_player_comparator import (
    ComparatorContractError,
    compare_player_to_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "engines" / "v12_player_comparator.py"


def _minutes(*, p_start=0.86, p_dnp=0.08, xmins=72.0, p60=None):
    row = {
        "model_owner": "V12_PLAYER_MINUTES",
        "p_available": 0.96,
        "p_start": p_start,
        "p_dnp": p_dnp,
        "xmins": xmins,
        "provenance": "p1.1-synthetic",
    }
    if p60 is not None:
        row.update(
            {
                "p_60_plus_supported": True,
                "p_60_plus": p60,
                "p_60_plus_provenance": "p1.1-existing-minute-distribution",
            }
        )
    return row


def _events(xpts, *, p_return=0.35, p_blank=0.42):
    return {
        "model_owner": "V12_PLAYER_EVENTS",
        "xpts": xpts,
        "p_return": p_return,
        "p_blank": p_blank,
        "point_distribution": {"mean": xpts, "source": "P1.3"},
        "floor": max(0.0, xpts - 2.0),
        "ceiling": xpts + 4.0,
        "uncertainty": 1.7,
        "provenance": "p1.3-synthetic",
    }


def _tactical(*, evidence_class="OBSERVED_ROLE", role="advanced-8"):
    return {
        "model_owner": "V12_TACTICAL_ROLE",
        "evidence_class": evidence_class,
        "role_summary": role,
        "route_to_points": ["GOAL", "ASSIST", "BONUS"],
        "coach": "current-coach",
        "base_formation": "4-2-3-1",
        "formation_variants": ["4-3-3"],
        "build_up": "current-season-observed",
        "pressing": "current-season-observed",
        "defensive_line": "current-season-observed",
        "width": "current-season-observed",
        "transition": "current-season-observed",
        "opponent_strengths": ["central compactness"],
        "opponent_vulnerabilities": ["wide half-space"],
        "relevant_channel": "right half-space",
        "set_piece_aerial_context": "secondary",
        "set_piece_penalty_role": "secondary set pieces",
        "provenance": "p1.6-synthetic",
    }


def _fixture(gw, opponent, xpts, *, p60=None, tactical=None):
    return {
        "gw": gw,
        "opponent": opponent,
        "home_away": "H" if gw % 2 else "A",
        "venue": f"Venue {gw}",
        "minutes": _minutes(p60=p60),
        "events": _events(xpts),
        "tactical": tactical or _tactical(),
        "rest_congestion": {"days_rest": 5},
        "midweek_competition_context": [],
        "fixture_confidence": "HIGH",
        "data_quality": "COMPLETE",
        "provenance": "official-fixture",
    }


def _player(element, name, *, position="MID", club_id=1, xpts_offset=0.0, p60=None):
    return {
        "element_id": element,
        "name": name,
        "position": position,
        "club_id": club_id,
        "price": 7.5,
        "sell_value": 7.3,
        "fixtures": [
            _fixture(6, "A", 4.2 + xpts_offset, p60=p60),
            _fixture(7, "B", 4.5 + xpts_offset, p60=p60),
            _fixture(8, "C", 4.7 + xpts_offset, p60=p60),
            _fixture(9, "D", 4.3 + xpts_offset, p60=p60),
            _fixture(10, "E", 4.8 + xpts_offset, p60=p60),
        ],
        "football_components": {
            "PROVEN_HISTORICAL": 70,
            "TACTICAL_ROLE": 72,
            "CURRENT_UNDERLYING": 74,
            "FIXTURE_SECURITY": 71,
        },
        "role_sustainability": "CURRENT_COACH_CURRENT_SEASON",
        "horizon_distributions": {
            "1GW": {"floor": 2.0, "ceiling": 9.0, "uncertainty": 1.7, "confidence": "HIGH"},
            "2GW": {"floor": 4.1, "ceiling": 17.0, "uncertainty": 2.4, "confidence": "HIGH"},
            "3GW": {"floor": 6.0, "ceiling": 24.0, "uncertainty": 3.0, "confidence": "HIGH"},
            "5GW": {"floor": 10.2, "ceiling": 38.0, "uncertainty": 4.2, "confidence": "MEDIUM"},
        },
        "competition_schedule": [
            {
                "competition": "UEFA Champions League",
                "date": "2026-09-23",
                "opponent": "Confirmed European Opponent",
                "status": "CONFIRMED",
                "location": "away",
                "travel_context": "international travel",
                "days_rest": 3,
                "provenance": "official-competition",
            },
            {
                "competition": "EFL Cup",
                "date": "2026-09-29",
                "opponent": "TBD",
                "status": "TBD",
                "provenance": "official-draw-pending",
            },
            {
                "competition": "International",
                "date": "2026-10-08",
                "opponent": "National Team Opponent",
                "status": "CONFIRMED",
                "location": "away",
                "travel_context": "verified international duty",
                "actual_minutes": None,
                "provenance": "official-international",
            },
        ],
        "provenance": "existing-v12-outputs",
    }


def _economics(*, hit=0, itb=0.5):
    shadow = derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=11.8,
        best_future_utility_with_ft_consumed=10.7,
        frontier_snapshot_id="comparator-test-frontier",
    )
    return build_transfer_economics(
        ft_used=1,
        hit_points=hit,
        ft_shadow=shadow,
        buy_back_cost=0.1,
        sell_value_loss=0.0,
        price_movement_effect=0.0,
        affordability_after=True,
        itb_after=itb,
        concentration_risk="LOW",
        correlation_risk="LOW",
        exit_route={},
        reacquisition_plan={},
    )


def _context(element=202, **overrides):
    row = {
        "transfer_economics": _economics(),
        "affordability": {"status": "PASS", "bank_after": 0.5},
        "structural_impact": {"formation_options_preserved": True},
        "robustness": {"status": "PASS", "classification": "MEAN-EDGE-DOMINATED"},
        "expected_regret": 0.4,
        "information_value_of_waiting": 0.25,
        "mini_league_overlay": {"applied_after_football_optimal_baseline": True},
        "gate0": {"status": "PASS"},
        "football_label": "CHALLENGER",
        "operational_action": "WAIT",
        "decision_reasons": ["existing V12 horizon edge"],
        "decision_risks": ["lineup uncertainty"],
        "reversal_triggers": ["material P(start) change"],
    }
    row.update(overrides)
    return {element: row}


def _compare(*, owned=None, challenger=None, context=None, active_chip=None):
    owned = owned or _player(101, "Owned Generic")
    challenger = challenger or _player(202, "Candidate Generic", club_id=2, xpts_offset=0.8)
    return compare_player_to_candidates(
        player_out=owned,
        challengers=[challenger],
        comparison_timestamp="2026-09-20T12:50:00+07:00",
        planning_gw=6,
        candidate_context=context or _context(challenger["element_id"]),
        active_chip=active_chip,
    )


def test_comparator_supports_arbitrary_ids_and_has_no_named_player_hardcode():
    result = _compare(
        owned=_player(911, "Alpha"),
        challenger=_player(1777, "Beta", club_id=7, xpts_offset=0.3),
        context=_context(1777),
    )
    assert result["player_out"]["element_id"] == 911
    assert result["comparisons"][0]["player_in"]["element_id"] == 1777
    source = MODULE.read_text(encoding="utf-8")
    assert "Rogers" not in source
    assert "Cherki" not in source
    assert "Sangaré" not in source
    assert "Groß" not in source


def test_comparator_requires_existing_p1_1_owner_instead_of_recalculating_minutes():
    owned = _player(101, "Owned")
    owned["fixtures"][0]["minutes"]["model_owner"] = "SECOND_XMINS_MODEL"
    with pytest.raises(ComparatorContractError, match="V12_PLAYER_MINUTES"):
        _compare(owned=owned)


def test_comparator_requires_existing_p1_3_owner_instead_of_recalculating_xpts():
    candidate = _player(202, "Candidate", club_id=2)
    candidate["fixtures"][0]["events"]["model_owner"] = "SECOND_XPTS_MODEL"
    with pytest.raises(ComparatorContractError, match="V12_PLAYER_EVENTS"):
        _compare(challenger=candidate)


def test_comparator_requires_existing_p1_6_owner_and_creates_no_second_tactical_score():
    candidate = _player(202, "Candidate", club_id=2)
    candidate["fixtures"][0]["tactical"]["model_owner"] = "SECOND_TACTICAL_SCORER"
    with pytest.raises(ComparatorContractError, match="V12_TACTICAL_ROLE"):
        _compare(challenger=candidate)


def test_comparator_is_diagnostic_not_ranking_or_decision_authority():
    result = _compare()
    battle = result["comparisons"][0]
    assert result["decision_authority"] is False
    assert result["ranking_authority"] is False
    assert battle["decision_authority"] is False
    assert battle["ranking_authority"] is False
    assert battle["diagnostic_evidence_only"] is True
    assert battle["hidden_weighted_horizon_aggregate"] is False


def test_p60_is_carried_only_when_existing_p1_1_explicitly_supports_it():
    supported = _compare(
        owned=_player(101, "Owned", p60=0.71),
        challenger=_player(202, "Candidate", club_id=2, xpts_offset=0.5, p60=0.82),
    )
    row = supported["comparisons"][0]["fixture_by_fixture"][0]
    assert row["player_out"][0]["p_60_plus"]["value"] == 0.71
    assert row["player_in"][0]["p_60_plus"]["value"] == 0.82

    unavailable = _compare()
    row2 = unavailable["comparisons"][0]["fixture_by_fixture"][0]
    assert row2["player_out"][0]["p_60_plus"]["value"] == "UNAVAILABLE"
    assert "P1.1" in row2["player_out"][0]["p_60_plus"]["reason"]


def test_p60_has_no_gaussian_fallback_or_new_probability_math():
    source = MODULE.read_text(encoding="utf-8").lower()
    assert "gaussian" not in source
    assert "normal distribution" not in source
    assert "erf(" not in source


def test_comparator_exposes_separate_1_2_3_5gw_and_expected_starts_not_cumulative_probability():
    battle = _compare()["comparisons"][0]
    for key in ("horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw"):
        assert key in battle
        assert "expected_starts_over_horizon" in battle[key]["out"]
        assert battle[key]["out"]["cumulative_start_probability"] is None
    assert battle["raw_gain_2gw"] == pytest.approx(1.6)
    assert battle["raw_gain_5gw"] == pytest.approx(4.0)


def test_fixture_surface_covers_next_five_pl_gws():
    rows = _compare()["comparisons"][0]["fixture_by_fixture"]
    assert [row["gw"] for row in rows] == [6, 7, 8, 9, 10]
    assert all("player_out" in row and "player_in" in row for row in rows)


def test_competition_context_preserves_confirmed_europe_international_and_tbd_cup():
    battle = _compare()["comparisons"][0]
    schedule = battle["competition_schedule"]["out"]
    assert any(row["competition"] == "UEFA Champions League" and row["status"] == "CONFIRMED" for row in schedule)
    assert any(row["competition"] == "International" and row["status"] == "CONFIRMED" for row in schedule)
    cup = next(row for row in schedule if row["competition"] == "EFL Cup")
    assert cup["status"] == "TBD"
    assert cup["opponent"] == "TBD"
    assert battle["competition_schedule"]["direct_xpts_penalty_applied"] is False


def test_tbd_fixture_cannot_invent_future_opponent():
    candidate = _player(202, "Candidate", club_id=2)
    candidate["competition_schedule"][1]["opponent"] = "Invented Team"
    with pytest.raises(ComparatorContractError, match="TBD"):
        _compare(challenger=candidate)


def test_missing_tactical_detail_remains_unavailable_not_fabricated():
    candidate = _player(202, "Candidate", club_id=2)
    candidate["fixtures"][0]["tactical"].pop("pressing")
    result = _compare(challenger=candidate)
    row = result["comparisons"][0]["fixture_by_fixture"][0]["player_in"][0]
    assert row["pressing"] == "UNAVAILABLE"


def test_transfer_economics_reuses_existing_canonical_output():
    battle = _compare()["comparisons"][0]
    assert battle["transfer_economics"]["decision_chain_stage"] == "TRANSFER_ECONOMICS"
    assert battle["transfer_economics"]["included_in_football_score"] is False


def test_same_price_upgrade_and_downgrade_are_context_not_new_finance_model():
    same = _compare()["comparisons"][0]
    assert same["affordability"]["status"] == "PASS"

    up = _compare(context=_context(202, affordability={"status": "PASS", "bank_after": 0.0}))
    assert up["comparisons"][0]["affordability"]["bank_after"] == 0.0

    down = _compare(context=_context(202, affordability={"status": "PASS", "bank_after": 1.3}))
    assert down["comparisons"][0]["affordability"]["bank_after"] == 1.3


def test_gate0_club_limit_failure_cannot_be_act():
    with pytest.raises(ComparatorContractError, match="Gate0-failing"):
        _compare(
            context=_context(
                202,
                gate0={"status": "FAIL", "reason": "MAX_3_CLUB"},
                operational_action="ACT",
            )
        )


def test_unknown_sell_value_is_never_guessed():
    owned = _player(101, "Owned")
    owned["sell_value"] = None
    result = _compare(
        owned=owned,
        context=_context(202, affordability={"status": "UNAVAILABLE", "reason": "sell value unknown"}),
    )
    battle = result["comparisons"][0]
    assert battle["player_out"]["sell_value"] is None
    assert battle["affordability"]["status"] == "UNAVAILABLE"


def test_active_wildcard_rejects_irrelevant_hit_cost():
    with pytest.raises(ComparatorContractError, match="Wildcard"):
        _compare(
            context=_context(202, transfer_economics=_economics(hit=4)),
            active_chip="WILDCARD",
        )


def test_wait_prepare_act_is_exact_operational_enum():
    for action in ("WAIT", "PREPARE", "ACT"):
        result = _compare(context=_context(202, operational_action=action))
        assert result["comparisons"][0]["operational_action"] == action
    with pytest.raises(ComparatorContractError):
        _compare(context=_context(202, operational_action="LEAN_TRANSFER"))


def test_mini_league_overlay_must_be_after_football_baseline():
    with pytest.raises(ComparatorContractError, match="downstream"):
        _compare(
            context=_context(
                202,
                mini_league_overlay={"applied_after_football_optimal_baseline": False},
            )
        )


def test_comparator_preserves_canonical_weights_without_defining_new_ones():
    source = MODULE.read_text(encoding="utf-8")
    assert "0.20" not in source
    assert "0.25" not in source
    assert "0.30" not in source
    assert "CANONICAL_WEIGHTS =" not in source


def _native_minutes_fixture(*, p_start=0.81, p_dnp=0.09, xmins=68.4):
    return {
        "model_owner": "V12_PLAYER_MINUTES",
        "conditional_probabilities": {
            "p_available": 0.94,
            "p_start_given_available": 0.8617,
        },
        "start_probability": p_start,
        "cameo_probability": 0.10,
        "late_cameo_probability": 0.03,
        "dnp_probability": p_dnp,
        "derived_probabilities": {
            "p_start": p_start,
            "p_cameo": 0.10,
            "p_late_cameo": 0.03,
            "p_dnp": p_dnp,
        },
        "expected_minutes": 67.0,
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "mean": xmins,
            "std": 18.2,
            "states": [
                {"state": "START", "probability": p_start, "minutes_mean": 78.0, "minutes_std": 9.0},
                {"state": "CAMEO", "probability": 0.07, "minutes_mean": 22.0, "minutes_std": 7.0},
                {"state": "LATE_CAMEO", "probability": 0.03, "minutes_mean": 8.0, "minutes_std": 4.0},
                {"state": "ZERO_MINUTES", "probability": p_dnp, "minutes_mean": 0.0, "minutes_std": 0.0},
            ],
        },
        "evidence_lineage": {"source": "native-p1.1-test-shape"},
    }


def _native_events_fixture(xpts=5.25):
    point_distribution = {
        "status": "READY_PARTIAL_BONUS_RESIDUAL",
        "model": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
        "probabilities": {"0": 0.20, "2": 0.25, "5": 0.30, "10": 0.25},
        "expected_points": xpts,
        "variance": 7.84,
        "std": 2.8,
        "quantiles": {"P10": 0, "P50": 5, "P90": 10},
        "p_fpl_blank": 0.45,
        "tails": {"ge_10": 0.25},
        "provenance": {"owner": "P1.3B"},
    }
    return {
        "model_owner": "V12_PLAYER_EVENTS",
        "event_probabilities": {"p_attacking_return": 0.39},
        "minutes_threshold_probabilities": {
            "p_60_plus": 0.77,
            "threshold_minutes": 60,
            "source": "P1.1_FINITE_STATE_PLUS_P1.3_GOVERNED_BOUNDED_QUADRATURE",
            "new_minutes_model_created": False,
        },
        "point_distribution": point_distribution,
        "aggregate": {
            "expected_fpl_points": xpts,
            "points_variance": 7.84,
            "points_std": 2.8,
            "canonical_gaussian": False,
            "quantiles": dict(point_distribution["quantiles"]),
            "p_fpl_blank": 0.45,
            "tails": {"ge_10": 0.25},
        },
        "mean": xpts,
        "std": 2.8,
    }


def _native_tactical_fixture(score=72.5):
    return {
        "model_owner": "V12_TACTICAL_ROLE",
        "canonical_tactical_role_score": score,
        "scoring_channel_vector": {"GOAL": 0.7, "ASSIST": 0.6, "SET_PIECE": 0.2},
        "scoring_channel_diversity": 0.68,
        "tactical_role_fit": 0.74,
        "role_resilience": 0.79,
        "fixture_suppression_raw": 0.22,
        "fixture_suppression_effective": 0.14,
        "feature_evidence": {
            "tactical_role_fit": {"evidence_state": "OBSERVED"},
        },
        "score_decomposition": {"FINAL_TACTICAL_ROLE_SCORE": score},
    }


def _native_profile_fixture():
    return {
        "evidence_class": "OBSERVED_ROLE",
        "role_summary": "advanced-8 / right half-space",
        "route_to_points": ["GOAL", "ASSIST", "BONUS"],
        "coach": "verified-current-coach",
        "base_formation": "4-3-3",
        "pressing": "verified-profile-context",
        "opponent_vulnerabilities": ["right half-space"],
        "provenance": "verified-tactical-profile",
    }


def _native_player(element, name, *, club_id, xpts_offset=0.0):
    player = _player(element, name, club_id=club_id, xpts_offset=xpts_offset)
    for index, fixture in enumerate(player["fixtures"]):
        fixture["minutes"] = _native_minutes_fixture(
            p_start=0.81 - index * 0.01,
            p_dnp=0.09 + index * 0.005,
            xmins=68.4 - index,
        )
        fixture["events"] = _native_events_fixture(
            xpts=5.25 + xpts_offset + index * 0.1
        )
        fixture["tactical"] = _native_tactical_fixture(score=72.5 - index)
        fixture["tactical_profile"] = _native_profile_fixture()
    return player


def test_native_p11_shape_maps_without_flattened_aliases():
    owned = _native_player(301, "Native Owned", club_id=1)
    challenger = _native_player(302, "Native Challenger", club_id=2, xpts_offset=0.4)
    result = _compare(owned=owned, challenger=challenger, context=_context(302))
    row = result["comparisons"][0]["fixture_by_fixture"][0]["player_out"][0]
    assert row["owner_schema_binding"]["minutes"] == "NATIVE_P1_1"
    assert row["p_available"] == pytest.approx(0.94)
    assert row["p_start"] == pytest.approx(0.81)
    assert row["p_dnp"] == pytest.approx(0.09)
    assert row["p_cameo"] == pytest.approx(0.10)
    assert row["p_late_cameo"] == pytest.approx(0.03)
    assert row["xmins"] == pytest.approx(68.4)
    assert row["p_60_plus"]["value"] == pytest.approx(0.77)
    assert row["p_60_plus"]["provenance"] == (
        "P1.1_FINITE_STATE_PLUS_P1.3_GOVERNED_BOUNDED_QUADRATURE"
    )


def test_native_p13_shape_maps_distribution_quantiles_and_uncertainty():
    owned = _native_player(311, "Native Owned", club_id=1)
    challenger = _native_player(312, "Native Challenger", club_id=2, xpts_offset=0.4)
    result = _compare(owned=owned, challenger=challenger, context=_context(312))
    row = result["comparisons"][0]["fixture_by_fixture"][0]["player_out"][0]
    assert row["owner_schema_binding"]["events"] == "NATIVE_P1_3"
    assert row["xpts"] == pytest.approx(5.25)
    assert row["p_return"] == pytest.approx(0.39)
    assert row["p_blank"] == pytest.approx(0.45)
    assert row["point_distribution"]["model"] == "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1"
    assert row["floor"] == {
        "value": 0.0,
        "quantile": "P10",
        "source": "P1.3B_NATIVE_POINT_DISTRIBUTION",
    }
    assert row["ceiling"] == {
        "value": 10.0,
        "quantile": "P90",
        "source": "P1.3B_NATIVE_POINT_DISTRIBUTION",
    }
    assert row["uncertainty"] == pytest.approx(2.8)


def test_native_p16_output_is_preserved_and_profile_is_separate():
    owned = _native_player(321, "Native Owned", club_id=1)
    challenger = _native_player(322, "Native Challenger", club_id=2, xpts_offset=0.4)
    result = _compare(owned=owned, challenger=challenger, context=_context(322))
    row = result["comparisons"][0]["fixture_by_fixture"][0]["player_out"][0]
    assert row["owner_schema_binding"]["tactical"] == "NATIVE_P1_6"
    assert row["canonical_tactical_role_score"] == pytest.approx(72.5)
    assert row["p1_6_model_output"]["scoring_channel_diversity"] == pytest.approx(0.68)
    assert row["p1_6_model_output"]["tactical_role_fit"] == pytest.approx(0.74)
    assert row["tactical_profile_context"]["coach"] == "verified-current-coach"
    assert row["tactical_evidence_class"] == "OBSERVED_ROLE"
    assert row["role_summary"] == "advanced-8 / right half-space"
    assert "coach" not in row["p1_6_model_output"]
    assert result["comparisons"][0]["duplicate_tactical_scorer"] is False


def test_native_p16_without_profile_does_not_fabricate_observed_role():
    owned = _native_player(331, "Native Owned", club_id=1)
    challenger = _native_player(332, "Native Challenger", club_id=2, xpts_offset=0.4)
    for fixture in owned["fixtures"]:
        fixture.pop("tactical_profile", None)
    result = _compare(owned=owned, challenger=challenger, context=_context(332))
    row = result["comparisons"][0]["fixture_by_fixture"][0]["player_out"][0]
    assert row["tactical_evidence_class"] == "UNKNOWN"
    assert row["role_summary"] == "UNAVAILABLE"
    assert row["canonical_tactical_role_score"] is not None


def test_generic_native_schema_comparator_acceptance():
    owned = _native_player(341, "Owned Generic Native", club_id=1)
    challenger = _native_player(
        342, "Challenger Generic Native", club_id=2, xpts_offset=0.55
    )
    result = _compare(owned=owned, challenger=challenger, context=_context(342))
    battle = result["comparisons"][0]
    assert battle["player_out"]["element_id"] == 341
    assert battle["player_in"]["element_id"] == 342
    assert battle["planning_gw"] == 6
    assert len(battle["fixture_by_fixture"]) == 5
    assert battle["raw_gain_1gw"] > 0
    assert battle["raw_gain_2gw"] > 0
    assert battle["raw_gain_3gw"] > 0
    assert battle["raw_gain_5gw"] > 0
    assert battle["affordability"]["status"] == "PASS"
    assert battle["structural_impact"]["formation_options_preserved"] is True
    assert battle["robustness"]["status"] == "PASS"
    assert battle["expected_regret"] == pytest.approx(0.4)
    assert battle["information_value_of_waiting"] == pytest.approx(0.25)
    assert battle["operational_action"] == "WAIT"
    assert battle["reversal_triggers"] == ["material P(start) change"]
    assert battle["duplicate_xpts_model"] is False
    assert battle["duplicate_xmins_model"] is False
    assert battle["duplicate_tactical_scorer"] is False
