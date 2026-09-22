from __future__ import annotations

from src.engines.v12_stage3_decision import (
    build_price_uncertainty,
    build_robustness,
    build_sequential_rollout,
    compose_stage3_decision,
    load_config,
    select_material_football_route,
)


def _route(route_id, points, *, economics="PARTIAL"):
    return {
        "route_id": route_id,
        "classification": "HOLD" if route_id == "HOLD" else "CHANGE",
        "transfer_count": 0 if route_id == "HOLD" else 1,
        "players_out": [] if route_id == "HOLD" else [{"element": 10}],
        "players_in": [] if route_id == "HOLD" else [{"element": 20}],
        "football_route_utility": {
            "per_gw": [
                {
                    "status": "READY",
                    "gw": 6 + i,
                    "expected_fpl_points": value,
                    "starting_xi": list(range(1, 12)),
                    "bench_gk": 12,
                    "bench_order": [13, 14, 15],
                    "captain": 1,
                    "vice_captain": 2,
                }
                for i, value in enumerate(points)
            ]
        },
        "transfer_economics": {
            "status": economics,
            "decision_chain_stage": "TRANSFER_ECONOMICS",
            "included_in_football_score": False,
        },
        "information_value": {"status": "UNAVAILABLE", "value": None},
    }


def _package():
    return {
        "model_owner": "V12_PACKAGE_UTILITY",
        "routes": [
            _route("HOLD", [50, 50, 50, 50, 50], economics="PASS"),
            _route("R1", [51, 51, 51, 51, 51]),
            _route("R2", [50.5, 50.1, 49.9, 49.8, 49.7]),
        ],
        "selected_route_id": "HOLD",
    }


def _mc():
    return {
        "model_owner": "V12_MONTE_CARLO",
        "execution_state": "EXECUTED",
        "canonical_pass": True,
        "actual_paths": 500000,
        "sampling_diagnostics": {
            "match_state_invariants": {"status": "PASS"}
        },
        "metrics": {
            "R1": {
                "1": {
                    "expected_regret": 1.0,
                    "decision_net_supported": False,
                }
            }
        },
        "paired_outputs": {
            "HOLD__VS__R1__H1": {
                "mean_difference": -1.0,
                "p_a_gt_b": 0.35,
                "p_a_lt_b": 0.65,
                "p_delta_ge_meaningful_threshold": 0.2,
                "Q10": -8.0,
                "Q25": -4.0,
                "median": -1.0,
                "Q75": 1.0,
                "Q90": 3.0,
            }
        },
    }


def _team():
    return {
        "bank": None,
        "free_transfers": None,
        "chips": None,
        "availability": {
            "bank": "UNAVAILABLE",
            "free_transfers": "NOT_SUPPORTED",
            "selling_price": "UNAVAILABLE",
            "purchase_price": "UNAVAILABLE",
            "chips": "UNAVAILABLE",
        },
        "players": [
            {"element_id": i, "selling_price": None}
            for i in range(1, 16)
        ],
    }


def test_stage3_is_strictly_downstream():
    governance = load_config()["governance"]
    assert governance["downstream_only"] is True
    assert governance["p1_1_read_only"] is True
    assert governance["p1_3_read_only"] is True
    assert governance["dynamic_fdr_read_only"] is True
    assert governance["position_engines_read_only"] is True
    assert governance["weights_20_25_30_25_unchanged"] is True
    assert governance["v6_mutated"] is False


def test_material_comparator_comes_from_p1_2_routes_without_becoming_authority():
    result = select_material_football_route(_package())
    assert result["route_id"] == "R1"
    assert result["selection_authority"] is False
    assert result["final_transfer_decision"] is False


def test_private_economics_missing_does_not_destroy_football_rollout():
    out = build_sequential_rollout(
        _package(), current_team=_team(), material_route_id="R1"
    )
    assert out["status"] == "PARTIAL_FACTUAL_ECONOMICS"
    assert out["act_blocked_by_missing_private_economics"] is True
    assert out["current_action_fixed_squad_horizons"]["GW+1"][
        "gross_delta_vs_hold"
    ] == 1.0
    assert out["independent_future_gw_sum_claimed_as_dynamic_programming"] is False


def test_price_likelihood_bucket_is_not_invented_probability():
    predictor = {
        "data": {
            "players": [
                {
                    "id": 20,
                    "price_change_percent": "88.0",
                    "price_change_hourly_rate": 10,
                    "price_change_projections": [
                        {"offset": 0, "projected_percent": "90.0", "likelihood": 3}
                    ],
                }
            ]
        }
    }
    out = build_price_uncertainty(predictor, relevant_element_ids=[20])
    assert out["status"] == "UNAVAILABLE_NO_CALIBRATED_PROBABILITY_MAPPING"
    assert out["likelihood_bucket_to_probability_mapping_used"] is False
    assert out["rows"][0]["P_rise_before_deadline"] is None


def test_mc_robustness_uses_pairwise_distribution_not_mean_only():
    out = build_robustness(_mc(), route_id="R1")
    assert out["pairwise_gw1"]["p_a_gt_b"] == 0.65
    assert out["pairwise_gw1"]["Q10"] == -3.0
    assert out["classification"] in {"ROBUST", "FRAGILE"}
    assert "creator_absent" in out["stress_coverage"]["modelled"]


def test_unresolved_private_economics_forces_prepare_not_act():
    out = compose_stage3_decision(
        package_utility=_package(),
        monte_carlo=_mc(),
        mini_league_overlay={"model_owner": "V12_MINI_LEAGUE_OVERLAY"},
        current_team=_team(),
        price_predictor={"data": {"players": []}},
        material_route_id="R1",
    )
    assert out["action"]["state"] == "PREPARE"
    assert out["action"]["reason"] == "PRIVATE_TRANSFER_ECONOMICS_UNRESOLVED"
    assert out["governance"]["v6_mutated"] is False
