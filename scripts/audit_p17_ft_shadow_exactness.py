from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engines import v12_integrated_report_runner as ir
from src.engines.v12_package_search import search_packages
from src.engines.v12_package_utility import (
    _cumulative_lineup_horizons,
    _materialize_route_lineups,
    _route_squad,
)
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.models.historical_projection import build as build_player_projections
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength
from src.models.v12_analytics_foundation import (
    load_v6_analytics_foundation,
    require_match_foundation,
)

TARGET_ROUTE_IDS = (
    "1:115->474",
    "1:15->69",
    "1:279->93",
    "1:31->60",
    "1:68->155",
    "1:68->591",
)


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _build_inputs(runtime_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    official = ir._official_payload(runtime_root)
    bootstrap = official["bootstrap"]
    fixtures = official["fixtures"]
    planning_gw = ir._planning_gw(bootstrap)
    state = ir._read_json(ir.STATE_PATH, {}) or {}
    personal = ir._personal_evidence_resolution(
        runtime_root,
        state,
        planning_gw=planning_gw,
    )
    owned = ir._owned15(personal, bootstrap)
    strength = build_team_strength(bootstrap, fixtures)
    foundation = require_match_foundation(
        load_v6_analytics_foundation(
            runtime_root,
            bootstrap=bootstrap,
            planning_gw=planning_gw,
            strength=strength or {},
        )
    )
    projections = build_player_projections(
        bootstrap,
        strength or {},
        planning_gw,
        foundation.get("historical_prior") or {},
        player_features_payload=foundation.get("player_features_payload") or {},
        player_match_rows=foundation.get("player_match_rows") or [],
        opponent_history_rows=foundation.get("opponent_history_rows") or [],
        opponent_history_scope=foundation.get("opponent_history_scope"),
    )
    attach_official_role_evidence(projections, bootstrap)
    attach_tactical_role_scores(
        projections,
        planning_gw,
        team_strength=strength or {},
    )
    finance = ir._private_finance_context(personal)
    search = search_packages(
        current_squad=owned,
        candidate_universe=ir._package_candidate_rows(projections),
        bank=finance.get("bank"),
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=None,
        lossy_pruning=False,
        execution_mode="SCALAR",
    )
    return projections, list(search.get("routes") or []), planning_gw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slot", required=True)
    args = parser.parse_args()

    projections, routes, planning_gw = _build_inputs(args.runtime_root)
    route_map = {str(row.get("route_id") or ""): row for row in routes}
    missing = [route_id for route_id in TARGET_ROUTE_IDS if route_id not in route_map]
    if missing:
        raise SystemExit(f"target routes missing from production search: {missing}")

    os.environ["V12_P17_ROUND_DIAGNOSTIC"] = "1"
    lineups, proof = _materialize_route_lineups(
        routes,
        projections,
        planning_gw=planning_gw,
        generated_at=args.slot,
    )
    os.environ.pop("V12_P17_ROUND_DIAGNOSTIC", None)

    rows = []
    for route_id in TARGET_ROUTE_IDS:
        batch = lineups[route_id]
        squad = _route_squad(route_map[route_id])
        scalar = _cumulative_lineup_horizons(
            projections,
            squad,
            planning_gw=planning_gw,
            generated_at=args.slot,
        )
        # Future frontier consumes the second GW row (offset=1).
        batch_next = batch["per_gw"][1]
        scalar_next = scalar["per_gw"][1]
        diag = dict(batch_next.get("_rounding_diagnostic") or {})
        raw = float(diag["route_utility_pre_round"])
        scaled = raw * 1_000_000.0
        rows.append(
            {
                "route_id": route_id,
                "planning_gw": planning_gw,
                "future_gw": int(batch_next["gw"]),
                "pre_round": raw,
                "numpy_round_6": diag.get("numpy_round_6"),
                "python_round_6": diag.get("python_round_6"),
                "scalar_oracle_round_6": scalar_next.get("route_utility"),
                "distance_to_decimal_half": diag.get("distance_to_decimal_half"),
                "spacing_scaled": diag.get("spacing_scaled"),
                "distance_to_half_in_scaled_ulps": (
                    float(diag["distance_to_decimal_half"])
                    / max(float(diag["spacing_scaled"]), 1e-300)
                ),
                "scaled_value": scaled,
                "batch_selected_xi": batch_next.get("starting_xi"),
                "scalar_selected_xi": scalar_next.get("starting_xi"),
                "batch_captain": batch_next.get("captain"),
                "scalar_captain": scalar_next.get("captain"),
                "batch_vice": batch_next.get("vice_captain"),
                "scalar_vice": scalar_next.get("vice_captain"),
            }
        )

    payload = {
        "schema_version": 1,
        "report_slot": args.slot,
        "planning_gw": planning_gw,
        "route_count": len(routes),
        "execution_mode": proof.get("execution_mode"),
        "target_route_ids": list(TARGET_ROUTE_IDS),
        "rows": rows,
    }
    _dump(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
