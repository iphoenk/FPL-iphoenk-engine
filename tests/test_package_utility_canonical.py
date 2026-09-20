from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from src.engines import v12_package_search as package_search
from src.engines import v12_package_utility as utility
from src.engines.canonical_decision_methodology import CANONICAL_WEIGHTS
from src.engines.v12_model_evidence import ModelEvidenceError


GW = 6
GENERATED = "2026-09-20T00:00:00Z"


def _current() -> list[dict]:
    rows = [
        (1, "GK", 1, 45), (2, "GK", 2, 45),
        (3, "DEF", 3, 45), (4, "DEF", 4, 45), (5, "DEF", 5, 45),
        (6, "DEF", 6, 45), (7, "DEF", 7, 45),
        (8, "MID", 8, 60), (9, "MID", 9, 60), (10, "MID", 10, 60),
        (11, "MID", 11, 60), (12, "MID", 12, 60),
        (13, "FWD", 13, 70), (14, "FWD", 14, 70), (15, "FWD", 15, 70),
    ]
    return [
        {
            "element": element,
            "name": f"P{element}",
            "position": position,
            "team_id": team,
            "now_cost": price,
            "sell_cost": price - (element % 2),
            "status": "a",
        }
        for element, position, team, price in rows
    ]


def _candidates() -> list[dict]:
    rows = [
        (101, "GK", 16, 44),
        (102, "DEF", 16, 44),
        (103, "DEF", 1, 46),
        (104, "MID", 17, 58),
        (105, "MID", 2, 61),
        (106, "FWD", 18, 68),
        (107, "FWD", 3, 72),
    ]
    return [
        {
            "element": element,
            "name": f"C{element}",
            "position": position,
            "team_id": team,
            "now_cost": price,
            "status": "a",
            "eligible": True,
        }
        for element, position, team, price in rows
    ]


def _universe() -> list[dict]:
    return [
        {
            "element": row["element"],
            "name": row["name"],
            "position": row["position"],
            "team_id": row["team_id"],
            "now_cost": row["now_cost"],
            "status": "a",
        }
        for row in _current()
    ] + _candidates()


def _search() -> dict:
    return package_search.search_packages(
        current_squad=_current(),
        candidate_universe=_universe(),
        bank=5,
        max_transfers=2,
        universe_complete=True,
        expected_eligible_universe_count=len(_candidates()),
    )


def _projections() -> dict:
    rows = []
    by_id = {row["element"]: row for row in _current() + _candidates()}
    for element, meta in sorted(by_id.items()):
        rows.append(
            {
                "element": element,
                "name": meta["name"],
                "position": meta["position"],
                "team_id": meta["team_id"],
                "now_cost": meta["now_cost"],
                "xmins": {
                    "expected_minutes": 75.0,
                    "xmins_distribution": {
                        "mean": 75.0,
                        "std": 10.0,
                        "states": [
                            {"state": "START", "probability": 0.8},
                            {"state": "REGULAR_CAMEO", "probability": 0.1},
                            {"state": "LATE_CAMEO", "probability": 0.05},
                            {"state": "ZERO_MINUTES", "probability": 0.05},
                        ],
                    },
                },
                "tactical_role_component": {
                    "canonical_tactical_role_score": 60.0,
                    "canonical_component": {
                        "name": "TACTICAL_ROLE",
                        "weight": 0.25,
                        "weighted_component_points": 15.0,
                    },
                },
                "xpts_by_gw": [
                    {
                        "gw": GW + offset,
                        "mean": 4.0,
                        "std": 1.0,
                        "points_variance": 1.0,
                        "point_distribution": {
                            "model": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
                            "probabilities": {"0": 0.1, "4": 0.8, "8": 0.1},
                        },
                    }
                    for offset in range(5)
                ],
            }
        )
    return {"planning_gw": GW, "generated_at": GENERATED, "players": rows}


def _fake_lineup(
    projections,
    squad_ids,
    *,
    gw,
    generated_at,
):
    incoming = sorted(element for element in squad_ids if int(element) >= 100)
    # Deterministic genuine-distribution stand-in for unit tests. The production
    # path is separately asserted to call P1.7 optimize_lineup.
    edge = 2.0 * len(incoming)
    xi = sorted(int(value) for value in squad_ids)[:11]
    captain = incoming[-1] if incoming else xi[-1]
    vice = xi[-2] if xi[-2] != captain else xi[-3]
    return {
        "status": "READY",
        "gw": int(gw),
        "route_utility": 50.0 + edge,
        "expected_fpl_points": 50.0 + edge,
        "distributional_downside": 8.0 - 0.2 * len(incoming),
        "supportable_upside": 12.0 + 0.5 * len(incoming),
        "expected_autosub_value": 0.8 + 0.1 * len(incoming),
        "cameo_blocking_cost": 0.3,
        "formation": "3-4-3",
        "starting_xi": xi,
        "bench_gk": sorted(int(value) for value in squad_ids)[11],
        "bench_order": sorted(int(value) for value in squad_ids)[12:15],
        "captain": captain,
        "vice_captain": vice,
        "captain_safe_pool_count": 5,
        "confidence": "HIGH",
        "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
        "p1_7_model_evidence_output_fingerprint": f"fake-{gw}-{len(incoming)}",
        "governance": {
            "p1_7_consumed_read_only": True,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_7_math_mutated": False,
        },
    }


def _negative_fake_lineup(projections, squad_ids, *, gw, generated_at):
    row = _fake_lineup(
        projections, squad_ids, gw=gw, generated_at=generated_at
    )
    incoming = sum(1 for element in squad_ids if int(element) >= 100)
    row["route_utility"] = 50.0 - 2.0 * incoming
    row["expected_fpl_points"] = 50.0 - 2.0 * incoming
    return row


def _contexts(search_result: dict):
    future = {}
    info = {}
    price = {}
    for row in search_result["routes"]:
        route_id = row["route_id"]
        if route_id != "HOLD":
            future[route_id] = {
                "best_future_utility_with_ft": 1.00,
                "best_future_utility_with_ft_consumed": 0.75,
                "frontier_snapshot_id": f"frontier:{route_id}",
            }
        info[route_id] = {
            "value": 0.10,
            "pending_lineup_information": True,
            "injury_news": False,
            "price_movement": False,
            "future_ft_accrual": True,
            "fixture_information": False,
            "role_uncertainty": False,
        }
        price[route_id] = {
            "risk": "LOW",
            "football_authority": False,
        }
    return future, info, price


def _evaluate(monkeypatch, *, free_transfers=2, hit_cost=4, rentals=()):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    search_result = _search()
    future, info, price = _contexts(search_result)
    result = utility.evaluate_packages(
        search_result=search_result,
        projections=_projections(),
        free_transfers=free_transfers,
        hit_cost_per_extra_transfer=hit_cost,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        rental_route_ids=list(rentals),
        generated_at=GENERATED,
    )
    return search_result, result


def _change(rows: list[dict], count: int | None = None) -> dict:
    return next(
        row
        for row in rows
        if row["route_id"] != "HOLD"
        and (count is None or row["transfer_count"] == count)
    )


def test_01_hold_is_in_every_comparison(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["hold_route_id"] == "HOLD"
    assert sum(row["route_id"] == "HOLD" for row in result["routes"]) == 1


def test_02_every_utility_route_is_exact_p1_2a_route(monkeypatch):
    search_result, result = _evaluate(monkeypatch)
    assert {row["route_id"] for row in result["routes"]} == {
        row["route_id"] for row in search_result["routes"]
    }
    assert all(
        row["governance"]["search_route_consumed_exactly"] is True
        for row in result["routes"]
    )


def test_03_gw1_3gw_5gw_are_distinct_not_collapsed(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    assert set(row["horizons"]) == {"GW+1", "3GW", "5GW"}
    analysis = row["canonical_horizon_analysis"]
    assert analysis["collapsed"] is False
    assert list(analysis["horizons"]) == ["GW+1", "3GW", "5GW"]


def test_04_legacy_10_15_horizon_weighting_does_not_survive(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["methodology"]["legacy_10_15gw_used"] is False
    assert result["methodology"]["horizons_collapsed"] is False
    assert all(
        row["governance"]["legacy_horizon_weight_used"] is False
        for row in result["routes"]
    )


def test_05_fixed_change_penalty_0_20_is_not_used(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["methodology"]["legacy_fixed_change_penalty_used"] is False
    assert utility.load_config()["economics"]["fixed_change_penalty"] is None
    assert all(
        row["governance"]["legacy_change_penalty_0_20_used"] is False
        for row in result["routes"]
    )


def test_06_hit_cost_is_exact_when_ft_is_known(monkeypatch):
    _, result = _evaluate(monkeypatch, free_transfers=1, hit_cost=4)
    row = _change(result["routes"], count=2)
    assert row["ft_usage"]["hit_transfers"] == 1
    assert row["hit"] == 4
    assert row["hit_status"] == "RESOLVED"


def test_07_unknown_ft_is_not_guessed(monkeypatch):
    _, result = _evaluate(monkeypatch, free_transfers=None, hit_cost=4)
    row = _change(result["routes"])
    assert row["hit"] is None
    assert row["hit_status"] == "UNRESOLVED_FREE_TRANSFERS"
    assert row["transfer_economics"]["status"] == "PARTIAL"


def test_08_exact_sell_value_from_search_is_preserved(monkeypatch):
    search_result, result = _evaluate(monkeypatch)
    source = _change(search_result["routes"])
    row = next(x for x in result["routes"] if x["route_id"] == source["route_id"])
    assert row["players_out"] == source["players_out"]
    assert all(x["sell_value"] is not None for x in row["players_out"])


def test_09_bank_after_is_exact_search_economics(monkeypatch):
    search_result, result = _evaluate(monkeypatch)
    source = _change(search_result["routes"])
    row = next(x for x in result["routes"] if x["route_id"] == source["route_id"])
    assert row["bank_after"] == source["bank_after"]


def test_10_rental_publishes_2gw_but_does_not_force_exit(monkeypatch):
    search_result = _search()
    rental = _change(search_result["routes"], count=1)["route_id"]
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    future, info, price = _contexts(search_result)
    result = utility.evaluate_packages(
        search_result=search_result,
        projections=_projections(),
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        rental_route_ids=[rental],
        generated_at=GENERATED,
    )
    row = next(x for x in result["routes"] if x["route_id"] == rental)
    assert "2GW" in row["horizons"]
    assert row["rental"]["fresh_reoptimization_next_gw"] is True
    assert row["rental"]["precommitted_exit"] is False
    assert row["rental"]["automatic_exit_assumed"] is False


def test_11_production_lineup_adapter_calls_p1_7_owner():
    source = inspect.getsource(utility._lineup_decision)
    assert "optimize_lineup(" in source
    assert "v12_lineup_optimizer" in inspect.getsource(utility)


def test_12_bench_impact_is_included(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    assert row["bench_impact"]["autosub_value_delta"] is not None
    assert row["bench_impact"]["cameo_blocking_cost_delta"] is not None


def test_13_captain_and_vice_impact_are_included(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    assert row["captain_impact"]["captain"] is not None
    assert row["captain_impact"]["vice_captain"] is not None
    assert "captain_changed" in row["captain_impact"]


def test_14_robustness_comes_from_distributional_lineup_surface(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    assert row["robustness"]["mean_only"] is False
    assert row["robustness"]["lineup_distribution_consumed"] is True
    assert row["uncertainty"]["gw_plus_1_downside"] is not None
    assert row["uncertainty"]["gw_plus_1_upside"] is not None


def test_15_no_fake_p_beats_hold_or_monte_carlo(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["methodology"]["p_beats_hold"] == "NOT_COMPUTED"
    assert result["methodology"]["monte_carlo"] == "NOT_RUN"
    assert all(
        row["uncertainty"]["p_beats_hold"] == "NOT_COMPUTED"
        and row["uncertainty"]["monte_carlo"] == "NOT_RUN"
        for row in result["routes"]
    )


def test_16_price_risk_is_separate_and_never_football_authority(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert all(
        row["price_economic_risk"]["football_authority"] is False
        and row["governance"]["price_predictor_is_football_authority"] is False
        for row in result["routes"]
    )


def test_17_information_value_is_explicit(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    assert row["information_value"]["status"] == "AVAILABLE"
    assert row["information_value"]["value"] == pytest.approx(0.10)
    assert row["information_value"]["drivers"]["pending_lineup_information"] is True


def test_18_dynamic_ft_shadow_uses_canonical_future_opportunity_difference(monkeypatch):
    _, result = _evaluate(monkeypatch)
    row = _change(result["routes"])
    shadow = row["dynamic_ft_shadow"]
    assert shadow["status"] == "PASS"
    assert shadow["method"] == "FUTURE_OPTIMIZATION_OPPORTUNITY_DIFFERENCE"
    assert shadow["ft_shadow_value"] == pytest.approx(0.25)
    assert shadow["fixed_universal_ft_value"] is False


def test_19_hold_can_legitimately_beat_every_change(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _negative_fake_lineup)
    search_result = _search()
    future, info, price = _contexts(search_result)
    result = utility.evaluate_packages(
        search_result=search_result,
        projections=_projections(),
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        generated_at=GENERATED,
    )
    assert result["selected_route_id"] == "HOLD"
    assert result["decision"]["football_action"] == "HOLD"
    assert result["decision"]["operational_action"] == "WAIT"


def test_20_expected_regret_is_present_for_resolved_routes(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert all(row["expected_regret"] is not None for row in result["routes"])
    assert min(row["expected_regret"] for row in result["routes"]) == pytest.approx(0.0)


def test_21_phase0_freeze_is_immutable_and_settlement_is_separate(monkeypatch):
    _, result = _evaluate(monkeypatch)
    frozen = utility.freeze_package_decision(
        result,
        deadline_time="2026-09-20T10:00:00Z",
        frozen_at="2026-09-20T09:00:00Z",
    )
    assert frozen["status"] == "FROZEN_AWAITING_SETTLEMENT"
    with pytest.raises(ModelEvidenceError):
        utility.freeze_package_decision(
            result,
            deadline_time="2026-09-20T10:00:00Z",
            frozen_at="2026-09-20T09:10:00Z",
            existing_record=frozen,
        )
    settled = utility.settle_package_decision(
        frozen,
        decision_outcome_evidence={
            "chosen_transfer_net": 5.0,
            "best_transfer_or_hold_net": 7.0,
            "hold_realized_net": 4.0,
            "act_realized_net": 5.0,
            "chosen_action": "ACT",
            "rental_player_points": 8.0,
            "hold_player_points": 5.0,
            "rental_exact_hit_cost": 0.0,
            "rental_exact_exit_cost": 0.0,
        },
        event_finished=True,
        settled_at="2026-09-21T20:00:00Z",
    )
    assert settled["status"] == "SETTLED"
    metrics = settled["decision_calibration"]["metrics"]
    assert metrics["transfer_counterfactual_regret"]["value"] == pytest.approx(2.0)
    assert metrics["one_gw_rental_realized_pnl"]["value"] == pytest.approx(3.0)
    assert (
        settled["prediction_calibration"]["governance"][
            "prediction_error_separate_from_decision_error"
        ]
        is True
    )


def test_22_20_25_30_25_is_unchanged(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["methodology"]["weights"] == CANONICAL_WEIGHTS
    assert result["methodology"]["weights_unchanged"] is True
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }


def test_23_p1_1_p1_3_p1_6_p1_7_inputs_are_read_only(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    search_result = _search()
    projections = _projections()
    search_before = deepcopy(search_result)
    projections_before = deepcopy(projections)
    future, info, price = _contexts(search_result)
    result = utility.evaluate_packages(
        search_result=search_result,
        projections=projections,
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        generated_at=GENERATED,
    )
    assert search_result == search_before
    assert projections == projections_before
    governance = result["governance"]
    assert governance["p1_1_math_mutated"] is False
    assert governance["p1_3_math_mutated"] is False
    assert governance["p1_6_math_mutated"] is False
    assert governance["p1_7_math_mutated"] is False


def test_24_no_mini_league_overlay(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["methodology"]["mini_league"] == "NOT_CONSUMED"
    assert result["governance"]["mini_league_overlay_started"] is False


def test_25_v6_scheduler_and_authority_are_unchanged(monkeypatch):
    _, result = _evaluate(monkeypatch)
    governance = result["governance"]
    assert governance["v6_mutated"] is False
    assert governance["scheduler_changed"] is False
    assert governance["authority_added"] is False
    source = inspect.getsource(utility)
    assert "src.runtime_v6" not in source
    assert "config/v6" not in source


def test_26_search_and_utility_owners_are_distinct(monkeypatch):
    _, result = _evaluate(monkeypatch)
    assert result["governance"]["p1_2a_search_owner"] == "V12_PACKAGE_SEARCH"
    assert result["governance"]["p1_2b_utility_owner"] == "V12_PACKAGE_UTILITY"
    assert result["governance"]["search_and_utility_separate"] is True
    assert package_search.MODEL_OWNER != utility.MODEL_OWNER
