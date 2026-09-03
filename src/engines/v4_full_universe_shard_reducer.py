from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_shard_planner import PLAN_FILE, load_plan
from src.engines.v4_full_universe_shard_worker import CONTRACT as SHARD_CONTRACT, DEFAULT_DIR
from src.utils import DATA, atomic_json, read_json


CONTRACT = "V4_FULL_UNIVERSE_SHARD_REDUCTION_V1"
DEFAULT_OUTPUT = DATA / "runtime" / "v4_full_universe_precomputed.json"


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_results(directory: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(directory.glob("shard_*.json")):
        payload = read_json(path, {}) or {}
        payload["_source_path"] = str(path)
        rows.append(payload)
    return rows


def _verify(plan: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_shards = {int(row["shard_id"]) for row in plan.get("shards") or []}
    if not results:
        raise RuntimeError("no V4 full-universe shard results found")
    actual_shards: set[int] = set()
    task_owner: dict[str, int] = {}
    processed_owner: dict[str, int] = {}
    pruning_hashes: set[str] = set()
    baseline_hashes: set[str] = set()
    affordability_hashes: set[str] = set()
    epsilon_values: set[float] = set()
    non_roll_package_owner: dict[str, int] = {}

    expected_tasks = {
        str(task["task_id"])
        for shard in plan.get("shards") or []
        for task in shard.get("tasks") or []
    }

    for result in results:
        execution = result.get("shard_execution") or {}
        if execution.get("contract") != SHARD_CONTRACT:
            raise RuntimeError(f"invalid shard result contract in {result.get('_source_path')}")
        shard_id = int(execution.get("shard_id"))
        if shard_id in actual_shards:
            raise RuntimeError(f"duplicate shard result shard_id={shard_id}")
        actual_shards.add(shard_id)
        if str(execution.get("optimizer_input_fingerprint") or "") != str(plan.get("optimizer_input_fingerprint") or ""):
            raise RuntimeError(f"optimizer fingerprint mismatch on shard_id={shard_id}")
        if str(execution.get("execution_code_fingerprint") or "") != str(plan.get("execution_code_fingerprint") or ""):
            raise RuntimeError(f"execution code fingerprint mismatch on shard_id={shard_id}")
        assigned = [str(value) for value in execution.get("assigned_task_ids") or []]
        processed = [str(value) for value in execution.get("processed_task_ids") or []]
        if sorted(assigned) != sorted(processed) or len(processed) != len(set(processed)):
            raise RuntimeError(f"shard-local task coverage mismatch shard_id={shard_id}")
        for task_id in assigned:
            if task_id in task_owner:
                raise RuntimeError(f"duplicate assigned task across shards: {task_id}")
            task_owner[task_id] = shard_id
        for task_id in processed:
            if task_id in processed_owner:
                raise RuntimeError(f"duplicate processed task across shards: {task_id}")
            processed_owner[task_id] = shard_id
        search = result.get("search") or {}
        if search.get("status") != "SHARD_PARTIAL_EXACT" or search.get("shard_local_exactness") is not True:
            raise RuntimeError(f"non-exact shard result shard_id={shard_id}")
        pruning_hashes.add(_stable_hash(search.get("pruning_proofs") or []))
        baseline_hashes.add(_stable_hash(result.get("baseline") or {}))
        affordability_hashes.add(_stable_hash(result.get("affordability") or {}))
        epsilon_values.add(float((result.get("efficient_frontier") or {}).get("dominance_epsilon") or 0.0))
        for row in result.get("packages") or []:
            package_id = str(row.get("package_id") or "")
            if not package_id or package_id == "ROLL_BASELINE":
                continue
            prior = non_roll_package_owner.get(package_id)
            if prior is not None and prior != shard_id:
                raise RuntimeError(f"duplicate non-roll package across disjoint shards: {package_id}")
            non_roll_package_owner[package_id] = shard_id

    if actual_shards != expected_shards:
        raise RuntimeError(f"shard set incomplete expected={sorted(expected_shards)} actual={sorted(actual_shards)}")
    if set(task_owner) != expected_tasks:
        raise RuntimeError(f"assigned task cover incomplete missing={sorted(expected_tasks-set(task_owner))[:20]} unexpected={sorted(set(task_owner)-expected_tasks)[:20]}")
    if set(processed_owner) != expected_tasks:
        raise RuntimeError(f"processed task cover incomplete missing={sorted(expected_tasks-set(processed_owner))[:20]} unexpected={sorted(set(processed_owner)-expected_tasks)[:20]}")
    if len(pruning_hashes) != 1:
        raise RuntimeError("safe-pruning proof set differs across shards")
    if len(baseline_hashes) != 1 or len(affordability_hashes) != 1:
        raise RuntimeError("baseline/affordability contract differs across shards")
    if len(epsilon_values) != 1:
        raise RuntimeError("frontier epsilon differs across shards")

    return {
        "expected_shard_count": len(expected_shards),
        "actual_shard_count": len(actual_shards),
        "expected_task_count": len(expected_tasks),
        "assigned_task_count": len(task_owner),
        "processed_task_count": len(processed_owner),
        "complete_task_cover": True,
        "task_assignment_disjoint": True,
        "task_processing_disjoint": True,
        "optimizer_input_fingerprint_match": True,
        "execution_code_fingerprint_match": True,
        "safe_pruning_proof_match": True,
        "baseline_match": True,
        "affordability_match": True,
        "frontier_epsilon_match": True,
        "non_roll_package_overlap_detected": False,
    }


def _merge_diagnostics(results: list[dict[str, Any]]) -> dict[str, Any]:
    additive = (
        "search_nodes",
        "incoming_combinations_considered",
        "packages_evaluated",
        "packages_rejected_by_budget",
        "packages_rejected_by_budget_bound",
        "packages_rejected_by_club_limit",
        "packages_rejected_by_legality",
        "packages_dominated_on_frontier",
    )
    first = copy.deepcopy(((results[0].get("search") or {}).get("diagnostics") or {}))
    for key in additive:
        first[key] = sum(int((((row.get("search") or {}).get("diagnostics") or {}).get(key) or 0)) for row in results)
    first["packages_retained_on_frontier"] = None
    first["shard_count"] = len(results)
    first["sharded_execution"] = True
    return first


def reduce_results(plan: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    proof = _verify(plan, results)
    template = copy.deepcopy(results[0])
    top_limit = int((((plan.get("registry") or {}).get("planner") or {}).get("top_keep_per_shard") or 12))
    epsilon = float((template.get("efficient_frontier") or {}).get("dominance_epsilon") or 0.01)

    top_by_k: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    package_seen: set[str] = set()
    for result in results:
        for row in result.get("packages") or []:
            package_id = str(row.get("package_id") or "")
            if not package_id or package_id in package_seen:
                continue
            package_seen.add(package_id)
            replacements = int(row.get("replacements") or 0)
            if replacements in top_by_k:
                core._retain_top(top_by_k[replacements], copy.deepcopy(row), top_limit)

    roll = copy.deepcopy(template.get("roll_baseline") or {})
    frontier_by_id: dict[str, dict] = {}
    if roll:
        frontier_by_id[str(roll.get("package_id") or "ROLL_BASELINE")] = roll
    for result in results:
        for row in (result.get("efficient_frontier") or {}).get("rows") or []:
            package_id = str(row.get("package_id") or "")
            if not package_id:
                raise RuntimeError("frontier row without package_id")
            if package_id not in frontier_by_id:
                frontier_by_id[package_id] = copy.deepcopy(row)

    frontier: list[dict] = []
    for package_id in sorted(frontier_by_id):
        core._frontier_insert(frontier, frontier_by_id[package_id], epsilon)
    frontier.sort(key=core._rank, reverse=True)

    best_by_k = {str(k): (rows[0] if rows else None) for k, rows in top_by_k.items()}
    packages = [row for k in (1, 2, 3) for row in top_by_k[k]]
    best_candidates = [row for row in best_by_k.values() if row]
    recommended = max(best_candidates, key=core._rank) if best_candidates else None
    if recommended and core._f(recommended.get("adjusted_utility_gain_5")) <= 0:
        recommended = None
    overall = (recommended or roll).get("classification") or "ROLL_BASELINE"
    categories = core._frontier_categories(frontier, roll)

    diagnostics = _merge_diagnostics(results)
    diagnostics["packages_retained_on_frontier"] = len(frontier)
    template["schema_version"] = max(3, int(template.get("schema_version") or 0))
    template["engine"] = "v4-full-universe-transfer-package-search-sharded-v1"
    template["overall_verdict"] = overall
    template["recommended_package"] = recommended
    template["best_by_replacement_count"] = best_by_k
    template["packages"] = packages
    template["efficient_frontier"]["status"] = "PASS"
    template["efficient_frontier"]["rows"] = frontier
    template["efficient_frontier"]["categories"] = categories
    template["search"]["status"] = "FULL_UNIVERSE_PROVEN"
    template["search"]["global_optimality_guaranteed_under_declared_package_semantics"] = True
    template["search"].pop("shard_local_exactness", None)
    template["search"]["diagnostics"] = diagnostics
    template["decision_authority"] = "PRECOMPUTED_FULL_UNIVERSE_EXACT_FOR_OPTIMIZATION"
    template["execution_authorized"] = False
    template.pop("shard_execution", None)
    template["shard_reduction"] = {
        "schema_version": 1,
        "contract": CONTRACT,
        "execution_only": True,
        "authority_owner": "optimization",
        "optimizer_input_fingerprint": plan.get("optimizer_input_fingerprint"),
        "execution_code_fingerprint": plan.get("execution_code_fingerprint"),
        "proof": proof,
        "top_keep_per_shard": top_limit,
        "global_top_n_exact_from_union_of_local_top_n": True,
        "global_frontier_exact_from_union_of_exact_local_frontiers": True,
        "single_final_business_authority_preserved": True,
        "fail_closed_on_partial_inconsistent_or_overlapping_shards": True,
    }
    template.setdefault("governance", {})["sharding_changes_execution_topology_only"] = True
    template["governance"]["workers_are_non_authoritative"] = True
    template["governance"]["global_completeness_proven_before_full_universe_state"] = True
    return template


def run(*, plan_path: Path = PLAN_FILE, shard_dir: Path = DEFAULT_DIR, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    plan = load_plan(plan_path)
    results = _load_results(shard_dir)
    reduced = reduce_results(plan, results)
    atomic_json(output_path, reduced)
    return reduced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(PLAN_FILE))
    parser.add_argument("--shard-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    result = run(plan_path=Path(args.plan), shard_dir=Path(args.shard_dir), output_path=Path(args.output))
    print(json.dumps({
        "contract": CONTRACT,
        "status": (result.get("search") or {}).get("status"),
        "shards": (result.get("shard_reduction") or {}).get("proof", {}).get("actual_shard_count"),
        "tasks": (result.get("shard_reduction") or {}).get("proof", {}).get("processed_task_count"),
        "packages_evaluated": ((result.get("search") or {}).get("diagnostics") or {}).get("packages_evaluated"),
        "frontier": len((result.get("efficient_frontier") or {}).get("rows") or []),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
