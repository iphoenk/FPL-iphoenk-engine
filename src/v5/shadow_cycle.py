from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import atomic_json, read_json
from src.v5.config_cache import load_json_config
from src.v5.evaluation.shadow_parity import compare
from src.v5.official_auth import expected_team_id
from src.v5.release_integrity import runtime_fingerprint
from src.v5.services.orchestrator_beta import handle as beta_handle

MANIFEST_CONFIG = "config/v5_convergence_manifest.json"
PERFORMANCE_CONFIG = "config/v5_performance_budgets.json"


def _read_object(path: str) -> dict[str, Any]:
    data = read_json(Path(path), None)
    if not isinstance(data, dict):
        raise RuntimeError(f"expected object in {path}")
    return data


def _ids(rows: Any) -> set[int]:
    return {int(row["element"]) for row in (rows or []) if isinstance(row, dict) and row.get("element") is not None}


def run(v3_latest_path: str, v3_lineup_path: str, output_dir: str, team_id: int) -> dict[str, Any]:
    v3_latest = _read_object(v3_latest_path)
    v3_lineup = _read_object(v3_lineup_path)
    v3_reference = {**v3_latest, **v3_lineup}
    manifest = load_json_config(MANIFEST_CONFIG)
    baselines = manifest.get("baselines") if isinstance(manifest.get("baselines"), dict) else {}
    release = runtime_fingerprint()

    v5 = beta_handle("run", {"mode": "daily", "team_id": team_id, "persist": True})
    if not isinstance(v5, dict):
        raise RuntimeError("V5 beta refresh orchestrator returned a non-object")
    hot = beta_handle("hot_run", {"mode": "daily", "team_id": team_id})
    if not isinstance(hot, dict):
        raise RuntimeError("V5 beta hot orchestrator returned a non-object")
    if not v5.get("ruleset_id"):
        v5["ruleset_id"] = ((v5.get("prediction_summary") or {}).get("ruleset_id"))

    parity = compare(v3_reference, v5)
    generated_at = datetime.now(timezone.utc).isoformat()
    cycle_id = generated_at.replace(":", "").replace("+00:00", "Z").replace("-", "")
    v5_team = v5.get("team_summary") if isinstance(v5.get("team_summary"), dict) else {}
    owned_ids = [int(x) for x in (v5_team.get("owned_ids") or [])]
    decision = v5.get("decision_summary") if isinstance(v5.get("decision_summary"), dict) else {}
    lineup = decision.get("lineup") if isinstance(decision.get("lineup"), dict) else {}
    lineup_ids = _ids(lineup.get("starters")) | _ids(lineup.get("bench"))
    watch = v5.get("watchlist_summary") if isinstance(v5.get("watchlist_summary"), dict) else {}

    perf_cfg = load_json_config(PERFORMANCE_CONFIG)
    budgets = perf_cfg.get("budgets") if isinstance(perf_cfg.get("budgets"), dict) else {}
    refresh_perf = v5.get("service_performance") if isinstance(v5.get("service_performance"), dict) else {}
    hot_perf = hot.get("service_performance") if isinstance(hot.get("service_performance"), dict) else {}
    refresh_wall_ms = float(refresh_perf.get("full_beta_end_to_end_ms") or 0.0)
    hot_wall_ms = float(hot_perf.get("hot_path_wall_ms") or 0.0)
    hot_hard_ms = float(budgets.get("hot_path_hard_limit_seconds") or 0.0) * 1000.0
    refresh_observability_ceiling_ms = float(budgets.get("refresh_pipeline_observability_ceiling_seconds") or 0.0) * 1000.0
    hot_runtime_pass = hot_wall_ms > 0.0 and hot_hard_ms > 0.0 and hot_wall_ms <= hot_hard_ms
    freshness = ((hot.get("governance") or {}).get("freshness") or {})

    invariants = {
        "owned_exactly_15": len(owned_ids) == 15 and len(set(owned_ids)) == 15,
        "lineup_confined_to_owned": len(lineup_ids) == 15 and lineup_ids == set(owned_ids),
        "watchlist_exactly_20": int(watch.get("candidate_count") or 0) == 20,
        "user_lock_authority_pre_deadline": str((v5.get("phase") or {}).get("phase") or "") != "PRE_DEADLINE" or str(v5.get("squad_authority") or "") == "user_lock",
        "refresh_pipeline_telemetry_present": refresh_wall_ms > 0.0,
        "hot_materialization_fresh": bool(freshness.get("eligible")),
        "hot_path_under_one_second": hot_runtime_pass,
        "hot_path_no_hidden_sync_refresh": bool((hot.get("governance") or {}).get("hidden_synchronous_refresh") is False),
    }
    invariant_pass = all(invariants.values())
    cycle_pass = bool(parity.get("pass")) and invariant_pass
    post_status = "PENDING" if cycle_pass else "NOT_ELIGIBLE"

    result = {
        "schema_version": 7,
        "cycle_id": cycle_id,
        "generated_at": generated_at,
        "mode": "REAL_SHADOW",
        "production_remains_v3": True,
        "acceptance_context": {
            "production_baseline_version": baselines.get("production_truth"),
            "production_main_sha": baselines.get("production_main_sha"),
            "v5_version": v5.get("engine_version"),
            "release_fingerprint": release["fingerprint"],
            "release_fingerprint_contract": release["contract"],
            "release_fingerprint_files": release["files_hashed"],
            "runtime_requirement": {
                "hot_path_hard_limit_ms": hot_hard_ms,
                "refresh_pipeline_observability_ceiling_ms": refresh_observability_ceiling_ms,
                "must_be_below_one_second": True,
                "release_blocking_plane": "hot",
                "refresh_latency_release_blocking": False,
            },
        },
        "post_validation": {"status": post_status, "validated_at": None, "validator_contract": "V5_REAL_SHADOW_POSTVALIDATION_V5"},
        "v3": {"engine_version": v3_latest.get("engine_version"), "generated_at": v3_latest.get("generated_at"), "planning_gw": (v3_latest.get("phase") or {}).get("planning_gw"), "formation": v3_lineup.get("formation"), "starting_xi": v3_lineup.get("starting_xi") or [], "captain": v3_lineup.get("captain"), "vice_captain": v3_lineup.get("vice_captain"), "ruleset_id": v3_lineup.get("ruleset_id"), "squad_authority": v3_lineup.get("squad_authority")},
        "v5": {"engine_version": v5.get("engine_version"), "release_fingerprint": release["fingerprint"], "runner_status": v5.get("runner_status"), "planning_gw": (v5.get("phase") or {}).get("planning_gw"), "phase": (v5.get("phase") or {}).get("phase"), "squad_authority": v5.get("squad_authority"), "owned_count": len(owned_ids), "owned_ids": owned_ids, "decision": decision, "watchlist": watch, "user_report": v5.get("user_report") or {}, "source_fusion_health": v5.get("source_fusion_health") or {}, "governance": v5.get("governance") or {}, "framework_health": v5.get("framework_health") or {}, "service_performance": refresh_perf, "authenticated_official": v5.get("authenticated_official") or {}, "hot_path": hot},
        "parity": parity,
        "operational_invariants": {"pass": invariant_pass, "checks": invariants},
        "runtime_performance": {
            "refresh_pipeline_wall_ms": refresh_wall_ms,
            "refresh_pipeline_observability_ceiling_ms": refresh_observability_ceiling_ms,
            "refresh_within_observability_ceiling": bool(refresh_wall_ms > 0.0 and (refresh_observability_ceiling_ms <= 0.0 or refresh_wall_ms <= refresh_observability_ceiling_ms)),
            "refresh_latency_release_blocking": False,
            "hot_path_wall_ms": hot_wall_ms,
            "hot_path_hard_limit_ms": hot_hard_ms,
            "hot_path_pass": hot_runtime_pass,
            "hot_materialization_freshness": freshness,
        },
        "acceptance_progress": {"cycle_pass": cycle_pass, "required_real_cycles": int(parity.get("required_real_cycles") or 3), "real_cycle_recorded": True, "post_validation_required": True, "post_validation_status": post_status, "counts_as_successful_acceptance_cycle": False, "production_candidate_auto_promoted": False},
    }
    out = Path(output_dir)
    cycle_path = out / "cycles" / f"{cycle_id}.json"
    atomic_json(cycle_path, result)
    atomic_json(out / "latest_shadow_cycle.json", result)
    print(json.dumps({"cycle_id": cycle_id, "cycle_pass": cycle_pass, "post_validation_status": post_status, "parity_pass": parity.get("pass"), "refresh_pipeline_wall_ms": refresh_wall_ms, "hot_path_wall_ms": hot_wall_ms, "release_fingerprint": release["fingerprint"], "output": str(cycle_path)}, ensure_ascii=False))
    return result


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run one real V3/V5 shadow cycle without promoting V5")
    parser.add_argument("--v3-latest", default=".shadow/v3_latest.json")
    parser.add_argument("--v3-lineup", default=".shadow/v3_lineup_decision.json")
    parser.add_argument("--output-dir", default="data/v5/shadow")
    parser.add_argument("--team-id", type=int, default=int(os.getenv("FPL_TEAM_ID") or expected_team_id()))
    args = parser.parse_args()
    run(args.v3_latest, args.v3_lineup, args.output_dir, args.team_id)


if __name__ == "__main__":
    cli()
