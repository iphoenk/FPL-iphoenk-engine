from __future__ import annotations

"""Deterministic P1.4 canonical >=500k acceptance harness."""

import json

from src.engines.v12_monte_carlo import (
    package_route_definitions,
    run_correlated_monte_carlo,
)
from src.engines.v12_player_events import project_player_fixture


SEED = 14092026
ACTUAL_PATHS = 500_000
INPUT_SNAPSHOT_ID = "P1_4_ACCEPTANCE_FIXTURE_V1"


def _xmins(*, risky: bool = False) -> dict:
    probs = (0.62, 0.16, 0.12, 0.10) if risky else (0.86, 0.06, 0.03, 0.05)
    return {
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "mean": 0.0,
            "std": 0.0,
            "states": [
                {"state": "START", "probability": probs[0], "minutes_mean": 78.0, "minutes_std": 8.0},
                {"state": "REGULAR_CAMEO", "probability": probs[1], "minutes_mean": 24.0, "minutes_std": 7.0},
                {"state": "LATE_CAMEO", "probability": probs[2], "minutes_mean": 9.0, "minutes_std": 4.0},
                {"state": "ZERO_MINUTES", "probability": probs[3], "minutes_mean": 0.0, "minutes_std": 0.0},
            ],
        }
    }


def _rates(position: str, *, upgrade: bool = False) -> dict:
    goal = {"GK": 0.01, "DEF": 0.08, "MID": 0.22, "FWD": 0.38}[position]
    assist = {"GK": 0.01, "DEF": 0.10, "MID": 0.20, "FWD": 0.13}[position]
    if upgrade:
        goal += 0.08
        assist += 0.04
    return {
        "goal": {"posterior_rate90": goal},
        "assist": {"posterior_rate90": assist},
        "bonus": {"posterior_rate90": 0.22 if position in {"GK", "DEF"} else 0.28},
        "saves": {"posterior_rate90": 3.2 if position == "GK" else 0.0, "confidence": "MEDIUM"},
        "defcon": {
            "posterior_count_rate90": 8.0 if position == "DEF" else 5.5 if position == "MID" else 2.0,
            "threshold": 10 if position == "DEF" else 12 if position == "MID" else 0,
            "points": 2.0 if position in {"DEF", "MID"} else 0.0,
            "eligible": position in {"DEF", "MID"},
            "evidence_minutes": 450,
            "sample_quality": "MEDIUM",
            "source": "P1_4_ACCEPTANCE_FIXTURE",
        },
    }


def build_acceptance_fixture() -> tuple[dict, dict]:
    definitions = [
        (1, "GK", 1), (2, "GK", 2),
        (3, "DEF", 1), (4, "DEF", 3), (5, "DEF", 4), (6, "DEF", 5), (7, "DEF", 6),
        (8, "MID", 1), (9, "MID", 2), (10, "MID", 3), (11, "MID", 4), (12, "MID", 5),
        (13, "FWD", 2), (14, "FWD", 3), (15, "FWD", 4),
        (16, "MID", 6),
    ]
    opponents = {1: 2, 2: 1, 3: 4, 4: 3, 5: 6, 6: 5}
    fixture_ids = {1: 1001, 2: 1001, 3: 1002, 4: 1002, 5: 1003, 6: 1003}
    players = []
    for element, position, team_id in definitions:
        element_type = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]
        risky = element == 9
        xmins = _xmins(risky=risky)
        player = {
            "id": element,
            "element": element,
            "name": f"P{element}",
            "position": position,
            "element_type": element_type,
            "team_id": team_id,
            "xmins": xmins,
        }
        fixture = project_player_fixture(
            player,
            xmins,
            {
                "event": 6,
                "fixture": fixture_ids[team_id],
                "opponent": opponents[team_id],
                "team_expected_goals": 1.42 + 0.03 * (team_id % 3),
                "clean_sheet_probability": 0.34 + 0.02 * (team_id % 2),
            },
            home=team_id % 2 == 1,
            rates=_rates(position, upgrade=element == 16),
        )
        player["xpts_by_gw"] = [
            {
                "gw": 6,
                "mean": fixture["mean"],
                "std": fixture["std"],
                "fixtures": [fixture],
            }
        ]
        players.append(player)

    hold_xi = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    change_xi = [1, 3, 4, 5, 8, 16, 10, 11, 12, 13, 14]

    def lineup(xi: list[int]) -> dict:
        return {
            "status": "READY",
            "gw": 6,
            "starting_xi": xi,
            "bench_gk": 2,
            "bench_order": [15, 6, 7],
            "captain": 13,
            "vice_captain": 8,
            "formation": "3-5-2",
        }

    package = {
        "model_owner": "V12_PACKAGE_UTILITY",
        "planning_gw": 6,
        "selected_route_id": "R1",
        "hold_route_id": "HOLD",
        "routes": [
            {
                "route_id": "HOLD",
                "classification": "HOLD",
                "final_squad_elements": list(range(1, 16)),
                "football_route_utility": {"per_gw": [lineup(hold_xi)]},
                "horizons": {"GW+1": {"status": "READY", "net_delta_vs_hold": 0.0}},
                "transfer_economics": {
                    "status": "PASS",
                    "hit_points": 0.0,
                    "future_ft_shadow_value": 0.0,
                },
                "lineup_impact": {},
            },
            {
                "route_id": "R1",
                "classification": "CHANGE",
                "final_squad_elements": [x for x in range(1, 16) if x != 9] + [16],
                "football_route_utility": {"per_gw": [lineup(change_xi)]},
                "horizons": {"GW+1": {"status": "READY", "net_delta_vs_hold": 0.45}},
                "transfer_economics": {
                    "status": "PASS",
                    "hit_points": 0.0,
                    "future_ft_shadow_value": 0.20,
                },
                "lineup_impact": {
                    "captain_changed": False,
                    "vice_changed": False,
                    "bench_order_changed": False,
                },
            },
        ],
    }
    projections = {"planning_gw": 6, "players": players}
    return projections, package


def run_acceptance() -> dict:
    projections, package = build_acceptance_fixture()
    route_defs = package_route_definitions(package, route_ids=["R1"])
    result = run_correlated_monte_carlo(
        projections,
        route_defs,
        actual_paths=ACTUAL_PATHS,
        seed=SEED,
        input_snapshot_id=INPUT_SNAPSHOT_ID,
        canonical=True,
        horizons=(1,),
        selected_route_id="R1",
        generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"acceptance_fixture": "2026-09-20T01:09:04Z"},
    )
    return result


def main() -> int:
    result = run_acceptance()
    summary = {
        "status": result["status"],
        "canonical_pass": result["canonical_pass"],
        "actual_paths": result["actual_paths"],
        "seed": result["seed"],
        "correlation_model_version": result["correlation_model_version"],
        "run_fingerprint": result["run_fingerprint"],
        "output_fingerprint": result["output_fingerprint"],
        "convergence_evidence": result["convergence_evidence"],
        "selected_metrics": result["metrics"]["R1"]["1"],
        "performance": result["performance"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if result["status"] == "PASS" and result["actual_paths"] >= 500_000 else 2


if __name__ == "__main__":
    raise SystemExit(main())
