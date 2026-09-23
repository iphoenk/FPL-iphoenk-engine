from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engines import v12_integrated_report_runner as runner


def _git_sha(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    state = runner._read_json(runner.STATE_PATH, {}) or {}
    official = runner._official_payload(runtime_root)
    bootstrap = official["bootstrap"]
    fixtures = official["fixtures"]
    planning_gw = runner._planning_gw(bootstrap)

    personal = runner._personal_evidence_resolution(
        runtime_root,
        state,
        planning_gw=planning_gw,
    )
    owned = runner._owned15(personal or {}, bootstrap)
    if not owned:
        raise RuntimeError("production snapshot OUR15 unavailable")

    strength = runner.build_team_strength(bootstrap, fixtures)
    foundation = runner.require_match_foundation(
        runner.load_v6_analytics_foundation(
            runtime_root,
            bootstrap=bootstrap,
            planning_gw=planning_gw,
            strength=strength or {},
        )
    )

    projections, stage2_proof = runner.load_or_build_stage2_projections(
        bootstrap=bootstrap,
        strength=strength or {},
        planning_gw=planning_gw,
        historical_prior=foundation.get("historical_prior") or {},
        player_features_payload=(
            foundation.get("player_features_payload") or {}
        ),
        player_match_rows=(
            foundation.get("player_match_rows") or []
        ),
        opponent_history_rows=(
            foundation.get("opponent_history_rows") or []
        ),
        opponent_history_scope=foundation.get(
            "opponent_history_scope"
        ),
        builder=lambda: runner.build_player_projections(
            bootstrap,
            strength or {},
            planning_gw,
            foundation.get("historical_prior") or {},
            player_features_payload=(
                foundation.get("player_features_payload") or {}
            ),
            player_match_rows=(
                foundation.get("player_match_rows") or []
            ),
            opponent_history_rows=(
                foundation.get("opponent_history_rows") or []
            ),
            opponent_history_scope=foundation.get(
                "opponent_history_scope"
            ),
        ),
    )
    runner.attach_official_role_evidence(projections, bootstrap)
    runner.attach_tactical_role_scores(
        projections,
        planning_gw,
        team_strength=strength or {},
    )

    canonical = runner.build_canonical_universe(projections)
    if canonical.get("status") != "COMPLETE":
        raise RuntimeError(
            "production canonical universe incomplete: "
            + str(canonical.get("status"))
        )

    finance = runner._private_finance_context(personal or {})
    candidates = runner._package_candidate_rows(projections)
    search = runner.search_packages(
        current_squad=owned,
        candidate_universe=candidates,
        bank=(finance or {}).get("bank"),
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=None,
        lossy_pruning=False,
        execution_mode="SCALAR",
    )

    prefetch = runner._read_json(
        runtime_root / "data/v6/report_prefetch/latest.json",
        {},
    ) or {}
    generated_at = (
        prefetch.get("generated_at")
        or prefetch.get("logical_slot")
        or prefetch.get("report_slot")
        or "PRODUCTION_SNAPSHOT"
    )
    direct = runner.evaluate_packages(
        search_result=search,
        projections=projections,
        free_transfers=(finance or {}).get("free_transfers"),
        hit_cost_per_extra_transfer=(
            finance or {}
        ).get("hit_cost_per_extra_transfer"),
        future_frontier_by_route=None,
        information_value_by_route={},
        price_risk_by_route={},
        generated_at=str(generated_at),
    )

    execution = dict(
        ((direct.get("governance") or {}).get(
            "p1_7_execution_proof"
        ) or {})
    )
    kernel = dict(execution.get("kernel_proof") or {})
    result: dict[str, Any] = {
        "schema_version": 1,
        "measurement": "PRODUCTION_SNAPSHOT_P1_7_TIE_PREVALENCE",
        "runtime_data_sha": _git_sha(runtime_root),
        "code_sha": _git_sha(runner.ROOT),
        "planning_gw": int(planning_gw),
        "owned_count": len(owned),
        "projection_player_count": len(
            projections.get("players") or []
        ),
        "direct_search_route_count": len(
            search.get("routes") or []
        ),
        "search_route_denominator": search.get(
            "route_denominator"
        ),
        "execution_mode": execution.get("execution_mode"),
        "execution_elapsed_seconds": execution.get(
            "elapsed_seconds"
        ),
        "route_count": execution.get("route_count"),
        "unique_squad_count": execution.get(
            "unique_squad_count"
        ),
        "kernel_proof": kernel,
        "tie_prevalence": {
            "bench_rows_evaluated": kernel.get(
                "bench_rows_evaluated"
            ),
            "bench_primary_tie_count": kernel.get(
                "bench_primary_tie_count"
            ),
            "bench_primary_tie_rate": kernel.get(
                "bench_primary_tie_rate"
            ),
            "bench_primary_boundary_count": kernel.get(
                "bench_primary_boundary_count"
            ),
            "bench_secondary_boundary_count": kernel.get(
                "bench_secondary_boundary_count"
            ),
            "bench_published_boundary_count": kernel.get(
                "bench_published_boundary_count"
            ),
            "bench_scalar_fallback_count": kernel.get(
                "bench_scalar_fallback_count"
            ),
            "bench_scalar_fallback_rate": kernel.get(
                "bench_scalar_fallback_rate"
            ),
            "bench_scalar_fallback_limit_per_family_gw": (
                kernel.get(
                    "bench_scalar_fallback_limit_per_family_gw"
                )
            ),
            "bench_zero_dnp_fast_path_family_gw_count": (
                kernel.get(
                    "bench_zero_dnp_fast_path_family_gw_count"
                )
            ),
        },
        "stage2_cache_proof": stage2_proof,
        "wall_seconds": round(
            time.perf_counter() - started,
            6,
        ),
        "governance": {
            "runtime_data_read_only": True,
            "v6_mutated": False,
            "scheduler_touched": False,
            "funded_routes_started": False,
            "monte_carlo_started": False,
            "report_render_started": False,
            "publish_started": False,
        },
    }
    output.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
