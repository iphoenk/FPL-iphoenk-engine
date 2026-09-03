from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any

from src.engines import package_optimizer_exhaustive_accelerated as accelerated
from src.engines import package_optimizer_exhaustive_finalize as base
from src.models.package_optimizer_v2 import (
    CompiledPackageScorer,
    _scoring_context,
    load_config as load_optimizer_config,
    simulate_objective,
)
from src.rules import RULESET_ID
from src.runtime_v3.full_authority_cache import EXHAUSTIVE_PROFILE, optimizer_input_fingerprint
from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

POLICY_PATH = ROOT / "config" / "runtime" / "package_optimizer_sharding.json"
SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"
PLAN_REGISTRY = "V3_PACKAGE_OPTIMIZER_SHARD_PLAN_V1"
SHARD_REGISTRY = "V3_PACKAGE_OPTIMIZER_SHARD_RESULT_V1"


def load_policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_PACKAGE_OPTIMIZER_SHARDING_V1":
        raise RuntimeError("unexpected package optimizer sharding registry")
    planner = payload.get("planner") or {}
    required_positive = (
        "target_pair_combinations_per_shard",
        "min_shards",
        "max_shards",
        "batch_size",
        "top_keep_per_shard",
    )
    if any(int(planner.get(key) or 0) <= 0 for key in required_positive):
        raise RuntimeError("package optimizer sharding planner contains non-positive settings")
    if int(planner["min_shards"]) > int(planner["max_shards"]):
        raise RuntimeError("package optimizer sharding min_shards exceeds max_shards")
    if payload.get("execution_only") is not True or payload.get("authority_owner") != "prediction":
        raise RuntimeError("package optimizer sharding may not become business authority")
    return payload


def _material() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]], int, dict[str, Any]]:
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    if not projections or not team:
        raise RuntimeError("sharded optimizer requires projections.json and team.json")
    cfg = load_optimizer_config()
    gw = int(projections.get("planning_gw") or 1)
    context = _scoring_context(cfg, gw)
    context["planning_gw"] = gw
    current = base._current(projections, team)
    owned = {int(row["element"]) for row in current}
    pool, universe_counts = base._pool(projections, owned, cfg)
    itb = int((team.get("totals") or {}).get("itb") or 0)
    return projections, team, cfg, current, pool, itb, {"context": context, "universe_counts": universe_counts}


def _task_weight(task: tuple[int, int], current: list[dict[str, Any]], pool: dict[str, list[dict[str, Any]]]) -> int:
    left, right = task
    pos_left = str(current[left].get("position"))
    pos_right = str(current[right].get("position"))
    if pos_left == pos_right:
        size = len(pool[pos_left])
        return size * max(0, size - 1) // 2
    return len(pool[pos_left]) * len(pool[pos_right])


def build_plan() -> dict[str, Any]:
    policy = load_policy()
    planner = policy["planner"]
    projections, _, _, current, pool, _, extra = _material()
    tasks = [(i, j) for i, j in combinations(range(len(current)), 2)]
    weighted = [(task, _task_weight(task, current, pool)) for task in tasks]
    total_weight = sum(weight for _, weight in weighted)
    target = int(planner["target_pair_combinations_per_shard"])
    desired = max(1, int(math.ceil(total_weight / max(1, target))))
    shard_count = min(int(planner["max_shards"]), max(int(planner["min_shards"]), desired))
    shard_count = min(shard_count, max(1, len(tasks)))

    bins: list[dict[str, Any]] = [
        {"shard_id": index, "estimated_pair_combinations": 0, "tasks": []}
        for index in range(shard_count)
    ]
    for task, weight in sorted(weighted, key=lambda row: (-row[1], row[0])):
        target_bin = min(bins, key=lambda row: (int(row["estimated_pair_combinations"]), int(row["shard_id"])))
        target_bin["tasks"].append(list(task))
        target_bin["estimated_pair_combinations"] += int(weight)

    covered = [tuple(task) for shard in bins for task in shard["tasks"]]
    if len(covered) != len(tasks) or set(covered) != set(tasks) or len(set(covered)) != len(covered):
        raise RuntimeError("shard planner failed exact outgoing-pair task coverage")

    loads = [int(shard["estimated_pair_combinations"]) for shard in bins]
    fingerprint = optimizer_input_fingerprint()
    return {
        "schema_version": 1,
        "registry": PLAN_REGISTRY,
        "generated_at": iso_now(),
        "workflow_started_at": iso_now(),
        "profile": EXHAUSTIVE_PROFILE,
        "planning_gw": int(projections.get("planning_gw") or 1),
        "ruleset_id": RULESET_ID,
        "optimizer_input_fingerprint": fingerprint,
        "optimizer_input_fingerprint_prefix": fingerprint[:12],
        "strategy": planner["strategy"],
        "shard_count": shard_count,
        "task_count": len(tasks),
        "estimated_pair_combinations": total_weight,
        "target_pair_combinations_per_shard": target,
        "load_balance": {
            "min": min(loads, default=0),
            "max": max(loads, default=0),
            "mean": round(sum(loads) / max(1, len(loads)), 3),
            "max_to_mean_ratio": round(max(loads, default=0) / max(1.0, sum(loads) / max(1, len(loads))), 4),
        },
        "batch_size": int(planner["batch_size"]),
        "top_keep_per_shard": int(planner["top_keep_per_shard"]),
        "shards": bins,
        "matrix": {"shard_id": [int(shard["shard_id"]) for shard in bins]},
        "universe": extra["universe_counts"],
        "governance": {
            "execution_only": True,
            "complete_pair_task_cover": True,
            "candidate_pruning": False,
            "business_authority_sharded": False,
            "watchlist_input": False,
        },
    }


def _plan_shard(plan: dict[str, Any], shard_id: int) -> dict[str, Any]:
    if plan.get("registry") != PLAN_REGISTRY:
        raise RuntimeError("invalid package optimizer shard plan")
    match = next((row for row in plan.get("shards") or [] if int(row.get("shard_id")) == int(shard_id)), None)
    if not isinstance(match, dict):
        raise RuntimeError(f"unknown shard_id={shard_id}")
    return match


def run_shard(plan: dict[str, Any], shard_id: int) -> dict[str, Any]:
    policy = load_policy()
    planner = policy["planner"]
    shard = _plan_shard(plan, shard_id)
    projections, _, _, current, pool, itb, extra = _material()
    current_fingerprint = optimizer_input_fingerprint()
    if current_fingerprint != str(plan.get("optimizer_input_fingerprint") or ""):
        raise RuntimeError("shard input fingerprint differs from plan")

    context = extra["context"]
    scalar = CompiledPackageScorer(projections.get("players") or [], int(projections.get("planning_gw") or 1), scoring_context=context)
    hold_score = scalar.score(current, changes=0)
    hold_h = hold_score.get("horizons") or {}
    keep = int(planner["top_keep_per_shard"])

    previous_batch_size = accelerated.BATCH_SIZE
    try:
        accelerated.BATCH_SIZE = int(planner["batch_size"])
        accelerated._init_worker(projections.get("players") or [], current, pool, itb, context, keep, hold_h)
        totals = Counter()
        top_heap: list[tuple[float, str, dict[str, Any]]] = []
        frontier = base._Frontier(hold_h)
        tasks = [tuple(int(value) for value in task) for task in shard.get("tasks") or []]
        for task in tasks:
            result = accelerated._pair_partition(task)
            for key in (
                "pair_candidate_combinations",
                "pair_structural_cash_rejected",
                "pair_structural_club_rejected",
                "pair_step_legal",
                "pair_candidates_exact_scored",
                "batch_scalar_fallback_count",
            ):
                totals[key] += int(result.get(key) or 0)
            for package in result.get("top") or []:
                base._push(top_heap, package, keep)
            for package in result.get("frontier") or []:
                frontier.add(package)
    finally:
        accelerated.BATCH_SIZE = previous_batch_size

    output = {
        "schema_version": 1,
        "registry": SHARD_REGISTRY,
        "generated_at": iso_now(),
        "shard_id": int(shard_id),
        "task_count": len(tasks),
        "tasks": [list(task) for task in tasks],
        "estimated_pair_combinations": int(shard.get("estimated_pair_combinations") or 0),
        "optimizer_input_fingerprint": current_fingerprint,
        "batch_size": int(planner["batch_size"]),
        "top_keep": keep,
        "counters": dict(totals),
        "top": [row[2] for row in top_heap],
        "frontier": [package for _, package in frontier.rows],
        "governance": {
            "execution_only": True,
            "writes_package_optimizer": False,
            "writes_package_decision": False,
            "candidate_pruning": False,
            "canonical_equivalent_batch_kernel": True,
        },
    }
    return output


def _load_shards(plan: dict[str, Any], shard_dir: Path) -> list[dict[str, Any]]:
    expected_ids = {int(row.get("shard_id")) for row in plan.get("shards") or []}
    rows: list[dict[str, Any]] = []
    for path in sorted(shard_dir.glob("shard-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("registry") != SHARD_REGISTRY:
            raise RuntimeError(f"invalid shard result registry: {path}")
        rows.append(payload)
    actual_ids = [int(row.get("shard_id")) for row in rows]
    if set(actual_ids) != expected_ids or len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError(f"incomplete/duplicate shard result set expected={sorted(expected_ids)} actual={sorted(actual_ids)}")
    return sorted(rows, key=lambda row: int(row["shard_id"]))


def reduce_shards(plan: dict[str, Any], shard_dir: Path, *, persist: bool = True) -> dict[str, Any]:
    policy = load_policy()
    projections, team, cfg, current, pool, itb, extra = _material()
    current_fingerprint = optimizer_input_fingerprint()
    if current_fingerprint != str(plan.get("optimizer_input_fingerprint") or ""):
        raise RuntimeError("reducer input fingerprint differs from shard plan")
    shards = _load_shards(plan, shard_dir)

    expected_tasks = {
        tuple(int(value) for value in task)
        for shard in plan.get("shards") or []
        for task in shard.get("tasks") or []
    }
    actual_tasks = [
        tuple(int(value) for value in task)
        for shard in shards
        for task in shard.get("tasks") or []
    ]
    if len(actual_tasks) != len(set(actual_tasks)) or set(actual_tasks) != expected_tasks:
        raise RuntimeError("shard reducer refuses missing or duplicate outgoing-pair task coverage")
    if any(str(row.get("optimizer_input_fingerprint") or "") != current_fingerprint for row in shards):
        raise RuntimeError("shard reducer refuses mixed optimizer input fingerprints")

    started = time.perf_counter()
    context = extra["context"]
    gw = int(projections.get("planning_gw") or 1)
    scalar = CompiledPackageScorer(projections.get("players") or [], gw, scoring_context=context)
    clubs = Counter(int(row.get("team_id") or -1) for row in current)
    hold_score = scalar.score(current, changes=0)
    hold = base._record(0, [], [], hold_score, {"resulting_itb": itb, "steps": [], "execution_order": [], "orders_checked": 1}, itb)
    hold_h = hold_score.get("horizons") or {}
    keep = int(policy["planner"]["top_keep_per_shard"])
    heap: list[tuple[float, str, dict[str, Any]]] = [(base._f(hold_score.get("robust_score")), "HOLD", hold)]
    frontier = base._Frontier.from_hold(hold)
    frontier.add(hold)

    single_considered = single_legal = single_scored = single_cash = single_club = 0
    for outgoing in current:
        residual = [row for row in current if int(row["element"]) != int(outgoing["element"])]
        for incoming in pool[str(outgoing.get("position"))]:
            single_considered += 1
            structural, reason = base._structural_ok(clubs, [outgoing], [incoming], itb)
            if not structural:
                single_cash += int(reason == "cash")
                single_club += int(reason == "club")
                continue
            legal, sequence = base._fast_step_sequence(current, clubs, [outgoing], [incoming], itb)
            if not legal:
                continue
            single_legal += 1
            package = base._record(1, [outgoing], [incoming], {}, sequence, itb)
            single_scored += base._collect(package, residual + [incoming], 1, scalar, heap, frontier, keep)

    pair_totals = Counter()
    for shard in shards:
        for key, value in (shard.get("counters") or {}).items():
            pair_totals[str(key)] += int(value or 0)
        for package in shard.get("top") or []:
            base._push(heap, package, keep)
        for package in shard.get("frontier") or []:
            frontier.add(package)

    pair_legal = int(pair_totals["pair_step_legal"])
    pair_scored = int(pair_totals["pair_candidates_exact_scored"])
    evaluated = 1 + single_scored + pair_scored
    top = [row[2] for row in heap]
    accelerated._rehydrate_top_scores(top, current, pool, scalar)
    top.sort(key=lambda package: (base._f((package.get("score") or {}).get("robust_score")), str(package.get("id") or "")), reverse=True)

    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    hold_mean = base._f(hold_score.get("objective_mean"))
    hold_std = base._f(hold_score.get("objective_std"))
    for index, package in enumerate(top[:mc_top]):
        score = package.get("score") or {}
        mean = base._f(score.get("objective_mean"))
        std = base._f(score.get("objective_std"))
        mc = simulate_objective(mean, std, int(cfg.get("monte_carlo_simulations") or 300), int(cfg.get("monte_carlo_seed") or 1) + index)
        diff_std = math.sqrt(std * std + hold_std * hold_std)
        mc["p_outperform_hold_independent_baseline"] = round(1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0), 4) if diff_std > 0 else (1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0)
        package["monte_carlo"] = mc

    preview_n = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    preview = {
        position: [
            {"element": row["element"], "name": row.get("name"), "now_cost": row.get("now_cost"), "candidate_score": round(base._f(row.get("candidate_score")), 3)}
            for row in rows[:preview_n]
        ]
        for position, rows in pool.items()
    }
    frontier_out = frontier.output(int((cfg.get("frontier") or {}).get("publish_limit") or 20), evaluated)
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    eligible = {position: len(rows) for position, rows in pool.items()}
    scalar_fallbacks = int(pair_totals["batch_scalar_fallback_count"])

    diagnostics = {
        **extra["universe_counts"],
        "candidate_origin": "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE",
        "eligible_universe_count": sum(eligible.values()),
        "eligible_by_position": eligible,
        "search_method": "ZERO_CANDIDATE_PRUNING_EXHAUSTIVE_SEQUENTIAL_EXACT_V3_CROSS_RUNNER_SHARDED_BATCH",
        "candidate_pruning_applied": False,
        "candidate_pruned_count": 0,
        "fixed_top_n_per_position_applied": False,
        "fixed_top_n_per_outgoing_applied": False,
        "watchlist_used_as_optimizer_input": False,
        "single_candidates_considered": single_considered,
        "single_structural_cash_rejected": single_cash,
        "single_structural_club_rejected": single_club,
        "single_step_legal": single_legal,
        "single_exact_scored": single_scored,
        "single_budget_applied": False,
        "pair_generation_origin": "DIRECT_OUTGOING_PAIR_X_COMPLETE_POSITION_ELIGIBLE_INCOMING_POOLS",
        "pair_requires_single_move_seed": False,
        "pair_candidate_combinations": int(pair_totals["pair_candidate_combinations"]),
        "pair_structural_cash_rejected": int(pair_totals["pair_structural_cash_rejected"]),
        "pair_structural_club_rejected": int(pair_totals["pair_structural_club_rejected"]),
        "pair_step_legal": pair_legal,
        "pair_candidates_exact_scored": pair_scored,
        "pair_budget_applied": False,
        "exact_package_limit_applied": False,
        "all_step_legal_packages_scored": single_scored == single_legal and pair_scored == pair_legal,
        "lossy_pruning": False,
        "search_authority": "FULL",
        "compiled_exact_kernel": True,
        "guarded_batch_acceleration": True,
        "batch_size": int(policy["planner"]["batch_size"]),
        "batch_scalar_fallback_count": scalar_fallbacks,
        "batch_scalar_fallback_rate": round(scalar_fallbacks / max(1, pair_scored), 6),
        "cross_runner_sharding": True,
        "shard_registry": policy["registry"],
        "shard_count": len(shards),
        "shard_task_count": len(actual_tasks),
        "shard_complete_task_cover": set(actual_tasks) == expected_tasks,
        "shard_duplicate_tasks": len(actual_tasks) != len(set(actual_tasks)),
        "shard_input_fingerprint_prefix": current_fingerprint[:12],
        "shard_partition_is_execution_only": True,
        "shard_partition_changes_search_space": False,
        "local_frontier_reduction_exact": True,
        "global_frontier_from_exact_local_frontier_union": True,
        "top_packages_canonical_scalar_rehydrated": True,
        "authority_reason": "complete eligible Official FPL universe; zero candidate pruning; deterministic complete outgoing-pair sharding; every sequentially legal package scored by canonical-equivalent guarded batch kernel; one exact reducer owns final FULL optimizer",
        "optimizer_runtime_status_separate_from_search_authority": True,
        "finalizer_elapsed_ms": elapsed,
    }
    optimizer = {
        "generated_at": iso_now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": preview,
        "candidate_pool_is_preview_only": True,
        "package_count": evaluated,
        "hold": hold,
        "packages": top[:mc_top],
        "efficient_frontier": frontier_out,
        "search_diagnostics": diagnostics,
        "governance": {
            "candidate_generation_only": True,
            "production_owner": "prediction",
            "package_decision_writer": "lineup_governance",
            "execution_profile": EXHAUSTIVE_PROFILE,
            "authority_execution_profile": EXHAUSTIVE_PROFILE,
            "exhaustive_precompute": True,
            "cross_runner_sharded_execution": True,
            "shards_are_not_business_authority": True,
            "single_final_optimizer_writer": True,
            "prediction_scoring_semantics_unchanged": True,
            "candidate_pruning_for_full_authority": False,
            "watchlist_is_output_only": True,
            "pair_search_not_seeded_by_single_legality": True,
            "step_legal_transfer_recomputation": True,
            "efficient_frontier_from_all_evaluated_legal_packages": True,
            "lossy_pruning_is_explicit": False,
        },
    }
    if optimizer["status"] != "READY" or diagnostics["search_authority"] != "FULL" or diagnostics["all_step_legal_packages_scored"] is not True:
        raise RuntimeError("shard reducer did not produce truthful FULL optimizer")

    if persist:
        atomic_json(DATA / "package_optimizer.json", optimizer)
        latest = read_json(DATA / "latest.json", {})
        latest.setdefault("files", {})["package_optimizer"] = "data/package_optimizer.json"
        intelligence = latest.setdefault("decision_intelligence", {})
        intelligence.update({
            "package_optimizer_status": "READY",
            "package_count": optimizer.get("package_count"),
            "package_optimizer_search_authority": "FULL",
            "package_optimizer_execution_profile": EXHAUSTIVE_PROFILE,
            "package_optimizer_runtime_profile": EXHAUSTIVE_PROFILE,
            "package_optimizer_exact_full_reuse": False,
            "package_optimizer_sharded_execution": True,
            "best_package": (optimizer.get("packages") or [{}])[0].get("id") if optimizer.get("packages") else None,
        })
        latest["package_optimizer_shard_summary"] = {
            "registry": policy["registry"],
            "shard_count": len(shards),
            "task_count": len(actual_tasks),
            "complete_task_cover": True,
            "duplicate_tasks": False,
            "input_fingerprint_prefix": current_fingerprint[:12],
            "search_authority": "FULL",
        }
        atomic_json(DATA / "latest.json", latest)
    return optimizer


def finalize_runtime_performance(plan: dict[str, Any]) -> dict[str, Any]:
    started_text = str(plan.get("workflow_started_at") or "")
    try:
        started = datetime.fromisoformat(started_text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("shard plan workflow_started_at invalid") from exc
    elapsed_ms = max(0.0, (datetime.now(timezone.utc) - started).total_seconds() * 1000.0)
    slo_payload = json.loads(SLO_PATH.read_text(encoding="utf-8"))
    slo = (slo_payload.get("profiles") or {}).get(EXHAUSTIVE_PROFILE) or {}
    target_ms = float(slo.get("target_wall_ms") or 0)
    warning_ms = float(slo.get("warning_wall_ms") or target_ms)
    ceiling_ms = float(slo.get("legacy_ceiling_ms") or target_ms)
    performance = read_json(DATA / "runtime_performance.json", {})
    performance.update({
        "execution_profile": EXHAUSTIVE_PROFILE,
        "total_wall_ms": round(elapsed_ms, 3),
        "target_wall_ms": target_ms,
        "warning_wall_ms": warning_ms,
        "legacy_ceiling_ms": ceiling_ms,
        "within_target_slo": elapsed_ms <= target_ms if target_ms else None,
        "within_warning_slo": elapsed_ms <= warning_ms if warning_ms else None,
        "within_legacy_ceiling": elapsed_ms <= ceiling_ms if ceiling_ms else None,
        "performance_budget_ms": ceiling_ms,
        "within_target_budget": elapsed_ms <= ceiling_ms if ceiling_ms else None,
        "sharded_precompute": {
            "registry": PLAN_REGISTRY,
            "shard_policy_registry": load_policy()["registry"],
            "shard_count": int(plan.get("shard_count") or 0),
            "task_count": int(plan.get("task_count") or 0),
            "estimated_pair_combinations": int(plan.get("estimated_pair_combinations") or 0),
            "load_balance": plan.get("load_balance"),
            "optimizer_input_fingerprint_prefix": str(plan.get("optimizer_input_fingerprint_prefix") or ""),
            "cross_runner": True,
            "single_business_authority": True,
        },
    })
    atomic_json(DATA / "runtime_performance.json", performance)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("runtime_architecture", {}).update({
        "execution_profile": EXHAUSTIVE_PROFILE,
        "total_wall_ms": round(elapsed_ms, 3),
        "within_target_slo": performance["within_target_slo"],
        "within_target_budget": performance["within_target_budget"],
        "package_optimizer_cross_runner_shards": int(plan.get("shard_count") or 0),
        "package_optimizer_sharding_registry": load_policy()["registry"],
    })
    atomic_json(DATA / "latest.json", latest)
    return performance


def main() -> int:
    parser = argparse.ArgumentParser(description="V3 registry-driven package optimizer shard runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--output", required=True)

    shard_parser = sub.add_parser("run-shard")
    shard_parser.add_argument("--plan", required=True)
    shard_parser.add_argument("--shard-id", required=True, type=int)
    shard_parser.add_argument("--output", required=True)

    reduce_parser = sub.add_parser("reduce")
    reduce_parser.add_argument("--plan", required=True)
    reduce_parser.add_argument("--shard-dir", required=True)

    perf_parser = sub.add_parser("finalize-runtime")
    perf_parser.add_argument("--plan", required=True)

    args = parser.parse_args()
    if args.command == "plan":
        result = build_plan()
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "READY", "matrix": result["matrix"], "shard_count": result["shard_count"], "task_count": result["task_count"], "estimated_pair_combinations": result["estimated_pair_combinations"]}, ensure_ascii=False))
        return 0
    if args.command == "run-shard":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = run_shard(plan, args.shard_id)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(json.dumps({"status": "READY", "shard_id": result["shard_id"], "tasks": result["task_count"], "pair_exact_scored": (result.get("counters") or {}).get("pair_candidates_exact_scored"), "scalar_fallbacks": (result.get("counters") or {}).get("batch_scalar_fallback_count")}, ensure_ascii=False))
        return 0
    if args.command == "reduce":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        optimizer = reduce_shards(plan, Path(args.shard_dir), persist=True)
        print(json.dumps({"status": optimizer.get("status"), "search_authority": (optimizer.get("search_diagnostics") or {}).get("search_authority"), "package_count": optimizer.get("package_count"), "shard_count": (optimizer.get("search_diagnostics") or {}).get("shard_count")}, ensure_ascii=False))
        return 0
    if args.command == "finalize-runtime":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        performance = finalize_runtime_performance(plan)
        print(json.dumps({"status": "READY", "total_wall_ms": performance.get("total_wall_ms"), "within_target_slo": performance.get("within_target_slo"), "within_legacy_ceiling": performance.get("within_legacy_ceiling")}, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
