from __future__ import annotations

import pytest

from src.engines.canonical_decision_methodology import (
    FOOTBALL_COMPONENTS,
    SPEC_AUTHORITY,
    MethodologyContractError,
    build_horizon_analysis,
    build_scenario_evaluation,
    build_transfer_economics,
    compute_football_score,
    merge_active_and_optimizer_scenarios,
    propagate_availability,
    validate_methodology_weights,
)


def _synthetic_weights():
    # Test-only neutral weights. Production numerical weights are owned only by Spec V11.
    unit = 1.0 / len(FOOTBALL_COMPONENTS)
    return {key: unit for key in FOOTBALL_COMPONENTS}


def _football(**overrides):
    scores = {
        "PROVEN_HISTORICAL": 70.0,
        "TACTICAL_ROLE": 70.0,
        "CURRENT_UNDERLYING": 70.0,
        "FIXTURE_SECURITY": 70.0,
    }
    scores.update(overrides)
    return compute_football_score(scores, weights=_synthetic_weights())


def _availability(*, p_start=0.75, p_cameo=0.15, p_dnp=0.10, xmins=68.0, unknown=False):
    return propagate_availability(
        p_start=p_start,
        p_cameo=p_cameo,
        p_dnp=p_dnp,
        xmins=xmins,
        evidence_class="MODEL_WITH_OFFICIAL_NEWS",
        unknown_injury_duration=unknown,
    )


def _horizons(one=2.0, three=5.0, five=7.0):
    return build_horizon_analysis(
        one_gw={"expected_points_delta": one, "label": "ONE-GW"},
        three_gw={"expected_points_delta": three, "label": "3GW"},
        five_gw={"expected_points_delta": five, "label": "5GW"},
    )


def _economics(*, buy_back=0.0, sell_loss=0.0, exit_route=None):
    return build_transfer_economics(
        ft_used=1,
        hit_points=0,
        future_ft_shadow_value=1.2,
        buy_back_cost=buy_back,
        sell_value_loss=sell_loss,
        price_movement_effect=0.0,
        affordability_after=True,
        itb_after=0.4,
        concentration_risk="LOW",
        correlation_risk="LOW",
        exit_route=exit_route or {"gw_plus_1": "HOLD"},
        reacquisition_plan={"allowed": True},
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
        horizons=horizons or _horizons(),
        availability=availability or _availability(),
        transfer_economics=economics or _economics(),
        action_state="PREPARE",
        downside="fixture or minutes downside",
        reversal_trigger="new authoritative team news",
        optimizer_selected=optimizer_selected,
        route_type=route_type,
    )


def test_01_methodology_weights_must_be_hydrated_from_spec_authority():
    weights = _synthetic_weights()
    assert validate_methodology_weights(weights, authority=SPEC_AUTHORITY) == weights
    with pytest.raises(MethodologyContractError):
        validate_methodology_weights(weights, authority="/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt")


def test_02_stable_premium_history_matters_but_does_not_dominate_current_evidence():
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


def test_03_one_gw_punt_is_distinct_from_3gw_and_5gw_and_requires_exit():
    horizons = _horizons(one=4.5, three=0.8, five=-1.1)
    economics = _economics(exit_route={"gw_plus_1": "SELL_PUNT", "destination": "REACQUIRE_OR_ALTERNATIVE"})
    punt = _scenario(
        "one-gw-punt",
        horizons=horizons,
        economics=economics,
        route_type="ONE_GW_PUNT",
    )
    assert punt["horizons"]["collapsed"] is False
    assert punt["horizons"]["horizons"]["ONE_GW"]["expected_points_delta"] == 4.5
    assert punt["horizons"]["horizons"]["5GW"]["expected_points_delta"] == -1.1
    assert punt["transfer_economics"]["exit_route"]["gw_plus_1"] == "SELL_PUNT"


def test_04_injury_uncertainty_reduces_availability_without_false_long_term_sell():
    availability = _availability(
        p_start=0.40,
        p_cameo=0.25,
        p_dnp=0.35,
        xmins=42.0,
        unknown=True,
    )
    assert availability["p_available"] == 0.65
    assert availability["uncertainty_penalty_required"] is True
    assert availability["automatic_sell"] is False
    assert "XI_BENCH" in availability["propagates_to"]
    assert "PACKAGE_UTILITY" in availability["propagates_to"]


def test_05_bruno_style_route_keeps_buyback_and_sell_value_economics_downstream():
    football = _football(PROVEN_HISTORICAL=88, TACTICAL_ROLE=82)
    economics = _economics(buy_back=0.3, sell_loss=0.2)
    scenario = _scenario("bruno-style-route", football=football, economics=economics)
    assert scenario["football_score"]["transfer_economics_included"] is False
    assert scenario["transfer_economics"]["buy_back_cost"] == 0.3
    assert scenario["transfer_economics"]["sell_value_loss"] == 0.2
    assert scenario["mentioned_by_user_is_not_recommendation"] is True


def test_06_joao_pedro_style_route_depends_on_availability_and_economics_not_rumor_sell():
    availability = _availability(
        p_start=0.55,
        p_cameo=0.25,
        p_dnp=0.20,
        xmins=51.0,
        unknown=True,
    )
    scenario = _scenario(
        "joao-pedro-style-route",
        availability=availability,
        economics=_economics(buy_back=0.1),
    )
    assert scenario["availability"]["automatic_sell"] is False
    assert scenario["availability"]["unknown_injury_duration"] is True
    assert scenario["transfer_economics"]["included_in_football_score"] is False


def test_07_sangare_style_active_route_remains_visible_when_optimizer_does_not_select_it():
    scenario = _scenario("sangare-style-route", optimizer_selected=False)
    assert scenario["active"] is True
    assert scenario["optimizer_selected"] is False
    assert scenario["visible_even_if_optimizer_not_selected"] is True


def test_08_optimizer_can_add_better_universe_alternative_without_removing_user_route():
    active = _scenario("sangare-style-route", optimizer_selected=False)
    alternative = _scenario("full-universe-alternative", optimizer_selected=True)
    merged = merge_active_and_optimizer_scenarios(
        active_user_scenarios=[active],
        optimizer_alternatives=[alternative],
    )
    ids = {row["scenario_id"] for row in merged["scenarios"]}
    assert ids == {"sangare-style-route", "full-universe-alternative"}
    assert merged["active_user_routes_preserved"] is True
    assert merged["full_universe_alternatives_preserved"] is True
    assert merged["user_mention_forces_recommendation"] is False


def test_09_package_decision_chain_keeps_football_before_transfer_economics():
    scenario = _scenario("package-route")
    assert scenario["football_score"]["decision_chain_stage"] == "FOOTBALL_SCORE"
    assert scenario["transfer_economics"]["decision_chain_stage"] == "TRANSFER_ECONOMICS"
    assert scenario["transfer_economics"]["included_in_football_score"] is False


def test_10_invalid_probability_mix_is_rejected_instead_of_fabricated():
    with pytest.raises(MethodologyContractError):
        propagate_availability(
            p_start=0.7,
            p_cameo=0.3,
            p_dnp=0.2,
            xmins=65,
            evidence_class="RUMOR",
            unknown_injury_duration=True,
        )
