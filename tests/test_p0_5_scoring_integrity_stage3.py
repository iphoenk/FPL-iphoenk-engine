from __future__ import annotations

import pytest

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    MethodologyContractError,
    build_horizon_analysis,
    build_probability_state,
    build_scenario_evaluation,
    build_transfer_economics,
    compute_football_score,
    derive_dynamic_ft_shadow_value,
    merge_active_and_optimizer_scenarios,
    propagate_availability,
    validate_methodology_weights,
)


def _football(**overrides):
    scores = {
        "PROVEN_HISTORICAL": 70.0,
        "TACTICAL_ROLE": 70.0,
        "CURRENT_UNDERLYING": 70.0,
        "FIXTURE_SECURITY": 70.0,
    }
    scores.update(overrides)
    return compute_football_score(scores)


def _probability_state():
    return build_probability_state(
        p_available=0.90,
        p_start_given_available=0.75,
        p_bench_given_available_not_start=0.80,
        p_cameo_given_bench=0.70,
        p_late_cameo_given_cameo=0.35,
    )


def _availability(*, unknown=False):
    state = _probability_state()
    u = state["unconditional"]
    regular = u["p_cameo"] - u["p_late_cameo"]
    distribution = {
        "distribution": "FINITE_STATE_MINUTES_MIXTURE",
        "mean": 58.0,
        "std": 22.0,
        "states": [
            {"state": "START", "probability": u["p_start"], "minutes_mean": 75.0, "minutes_std": 10.0},
            {"state": "CAMEO", "probability": regular, "minutes_mean": 18.0, "minutes_std": 7.0},
            {"state": "LATE_CAMEO", "probability": u["p_late_cameo"], "minutes_mean": 8.0, "minutes_std": 4.0},
            {"state": "ZERO_MINUTES", "probability": u["p_dnp"], "minutes_mean": 0.0, "minutes_std": 0.0},
        ],
    }
    return propagate_availability(
        probability_state=state,
        xmins_distribution=distribution,
        evidence_class="MODEL_WITH_OFFICIAL_NEWS",
        unknown_injury_duration=unknown,
    )


def _horizons(*, punt=False):
    return build_horizon_analysis(
        one_gw={"expected_points_delta": 2.0, "label": "GW+1"},
        two_gw={"expected_points_delta": 2.8, "label": "2GW"} if punt else None,
        three_gw={"expected_points_delta": 5.0, "label": "3GW"},
        five_gw={"expected_points_delta": 7.0, "label": "5GW"},
        rental_or_exit=punt,
    )


def _economics(*, buy_back=0.0, sell_loss=0.0, exit_route=None):
    shadow = derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=8.2,
        best_future_utility_with_ft_consumed=7.0,
        frontier_snapshot_id="future-frontier",
    )
    return build_transfer_economics(
        ft_used=1,
        hit_points=0,
        ft_shadow=shadow,
        buy_back_cost=buy_back,
        sell_value_loss=sell_loss,
        price_movement_effect=0.0,
        affordability_after=True,
        itb_after=0.4,
        concentration_risk="LOW",
        correlation_risk="LOW",
        exit_route=exit_route or {},
        reacquisition_plan={"allowed": True},
        exit_security="PUNT EXIT SECURE",
    )


def _scenario(
    scenario_id,
    *,
    football=None,
    horizons=None,
    availability=None,
    economics=None,
    optimizer_selected=False,
    route_type="NORMAL",
):
    return build_scenario_evaluation(
        scenario_id=scenario_id,
        scenario_state="CONTEMPLATED",
        route={"out": "OUT", "in": "IN"},
        football_score=football or _football(),
        horizons=horizons or _horizons(punt=route_type == "ONE_GW_PUNT"),
        availability=availability or _availability(),
        transfer_economics=economics or _economics(),
        action_state="PREPARE",
        downside="fixture or minutes downside",
        reversal_trigger="new authoritative team news",
        optimizer_selected=optimizer_selected,
        route_type=route_type,
    )


def test_01_methodology_weights_are_exact_v12_and_legacy_library_is_rejected():
    assert validate_methodology_weights(
        CANONICAL_WEIGHTS, authority=CANONICAL_AUTHORITY
    ) == CANONICAL_WEIGHTS
    for legacy in (
        "/FPL/FPL_MASTER_SPEC_V11.txt",
        "/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt",
        "/FPL/state/ACTIVE_DECISION_CONTEXT.json",
    ):
        with pytest.raises(MethodologyContractError):
            validate_methodology_weights(CANONICAL_WEIGHTS, authority=legacy)


def test_02_historical_prior_matters_without_overriding_current_role_underlying_fixture():
    stable = _football(
        PROVEN_HISTORICAL=95,
        TACTICAL_ROLE=62,
        CURRENT_UNDERLYING=58,
        FIXTURE_SECURITY=64,
    )
    changed_role = _football(
        PROVEN_HISTORICAL=35,
        TACTICAL_ROLE=92,
        CURRENT_UNDERLYING=91,
        FIXTURE_SECURITY=86,
    )
    assert stable["component_scores"]["PROVEN_HISTORICAL"] > changed_role["component_scores"]["PROVEN_HISTORICAL"]
    assert changed_role["football_score"] > stable["football_score"]
    assert stable["transfer_economics_included"] is False


def test_03_one_gw_punt_has_provisional_exit_and_distinct_2gw_3gw_5gw():
    horizons = _horizons(punt=True)
    punt = _scenario(
        "generic-one-gw-punt",
        horizons=horizons,
        economics=_economics(exit_route={"likely_options": ["KEEP", "SELL_BEST_FRESH", "REACQUIRE"]}),
        route_type="ONE_GW_PUNT",
    )
    assert punt["horizons"]["collapsed"] is False
    assert list(punt["horizons"]["horizons"]) == ["GW+1", "2GW", "3GW", "5GW"]
    assert punt["next_route_precommitted"] is False
    assert punt["fresh_full_universe_rescan_required_at_gw_plus_1"] is True


def test_04_uncertain_availability_never_creates_automatic_sell():
    availability = _availability(unknown=True)
    assert availability["uncertainty_penalty_required"] is True
    assert availability["automatic_sell"] is False
    assert availability["probability_semantics"] == "V12_HIERARCHICAL"
    assert "XI_BENCH" in availability["propagates_to"]
    assert "PACKAGE_UTILITY" in availability["propagates_to"]


def test_05_buyback_and_sell_value_economics_remain_downstream():
    football = _football(PROVEN_HISTORICAL=88, TACTICAL_ROLE=82)
    economics = _economics(buy_back=0.3, sell_loss=0.2)
    scenario = _scenario("generic-transfer-route", football=football, economics=economics)
    assert scenario["football_score"]["transfer_economics_included"] is False
    assert scenario["transfer_economics"]["buy_back_cost"] == 0.3
    assert scenario["transfer_economics"]["sell_value_loss"] == 0.2
    assert scenario["mentioned_by_user_is_not_recommendation"] is True


def test_06_availability_and_economics_do_not_turn_uncertain_news_into_forced_action():
    scenario = _scenario(
        "generic-availability-route",
        availability=_availability(unknown=True),
        economics=_economics(buy_back=0.1),
    )
    assert scenario["availability"]["automatic_sell"] is False
    assert scenario["availability"]["unknown_injury_duration"] is True
    assert scenario["transfer_economics"]["included_in_football_score"] is False


def test_07_active_user_route_remains_visible_when_optimizer_does_not_select_it():
    scenario = _scenario("user-active-route", optimizer_selected=False)
    assert scenario["active"] is True
    assert scenario["optimizer_selected"] is False
    assert scenario["visible_even_if_optimizer_not_selected"] is True


def test_08_optimizer_can_add_better_universe_alternative_without_removing_user_route():
    active = _scenario("user-active-route", optimizer_selected=False)
    alternative = _scenario("full-universe-alternative", optimizer_selected=True)
    merged = merge_active_and_optimizer_scenarios(
        active_user_scenarios=[active],
        optimizer_alternatives=[alternative],
    )
    ids = {row["scenario_id"] for row in merged["scenarios"]}
    assert ids == {"user-active-route", "full-universe-alternative"}
    assert merged["active_user_routes_preserved"] is True
    assert merged["full_universe_alternatives_preserved"] is True
    assert merged["user_mention_forces_recommendation"] is False


def test_09_package_chain_keeps_football_before_transfer_economics():
    scenario = _scenario("package-route")
    assert scenario["football_score"]["decision_chain_stage"] == "FOOTBALL_SCORE"
    assert scenario["transfer_economics"]["decision_chain_stage"] == "TRANSFER_ECONOMICS"
    assert scenario["transfer_economics"]["included_in_football_score"] is False


def test_10_legacy_flat_probability_can_only_be_partial_compatibility():
    availability = propagate_availability(
        p_start=0.7,
        p_cameo=0.2,
        p_dnp=0.1,
        xmins=65,
        evidence_class="LEGACY_TEST",
    )
    assert availability["status"] == "PARTIAL"
    assert availability["probability_semantics"] == "LEGACY_COMPATIBILITY"
    assert availability["p_bench"] is None
