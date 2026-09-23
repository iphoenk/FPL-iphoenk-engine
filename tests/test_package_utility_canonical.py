from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from src.engines import v12_package_search as package_search
from src.engines import v12_package_utility as utility
from src.engines.canonical_decision_methodology import CANONICAL_WEIGHTS
from src.engines.lineup_governance import build_package_decision
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



def _team() -> dict:
    current = _current()
    return {
        "squad_authority": "OFFICIAL_FPL_AUTHENTICATED",
        "squad": [{"element": row["element"]} for row in current],
        "team_value_ledger": [
            {
                "element": row["element"],
                "sell_cost": row["sell_cost"],
            }
            for row in current
        ],
    }


def test_27_native_package_consumer_uses_p1_2b_as_decision_owner(monkeypatch):
    _, result = _evaluate(monkeypatch)
    decision = build_package_decision(
        result,
        _projections(),
        {},
        _team(),
    )
    assert decision["gate0_revalidated"] is True
    assert (
        decision["governance"]["production_package_decision_owner"]
        == "V12_PACKAGE_UTILITY"
    )
    assert decision["governance"]["native_package_utility_consumed"] is True
    assert (
        decision["governance"]["legacy_package_optimizer_decision_authority"]
        is False
    )
    assert decision["selected_package_id"] == result["selected_route_id"]


def test_28_legacy_optimizer_can_no_longer_authorize_change_action():
    legacy = {
        "hold": {
            "id": "HOLD",
            "legal": True,
            "score": {"valid": True},
        },
        "packages": [
            {
                "id": "LEGACY_BEST_CHANGE",
                "legal": True,
                "score": {"valid": True, "robust_score": 999.0},
            }
        ],
    }
    decision = build_package_decision(
        legacy,
        _projections(),
        {},
        _team(),
    )
    assert decision["selected_package_id"] == "HOLD"
    assert decision["decision"]["football_action"] == "HOLD"
    assert decision["decision"]["operational_action"] == "PREPARE"
    assert (
        decision["governance"]["legacy_package_optimizer_decision_authority"]
        is False
    )
    assert (
        decision["governance"]["legacy_candidate_can_trigger_change_action"]
        is False
    )


def test_29_migration_comparison_has_bounded_taxonomy(monkeypatch):
    search_result, result = _evaluate(monkeypatch)
    legacy = {
        "hold": {"id": "HOLD"},
        "packages": [
            {"id": row["route_id"]}
            for row in search_result["routes"][1:4]
        ],
    }
    comparison = utility.compare_legacy_package(
        native_search=search_result,
        native_utility=result,
        legacy_optimizer=legacy,
    )
    assert comparison["unexpected_regression_count"] == 0
    assert comparison["classification"] in comparison["classification_taxonomy"]
    assert comparison["legacy_utility_equivalence_required"] is False
    assert "UNEXPECTED_REGRESSION" in comparison["classification_taxonomy"]


def test_30_model_evidence_is_non_authoritative(monkeypatch):
    _, result = _evaluate(monkeypatch)
    evidence = result["model_evidence_binding"]
    assert evidence["authority"] is False
    assert evidence["raw_v6_payload_duplicated"] is False
    assert evidence["repository_python_execution_claimed"] is False
    assert len(evidence["run_fingerprint"]) == 64
    assert len(evidence["output_fingerprint"]) == 64



def test_31_p1_2b_parallel_runtime_is_bounded_execution_only():
    perf = utility.load_config()["performance"]
    assert perf["parallel_lineup_min_routes"] >= 64
    assert 2 <= perf["parallel_lineup_max_workers"] <= 4
    assert perf["parallel_chunks_per_worker"] >= 1
    assert perf["lossy_pruning"] is False
    assert perf["route_identity_preserved"] is True
    assert perf["p1_7_owner_unchanged"] is True

    materializer = inspect.getsource(utility._materialize_route_lineups)
    worker = inspect.getsource(utility._p1_2b_route_lineups_worker)
    assert "ProcessPoolExecutor" in inspect.getsource(utility)
    assert "PROCESS_POOL_EXACT_P1_7" in materializer
    assert "_cumulative_lineup_horizons(" in worker
    assert "optimize_lineup(" in inspect.getsource(utility._lineup_decision)
    assert "lossy_pruning" in materializer


def test_32_exact_route_materializer_preserves_sequential_p1_7_results(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    real_config = deepcopy(utility.load_config())
    real_config.setdefault("performance", {})["parallel_lineup_min_routes"] = 999999
    monkeypatch.setattr(utility, "load_config", lambda: real_config)

    search_result = _search()
    routes = search_result["routes"][:8]
    projections = _projections()
    actual, proof = utility._materialize_route_lineups(
        routes,
        projections,
        planning_gw=GW,
        generated_at=GENERATED,
    )

    expected = {
        row["route_id"]: utility._cumulative_lineup_horizons(
            projections,
            utility._route_squad(row),
            planning_gw=GW,
            generated_at=GENERATED,
        )
        for row in routes
    }
    assert actual == expected
    assert proof["execution_mode"] == "SEQUENTIAL_EXACT_P1_7"
    assert proof["route_count"] == len(routes)
    assert proof["exact_route_identity_preserved"] is True
    assert proof["lossy_pruning"] is False
    assert proof["p1_7_math_mutated"] is False
    assert proof["elapsed_seconds"] > 0.0
    assert proof["unique_squad_elapsed_seconds"]["count"] == len(routes)
    assert proof["per_gw_elapsed_seconds"]["count"] == len(routes) * 5
    assert 0.0 < proof["worker_utilization_estimate"] <= 1.0
    assert proof["coordination_serialization_upper_bound_seconds"] >= 0.0


def test_33_process_worker_calls_same_exact_p1_7_horizon_owner(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    projections = _projections()
    squad = utility._route_squad(_search()["routes"][0])
    expected = utility._cumulative_lineup_horizons(
        projections,
        squad,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    utility._init_p1_2b_lineup_worker(
        projections,
        GW,
        GENERATED,
    )
    (
        route_id,
        returned_squad,
        actual,
        elapsed,
        gw_elapsed,
    ) = utility._p1_2b_route_lineups_worker(("HOLD", squad))
    assert route_id == "HOLD"
    assert returned_squad == squad
    assert actual == expected
    assert elapsed > 0.0
    assert len(gw_elapsed) == 5
    assert all(value > 0.0 for value in gw_elapsed)


def test_34_package_output_carries_non_authoritative_execution_proof(monkeypatch):
    search_result, result = _evaluate(monkeypatch)
    proof = result["governance"]["p1_7_execution_proof"]
    assert proof["route_count"] == len(search_result["routes"])
    assert proof["p1_7_owner"] == "V12_LINEUP_OPTIMIZER"
    assert proof["decision_authority_changed"] is False
    assert proof["lossy_pruning"] is False
    assert result["methodology"]["lineup_execution"] == proof

def _canonical_compact_reference(lineup):
    def bench(starters, reserve_gk, outfield_bench):
        winner, _ = lineup.optimize_bench_order(
            starters,
            reserve_gk,
            outfield_bench,
            include_winner_blocking_counterfactual=False,
            publish_alternatives=False,
            include_winner_slots=False,
        )
        return winner

    def cvc(starters, ranked_pairs):
        del ranked_pairs
        return lineup._best_captain_vice_pair(starters)

    return bench, cvc


def _randomized_projections(seed: int) -> dict:
    import random

    rng = random.Random(seed)
    payload = deepcopy(_projections())
    for player in payload["players"]:
        dnp = rng.uniform(0.02, 0.16)
        cameo_total = rng.uniform(0.04, min(0.20, 0.42 - dnp))
        late = rng.uniform(0.01, min(0.07, cameo_total))
        regular = cameo_total - late
        start = 1.0 - dnp - cameo_total
        xmins = player["xmins"]
        xmins["start_probability"] = start
        xmins["cameo_probability"] = cameo_total
        xmins["late_cameo_probability"] = late
        xmins["dnp_probability"] = dnp
        xmins["expected_minutes"] = 90 * start + 18 * regular + 7 * late
        xmins["xmins_distribution"]["mean"] = xmins["expected_minutes"]
        xmins["xmins_distribution"]["states"] = [
            {"state": "START", "probability": start},
            {"state": "REGULAR_CAMEO", "probability": regular},
            {"state": "LATE_CAMEO", "probability": late},
            {"state": "ZERO_MINUTES", "probability": dnp},
        ]
        for gw_row in player["xpts_by_gw"]:
            blank = rng.uniform(0.05, 0.24)
            upside = rng.uniform(0.08, 0.28)
            middle = 1.0 - blank - upside
            probs = {"0": blank, "4": middle, "8": upside}
            mean = 4.0 * middle + 8.0 * upside
            second = 16.0 * middle + 64.0 * upside
            variance = max(0.0, second - mean * mean)
            gw_row["mean"] = mean
            gw_row["std"] = variance ** 0.5
            gw_row["points_variance"] = variance
            gw_row["point_distribution"]["probabilities"] = probs
    return payload


def test_35_prepared_compact_bench_and_cvc_match_canonical_all_550_xi():
    from src.engines import v12_lineup_optimizer as lineup

    projections = _randomized_projections(1207)
    pmap = {row["element"]: row for row in projections["players"]}
    squad_ids = tuple(row["element"] for row in _current())
    surfaces = [
        lineup.build_player_surface(pmap[element], GW)
        for element in squad_ids
    ]
    legal = lineup.enumerate_legal_xi(surfaces)
    assert len(legal) == 550
    ranked_pairs = lineup.evaluate_captain_vice_pairs(surfaces)

    bench_fields = (
        "order",
        "expected_autosub_value",
        "autosub_probability",
        "expected_selected_blank_probability_mass",
        "expected_selected_ge8_probability_mass",
        "expected_selected_ge10_probability_mass",
        "bench_order_utility",
    )
    for indices in legal:
        starters = [surfaces[index] for index in indices]
        starter_ids = {row["element"] for row in starters}
        bench = [row for row in surfaces if row["element"] not in starter_ids]
        reserve_gk = next(row for row in bench if row["position"] == "GK")
        outfield_bench = [row for row in bench if row["position"] != "GK"]

        expected_bench, _ = lineup.optimize_bench_order(
            starters,
            reserve_gk,
            outfield_bench,
            include_winner_blocking_counterfactual=False,
            publish_alternatives=False,
            include_winner_slots=False,
        )
        actual_bench = lineup._compact_bench_order_winner_exact(
            starters,
            reserve_gk,
            outfield_bench,
        )
        assert {
            key: actual_bench[key] for key in bench_fields
        } == {
            key: expected_bench[key] for key in bench_fields
        }

        expected_cvc = lineup._best_captain_vice_pair(starters)
        actual_cvc = lineup._best_captain_vice_pair_from_ranked_exact(
            starters,
            ranked_pairs,
        )
        assert actual_cvc == expected_cvc


@pytest.mark.parametrize("seed", [1207, 4319, 6471])
def test_36_prepared_p17_full_decision_matches_pre_repair_reference(
    monkeypatch, seed
):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _randomized_projections(seed)
    squad_ids = tuple(row["element"] for row in _current())

    actual = lineup.optimize_lineup(
        projections,
        squad_ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    reference_bench, reference_cvc = _canonical_compact_reference(lineup)
    with monkeypatch.context() as patch:
        patch.setattr(
            lineup,
            "_compact_bench_order_winner_exact",
            reference_bench,
        )
        patch.setattr(
            lineup,
            "_best_captain_vice_pair_from_ranked_exact",
            reference_cvc,
        )
        expected = lineup.optimize_lineup(
            projections,
            squad_ids,
            planning_gw=GW,
            generated_at=GENERATED,
        )

    assert actual == expected
    assert actual["legal_xi_count"] == 550
    assert actual["governance"]["all_legal_xi_enumerated"] is True


def test_37_prepared_p17_preserves_1_2_3_5gw_cumulative_outputs(monkeypatch):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _randomized_projections(1207647)
    squad_ids = tuple(row["element"] for row in _current())

    actual = utility._cumulative_lineup_horizons(
        projections,
        squad_ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    reference_bench, reference_cvc = _canonical_compact_reference(lineup)
    with monkeypatch.context() as patch:
        patch.setattr(
            lineup,
            "_compact_bench_order_winner_exact",
            reference_bench,
        )
        patch.setattr(
            lineup,
            "_best_captain_vice_pair_from_ranked_exact",
            reference_cvc,
        )
        expected = utility._cumulative_lineup_horizons(
            projections,
            squad_ids,
            planning_gw=GW,
            generated_at=GENERATED,
        )

    assert actual == expected
    for horizon in ("1", "2", "3", "5"):
        assert actual[horizon]["status"] == "READY"


def test_38_prepared_exact_p17_has_material_runtime_margin(capsys):
    import json
    import time
    from src.engines import v12_lineup_optimizer as lineup

    projections = _randomized_projections(6481)
    squad_ids = tuple(row["element"] for row in _current())
    pmap = {
        int(row["element"]): row
        for row in projections["players"]
    }
    players = [
        lineup.build_player_surface(pmap[int(element)], GW)
        for element in squad_ids
    ]

    started = time.perf_counter()
    reference = lineup._decision_core_scalar_reference(players)
    reference_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    repaired = lineup._decision_core(players)
    repaired_elapsed = time.perf_counter() - started

    for key in (
        "selected",
        "best_alternative",
        "formation_comparison",
        "close_call_proof",
        "alternatives",
        "legal_xi_count",
        "legal_formations_evaluated",
    ):
        assert repaired[key] == reference[key]
    for key in (
        "all_legal_routes_ranked_exactly",
        "selected_route_fully_materialized",
        "best_alternative_fully_materialized",
        "other_published_routes",
        "formation_comparison_source",
        "route_pruning_applied",
        "route_utility_changed",
    ):
        assert (
            repaired["materialization_governance"][key]
            == reference["materialization_governance"][key]
        )
    assert repaired_elapsed < reference_elapsed * 0.50
    speedup = reference_elapsed / max(repaired_elapsed, 1e-9)
    evidence = {
        "contract": "P1_2B_P1_7_RUNTIME_ACCEPTANCE_V2",
        "reference_seconds": round(reference_elapsed, 6),
        "repaired_seconds": round(repaired_elapsed, 6),
        "speedup": round(speedup, 3),
        "legal_xi": repaired["legal_xi_count"],
        "execution_kernel": repaired["materialization_governance"].get(
            "execution_kernel"
        ),
        "route_pruning": False,
        "approximation": False,
    }
    print("P1_2B_RUNTIME_ACCEPTANCE=" + json.dumps(evidence, sort_keys=True))
    captured = capsys.readouterr()
    assert "P1_2B_RUNTIME_ACCEPTANCE=" in captured.out

def test_full_direct_plus_material_funded_utility_preserves_truthful_scope(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    direct_search = package_search.search_packages(
        current_squad=_current(),
        candidate_universe=_universe(),
        bank=0,
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=len(_candidates()),
    )
    future, info, price = _contexts(direct_search)
    direct_utility = utility.evaluate_packages(
        search_result=direct_search,
        projections=_projections(),
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        generated_at=GENERATED,
    )
    funding_legs = utility.select_material_funding_legs(direct_utility)
    funded_search = package_search.compose_material_two_transfer_packages(
        current_squad=_current(),
        direct_search_result=direct_search,
        material_direct_route_ids=funding_legs["route_ids"],
        bank=0,
    )
    funded_future, funded_info, funded_price = _contexts(funded_search)
    funded_utility = utility.evaluate_packages(
        search_result=funded_search,
        projections=_projections(),
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=funded_future,
        information_value_by_route=funded_info,
        price_risk_by_route=funded_price,
        generated_at=GENERATED,
    )
    combined = utility.combine_package_utility_surfaces(
        direct_utility,
        funded_utility,
        funded_search_result=funded_search,
    )

    direct_ids = {row["route_id"] for row in direct_utility["routes"]}
    combined_ids = {row["route_id"] for row in combined["routes"]}
    assert direct_ids <= combined_ids
    assert combined["search_authority"] == "FULL_DIRECT_MATERIAL_FUNDED"
    assert combined["search_scope"]["direct"]["global_direct_complete"] is True
    assert (
        combined["search_scope"]["funded_two_transfer"][
            "global_two_transfer_complete"
        ]
        is False
    )
    assert combined["search_scope"]["global_two_transfer_exhaustive_claim"] is False
    assert combined["governance"]["funded_materialization"][
        "decision_authority_changed"
    ] is False
    assert any(
        int(row.get("transfer_count") or 0) == 2
        for row in combined["routes"]
    )


def test_funding_leg_selector_reuses_existing_materiality_authority(monkeypatch):
    monkeypatch.setattr(utility, "_lineup_decision", _fake_lineup)
    direct_search = package_search.search_packages(
        current_squad=_current(),
        candidate_universe=_universe(),
        bank=5,
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=len(_candidates()),
    )
    future, info, price = _contexts(direct_search)
    direct_utility = utility.evaluate_packages(
        search_result=direct_search,
        projections=_projections(),
        free_transfers=2,
        hit_cost_per_extra_transfer=4,
        future_frontier_by_route=future,
        information_value_by_route=info,
        price_risk_by_route=price,
        generated_at=GENERATED,
    )
    selected = utility.select_material_funding_legs(direct_utility)
    assert selected["status"] == "READY"
    assert selected["route_ids"]
    assert selected["source"] == "P1_4_EXISTING_MATERIALITY_SELECTOR"
    assert selected["no_new_player_score"] is True
    assert selected["no_new_package_score"] is True
    assert len(selected["route_ids"]) <= selected["direct_leg_limit"]



def _assert_batch_lineup_row_matches_scalar(actual, expected):
    keys = (
        "status",
        "gw",
        "route_utility",
        "expected_fpl_points",
        "distributional_downside",
        "supportable_upside",
        "expected_autosub_value",
        "cameo_blocking_cost",
        "formation",
        "starting_xi",
        "bench_gk",
        "bench_order",
        "captain",
        "vice_captain",
        "captain_safe_pool_count",
        "confidence",
        "covariance_status",
    )
    assert {key: actual.get(key) for key in keys} == {
        key: expected.get(key) for key in keys
    }


def test_route_batch_p17_selected_summary_matches_scalar_exactly():
    from src.engines import v12_lineup_optimizer as lineup

    projections = _randomized_projections(9237)
    search = package_search.search_packages(
        current_squad=_current(),
        candidate_universe=_universe(),
        bank=5,
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=len(_candidates()),
    )
    routes = list(search["routes"])[:12]
    squads = {
        str(route["route_id"]): tuple(
            sorted(int(value) for value in route["final_squad_elements"])
        )
        for route in routes
    }
    actual = lineup.optimize_lineup_summaries_exact_batch(
        projections,
        squads,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    for route_id, squad in squads.items():
        expected = utility._lineup_decision(
            projections,
            squad,
            gw=GW,
            generated_at=GENERATED,
        )
        _assert_batch_lineup_row_matches_scalar(
            actual[route_id],
            expected,
        )
        governance = actual[route_id]["governance"]
        assert governance["route_batch_execution_only"] is True
        assert governance[
            "all_550_legal_xi_numerically_evaluated"
        ] is True
        assert governance["scalar_exact_refinement_count"] >= 1
        assert governance["numerical_guard"] == pytest.approx(1e-4)


def _route_batch_stress_fixture(route_count=2043):
    projections = _randomized_projections(19437)
    current_ids = tuple(
        sorted(row["element"] for row in _current())
    )
    mids = [
        row["element"]
        for row in _current()
        if row["position"] == "MID"
    ]
    pmap = {
        row["element"]: row
        for row in projections["players"]
    }
    candidate_ids = []
    for index in range(410):
        element = 1000 + index
        source = deepcopy(pmap[mids[index % len(mids)]])
        source["element"] = element
        source["name"] = f"B{element}"
        source["team_id"] = 1 + (index % 20)
        shift = ((index % 31) - 15) * 0.0004
        for gw_row in source["xpts_by_gw"]:
            probs = dict(
                gw_row["point_distribution"]["probabilities"]
            )
            blank = max(
                0.02,
                min(0.30, float(probs["0"]) - shift),
            )
            upside = max(
                0.04,
                min(0.35, float(probs["8"]) + shift),
            )
            middle = 1.0 - blank - upside
            probs = {
                "0": blank,
                "4": middle,
                "8": upside,
            }
            mean = 4.0 * middle + 8.0 * upside
            second = 16.0 * middle + 64.0 * upside
            variance = max(0.0, second - mean * mean)
            gw_row["mean"] = mean
            gw_row["std"] = variance ** 0.5
            gw_row["points_variance"] = variance
            gw_row["point_distribution"]["probabilities"] = probs
        projections["players"].append(source)
        candidate_ids.append(element)

    routes = [
        {
            "route_id": "HOLD",
            "final_squad_elements": list(current_ids),
        }
    ]
    for element in candidate_ids:
        for outgoing in mids:
            if len(routes) >= int(route_count):
                break
            squad = sorted(
                (set(current_ids) - {int(outgoing)})
                | {int(element)}
            )
            routes.append(
                {
                    "route_id": f"{outgoing}->{element}",
                    "final_squad_elements": squad,
                }
            )
        if len(routes) >= int(route_count):
            break
    assert len(routes) == int(route_count)
    return projections, routes


def test_full_2043_route_batch_p17_runtime_acceptance(capsys):
    import json
    import time

    projections, routes = _route_batch_stress_fixture(2043)
    started = time.perf_counter()
    lineups, proof = utility._materialize_route_lineups(
        routes,
        projections,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    elapsed = time.perf_counter() - started

    assert len(lineups) == 2043
    assert proof["route_count"] == 2043
    assert proof["unique_squad_count"] == 2043
    assert proof["execution_mode"] in {
        "PROCESS_POOL_EXACT_P1_7_ROUTE_BATCH",
        "SEQUENTIAL_EXACT_P1_7_ROUTE_BATCH",
    }
    assert proof["route_batch_all_direct_routes_preserved"] is True
    assert proof["lossy_pruning"] is False
    assert proof["p1_7_math_mutated"] is False
    assert proof["decision_authority_changed"] is False
    assert proof["route_batch_count"] > 0
    assert proof["route_batch_exact_refinement_count"] >= 2043 * 5
    assert proof["elapsed_seconds"] <= 10.0
    assert elapsed <= 10.0

    current_ids = tuple(
        sorted(row["element"] for row in _current())
    )
    sample_route_ids = [
        "HOLD",
        routes[len(routes) // 2]["route_id"],
        routes[-1]["route_id"],
    ]
    route_by_id = {
        str(route["route_id"]): route
        for route in routes
    }
    for route_id in sample_route_ids:
        squad = tuple(
            sorted(
                int(value)
                for value in route_by_id[route_id][
                    "final_squad_elements"
                ]
            )
        )
        expected = utility._cumulative_lineup_horizons(
            projections,
            squad,
            planning_gw=GW,
            generated_at=GENERATED,
        )
        actual = lineups[route_id]
        for actual_row, expected_row in zip(
            actual["per_gw"],
            expected["per_gw"],
        ):
            _assert_batch_lineup_row_matches_scalar(
                actual_row,
                expected_row,
            )
        for horizon in ("1", "2", "3", "5"):
            assert actual[horizon] == expected[horizon]

    evidence = {
        "contract": "P1_2B_2043_ROUTE_BATCH_RUNTIME_ACCEPTANCE_V1",
        "route_count": proof["route_count"],
        "unique_squad_count": proof["unique_squad_count"],
        "execution_mode": proof["execution_mode"],
        "worker_count": proof["worker_count"],
        "route_batch_size": proof["route_batch_size"],
        "route_batch_count": proof["route_batch_count"],
        "exact_refinement_count": proof[
            "route_batch_exact_refinement_count"
        ],
        "materialization_seconds": proof["elapsed_seconds"],
        "outer_wall_seconds": round(elapsed, 6),
        "lossy_pruning": proof["lossy_pruning"],
        "p1_7_math_mutated": proof["p1_7_math_mutated"],
    }
    print(
        "P1_2B_ROUTE_BATCH_ACCEPTANCE="
        + json.dumps(evidence, sort_keys=True)
    )
    captured = capsys.readouterr()
    assert "P1_2B_ROUTE_BATCH_ACCEPTANCE=" in captured.out
