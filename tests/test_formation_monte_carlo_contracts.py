from __future__ import annotations

import pytest

from src.engines.v12_formation_monte_carlo import (
    FORMATIONS,
    FormationMonteCarloError,
    run_forced_lineup_monte_carlo,
    run_formation_monte_carlo,
)
from src.engines.v12_report_orchestration import _formation_mc_lines


def _routes():
    rows = []
    for index, formation in enumerate(FORMATIONS, start=1):
        rows.append(
            {
                "formation": formation,
                "per_gw": [
                    {
                        "gw": gw,
                        "starting_xi": list(range(1, 12)),
                        "bench_order": [12, 13, 14],
                        "bench_gk": 15,
                        "captain": 1,
                        "vice_captain": 2,
                    }
                    for gw in range(7, 13)
                ],
                "p17_fingerprint": f"p17-{index}",
            }
        )
    return rows


def _fake_simulator(projections, route_defs, **kwargs):
    assert len(route_defs) == 8
    assert route_defs[0]["route_id"] == "HOLD"
    assert kwargs["actual_paths"] == 500_000
    assert kwargs["horizons"] == (6,)
    assert kwargs["canonical"] is True
    assert kwargs["selected_route_id"] == "HOLD"
    metrics = {}
    path_semantics = {}
    for route in route_defs:
        route_id = route["route_id"]
        if route_id == "FORMATION_REFERENCE":
            continue
        metrics[route_id] = {
            "6": {
                "status": "READY",
                "mean_net_utility": 100.0,
                "median": 99.0,
                "standard_deviation": 12.0,
                "p10": 80.0,
                "p90": 120.0,
            }
        }
        path_semantics[route_id] = {
            "by_gw": {
                str(gw): {
                    "autosub_path_rate": 0.1,
                    "captain_takeover_path_rate": 0.2,
                    "captain_blank_probability": 0.3,
                    "captain_haul_probability": 0.4,
                    "expected_autosub_value": 0.5,
                }
                for gw in range(7, 13)
            }
        }
    return {
        "status": "PASS",
        "execution_state": "EXECUTED",
        "canonical_pass": True,
        "actual_paths": 500_000,
        "common_random_numbers": True,
        "correlated": True,
        "convergence_evidence": {"status": "PASS"},
        "metrics": metrics,
        # performance is timing metadata, never a sampling source.
        "performance": {"route_path_semantics": {"HOLD": {"by_gw": {}}}},
        "sampling_diagnostics": {
            "route_path_semantics": path_semantics,
            "state_frequencies": {
                f"{element}:gw7": {"DNP": 0.09}
                for element in range(1, 16)
            },
        },
        "output_fingerprint": "mc-fingerprint",
    }


def test_forced_lineup_mc_binds_exact_routes_to_same_current15_and_kernel():
    routes = [
        {
            "route_id": "HOLD",
            "label": "Scenario A",
            "per_gw": [
                {
                    "gw": gw,
                    "starting_xi": list(range(1, 12)),
                    "bench_order": [12, 13, 14],
                    "bench_gk": 15,
                    "captain": 1,
                    "vice_captain": 2,
                }
                for gw in range(7, 13)
            ],
        },
        {
            "route_id": "SCENARIO_B",
            "label": "Scenario B",
            "per_gw": [
                {
                    "gw": gw,
                    "starting_xi": list(range(2, 13)),
                    "bench_order": [1, 13, 14],
                    "bench_gk": 15,
                    "captain": 2,
                    "vice_captain": 3,
                }
                for gw in range(7, 13)
            ],
        },
    ]

    def simulator(projections, route_defs, **kwargs):
        assert [row["route_id"] for row in route_defs] == ["HOLD", "SCENARIO_B"]
        assert kwargs["actual_paths"] == 500_000
        assert kwargs["horizons"] == (1, 3, 5)
        assert kwargs["selected_route_id"] == "HOLD"
        assert kwargs["canonical"] is True
        return {
            "execution_state": "EXECUTED",
            "canonical_pass": True,
            "actual_paths": 500_000,
            "common_random_numbers": True,
            "correlated": True,
            "convergence_evidence": {"status": "PASS"},
            "metrics": {
                route_id: {
                    str(horizon): {"status": "READY", "mean_net_utility": 10.0}
                    for horizon in (1, 3, 5)
                }
                for route_id in ("HOLD", "SCENARIO_B")
            },
            "paired_outputs": {
                "HOLD__VS__SCENARIO_B__H1": {"status": "READY", "p_a_gt_b": 0.6},
                "HOLD__VS__SCENARIO_B__H3": {"status": "READY", "p_a_gt_b": 0.55},
                "HOLD__VS__SCENARIO_B__H5": {"status": "READY", "p_a_gt_b": 0.52},
            },
            "model_evidence_binding": {"output_fingerprint": "projection-fp"},
        }

    result = run_forced_lineup_monte_carlo(
        {"planning_gw": 7},
        current15=list(range(1, 16)),
        scenarios=routes,
        input_snapshot_id="private-full-master:gw7",
        simulator=simulator,
    )

    assert result["integrity"]["exact_route_binding"] is True
    assert result["integrity"]["common_random_numbers"] is True
    assert result["routes"]["HOLD"]["label"] == "Scenario A"
    assert result["paired"]["HOLD__VS__SCENARIO_B__H5"]["p_a_gt_b"] == 0.52


def test_all_eight_formations_are_executed_on_one_six_gw_contract():
    result = run_formation_monte_carlo(
        {"planning_gw": 7},
        current15=list(range(1, 16)),
        input_snapshot_id="private-full-master:gw7",
        route_builder=lambda **_: _routes(),
        simulator=_fake_simulator,
    )

    payload = result["formation_mc"]
    assert payload["horizon"] == {"start_gw": 7, "end_gw": 12, "total_gws": 6}
    assert [row["formation"] for row in payload["formations"]] == list(FORMATIONS)
    assert all(row["actual_paths"] == 500_000 for row in payload["formations"])
    assert all(row["convergence"] == "PASS" for row in payload["formations"])
    assert all(row["p10"] == 80.0 and row["p90"] == 120.0 for row in payload["formations"])
    assert all(row["captain_haul_probability"] == 0.4 for row in payload["formations"])
    assert all(row["captain_blank_probability"] == 0.3 for row in payload["formations"])
    assert all(row["vice_activation_probability"] == 0.2 for row in payload["formations"])
    assert all(row["autosub_probability"] == 0.1 for row in payload["formations"])
    assert all(row["minutes_risk"]["status"] == "MC500K_SAMPLED_DNP_BOUND" for row in payload["formations"])
    assert all(abs(row["minutes_risk"]["mean_p_dnp_xi"] - 0.09) < 1e-12 for row in payload["formations"])
    assert payload["integrity"] == {
        "formation_count": 8,
        "all_legal_formations": True,
        "all_mc_500k": True,
        "all_convergence_pass": True,
        "all_p17_exact": True,
        "all_current15_bound": True,
        "no_legacy_mc": True,
        "no_route_mc_substitution": True,
    }


def test_formation_mc_rejects_missing_formation_without_degrading():
    with pytest.raises(FormationMonteCarloError, match="eight legal formations"):
        run_formation_monte_carlo(
            {"planning_gw": 7},
            current15=list(range(1, 16)),
            input_snapshot_id="private-full-master:gw7",
            route_builder=lambda **_: _routes()[:-1],
            simulator=_fake_simulator,
        )


def test_formation_mc_rejects_non_current15_route():
    routes = _routes()
    routes[0]["per_gw"][0]["starting_xi"][-1] = 999
    with pytest.raises(FormationMonteCarloError, match="CURRENT15"):
        run_formation_monte_carlo(
            {"planning_gw": 7},
            current15=list(range(1, 16)),
            input_snapshot_id="private-full-master:gw7",
            route_builder=lambda **_: routes,
            simulator=_fake_simulator,
        )


def test_formation_mc_renderer_exposes_all_rows_and_route_separation():
    payload = {
        "horizon": {"start_gw": 7, "end_gw": 12},
        "formations": [
            {
                "formation": formation,
                "actual_paths": 500000,
                "convergence": "PASS",
                "xi": list(range(1, 12)),
                "bench": {"gk": 15, "order": [12, 13, 14]},
                "captain": 1,
                "vice_captain": 2,
                "mean_xpts": 10,
                "p10": 1,
                "p50": 10,
                "p90": 20,
                "variance": 2,
                "autosub_probability": 0.1,
                "captain_haul_probability": 0.2,
                "captain_blank_probability": 0.3,
                "vice_activation_probability": 0.4,
                "minutes_risk": {"status": "P1_1_PROJECTION_BOUND"},
            }
            for formation in FORMATIONS
        ],
        "integrity": {
            "formation_count": 8,
            "all_legal_formations": True,
            "all_mc_500k": True,
            "all_convergence_pass": True,
            "all_p17_exact": True,
            "all_current15_bound": True,
            "no_legacy_mc": True,
            "no_route_mc_substitution": True,
        },
    }
    rendered = "\n".join(_formation_mc_lines(payload))
    assert all(formation in rendered for formation in FORMATIONS)
    assert "GW7-GW12" in rendered
    assert "| 500000 |" in rendered
    assert "no_route_mc_substitution=True" in rendered



def test_formation_mc_fails_closed_if_absolute_quantiles_missing():
    def bad_quantiles(projections, route_defs, **kwargs):
        result = _fake_simulator(projections, route_defs, **kwargs)
        for route in result["metrics"].values():
            del route["6"]["p90"]
        return result

    with pytest.raises(FormationMonteCarloError, match="absolute point quantiles missing"):
        run_formation_monte_carlo(
            {"planning_gw": 7},
            current15=list(range(1, 16)),
            input_snapshot_id="private-full-master:gw7",
            route_builder=lambda **_: _routes(),
            simulator=bad_quantiles,
        )


def test_formation_mc_fails_closed_if_sampling_semantics_are_missing():
    def missing_sampled_semantics(projections, route_defs, **kwargs):
        result = _fake_simulator(projections, route_defs, **kwargs)
        result["sampling_diagnostics"]["route_path_semantics"]["HOLD"]["by_gw"].pop("7")
        return result

    with pytest.raises(FormationMonteCarloError, match="six-GW sampling semantics unavailable"):
        run_formation_monte_carlo(
            {"planning_gw": 7},
            current15=list(range(1, 16)),
            input_snapshot_id="private-full-master:gw7",
            route_builder=lambda **_: _routes(),
            simulator=missing_sampled_semantics,
        )


def test_formation_mc_fails_closed_if_a_rate_is_missing():
    def missing_rate(projections, route_defs, **kwargs):
        result = _fake_simulator(projections, route_defs, **kwargs)
        result["sampling_diagnostics"]["route_path_semantics"]["HOLD"]["by_gw"]["7"].pop(
            "captain_haul_probability"
        )
        return result

    with pytest.raises(FormationMonteCarloError, match="captain_haul_probability unavailable"):
        run_formation_monte_carlo(
            {"planning_gw": 7},
            current15=list(range(1, 16)),
            input_snapshot_id="private-full-master:gw7",
            route_builder=lambda **_: _routes(),
            simulator=missing_rate,
        )
