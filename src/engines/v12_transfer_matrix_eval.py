from __future__ import annotations

"""Private, exact P1.7 transfer what-if evaluator.

Inputs: P1.1/P1.3/P1.6 canonical projection warm state from SAME occurrence
and complete 240-row deterministic legality manifest. Does not call the
production publisher, alter CURRENT15, or fabricate scenario P1.4 simulations.
The separate 500K scenario MC remains REQUIRED but NOT_EXECUTED until supported.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from src.engines.v12_transfer_matrix import INPUT_PATH, build_matrix


class TransferMatrixEvaluationError(RuntimeError):
    pass


def evaluate_private_matrix(
    config: Mapping[str, Any],
    warm: Mapping[str, Any],
    *,
    optimizer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if warm.get("schema") != "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1":
        raise TransferMatrixEvaluationError("canonical private warm state required")
    if int(warm.get("planning_gw") or 0) != int(config.get("target_gw") or 0):
        raise TransferMatrixEvaluationError("GW identity mismatch")
    if str(warm.get("report_slot") or "") != str(config["baseline"]["slot"]):
        raise TransferMatrixEvaluationError("occurrence slot mismatch")
    owned = sorted(int(row["element_id"]) for row in config["owned"])
    actual_owned = sorted(
        int(row.get("element_id") or row.get("element") or 0)
        for row in warm.get("owned") or []
    )
    if actual_owned != owned:
        raise TransferMatrixEvaluationError("private OUR15 identity mismatch")
    projections = warm.get("projections")
    if not isinstance(projections, Mapping):
        raise TransferMatrixEvaluationError("missing canonical projections")
    required_ids = set(owned)
    required_ids.update(int(row["element_id"]) for row in config["candidates"])
    projection_ids = {
        int(row.get("element") or row.get("id") or 0)
        for row in projections.get("players") or []
        if isinstance(row, Mapping)
    }
    if not required_ids <= projection_ids:
        raise TransferMatrixEvaluationError("projection surface misses scenario candidates")
    if optimizer is None:
        from src.engines.v12_lineup_optimizer import optimize_lineup
        optimizer = optimize_lineup

    result = build_matrix(config)
    expected_baseline = {
        str(name): float(value)
        for name, value in config["baseline"]["canonical_formations"]
    }
    formations = set(expected_baseline)
    materialized: dict[str, dict[str, Any]] = {}
    for case in result["scenarios"]:
        if case["status"] != "STRUCTURAL_PASS_FINANCE_UNVERIFIED":
            continue
        case_id = case["scenario_id"]
        scenario = optimizer(
            projections,
            sorted(int(element) for element in case["squad_element_ids"]),
            planning_gw=int(config["target_gw"]),
        )
        formation_rows = [
            dict(row) for row in scenario.get("formation_comparison") or []
            if isinstance(row, Mapping)
        ]
        row_map = {str(row.get("formation")): row for row in formation_rows}
        if set(row_map) != formations or len(formation_rows) != 8:
            raise TransferMatrixEvaluationError(f"incomplete P1.7 formations for {case_id}")
        for formation, row in row_map.items():
            score = row.get("expected_fpl_points_with_captain_vice")
            if not isinstance(score, (int, float)):
                raise TransferMatrixEvaluationError(f"missing P1.7 score for {case_id}:{formation}")
            if not case["out_in"] and abs(float(score) - expected_baseline[formation]) > 0.002:
                raise TransferMatrixEvaluationError(
                    f"baseline P1.7 drift: {formation} expected={expected_baseline[formation]} got={score}"
                )
        materialized[case_id] = {
            "best_formation": scenario.get("formation"),
            "captain": scenario.get("captain"),
            "vice_captain": scenario.get("vice_captain"),
            "formation_comparison": formation_rows,
            "legal_formations_evaluated": scenario.get("legal_formations_evaluated"),
            "canonical_p17": True,
            "scenario_mc_state": "NOT_EXECUTED",
        }
    for row in result["formation_matrix"]:
        case_id = row["scenario_id"]
        computed = materialized.get(case_id)
        if computed is None:
            continue
        matches = [
            x for x in computed["formation_comparison"]
            if str(x.get("formation")) == row["formation"]
        ]
        if len(matches) != 1:
            raise TransferMatrixEvaluationError("non-unique P1.7 row")
        row["captain_adjusted_xpts"] = float(
            matches[0]["expected_fpl_points_with_captain_vice"]
        )
        row["points_authority"] = "P1_7_CANONICAL_FULL_ROUTE_WHAT_IF"
        # MC is never propagated from the base to a changed squad.
        if case_id != result["scenarios"][0]["scenario_id"]:
            row["mc_500k_status"] = "NOT_EXECUTED"
            row["mc_paths_for_this_squad"] = None
    result["p17_exact_scenarios"] = materialized
    result["coverage"]["p17_exact_rosters"] = len(materialized)
    result["coverage"]["p17_exact_formation_rows"] = len(materialized) * 8
    result["canonical_monte_carlo_for_transfer_rosters"] = False
    result["never_publish_as_current15"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_PATH))
    parser.add_argument("--warm-state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.input).read_text(encoding="utf-8"))
    warm = json.loads(Path(args.warm_state).read_text(encoding="utf-8"))
    result = evaluate_private_matrix(config, warm)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
