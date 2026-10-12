from __future__ import annotations

import pytest

from src.engines.v12_formation_monte_carlo import (
    FORMATIONS,
    FormationMonteCarloError,
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
                "Q10": 80.0,
                "Q90": 120.0,
            }
        }
        path_semantics[route_id] = {
            "autosub_path_rate": 0.1,
            "captain_takeover_path_rate": 0.2,
            "captain_blank_probability": 0.3,
            "captain_haul_probability": 0.4,
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
        "performance": {"route_path_semantics": path_semantics},
        "output_fingerprint": "mc-fingerprint",
    }


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

