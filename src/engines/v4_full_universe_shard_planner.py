from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from itertools import combinations
from math import comb
from pathlib import Path
from typing import Any

from src.engines.v4_decision_pipeline import _semantic_fingerprint, effective_planning_squad
from src.engines.v4_full_universe_package_search import safe_prune_incoming_players
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import POSITION_COUNTS, build_candidates, reconcile_owned_costs
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, read_json


CONTRACT = "V4_FULL_UNIVERSE_SHARD_PLAN_V1"
REGISTRY_FILE = CONFIG / "intelligence" / "full_universe_package_search_sharding.json"
PLAN_FILE = DATA / "runtime" / "v4_full_universe_shard_plan.json"
_POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
_CODE_FILES = (
    Path("src/engines/v4_full_universe_package_search.py"),
    Path("src/engines/v4_full_universe_package_search_core.py"),
    Path("src/engines/v4_wc_package_audit_fast.py"),
)


def load_registry() -> dict[str, Any]:
    registry = read_json(REGISTRY_FILE, {}) or {}
    if registry.get("registry") != "V4_FULL_UNIVERSE_PACKAGE_SEARCH_SHARDING_V1":
        raise RuntimeError("invalid V4 full-universe sharding registry")
    planner = registry.get("planner") or {}
    required_positive = (
        "target_combinations_per_shard",
        "max_estimated_combinations_per_task",
        "min_shards",
        "max_shards",
        "top_keep_per_shard",
    )
    for key in required_positive:
        value = planner.get(key)
        if value is None or int(value) <= 0:
            raise RuntimeError(f"sharding registry requires measured positive planner.{key}")
    if int(planner["min_shards"]) > int(planner["max_shards"]):
        raise RuntimeError("sharding registry min_shards exceeds max_shards")
    return registry


def _execution_code_fingerprint() -> str:
    payload = {
        str(path): file_digest(path)
        for path in _CODE_FILES
    }
    payload[str(REGISTRY_FILE)] = file_digest(REGISTRY_FILE)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_material() -> dict[str, Any]:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    prices = read_json(DATA / "prices.json", {})
    understat = read_json(DATA / "understat_tactical_v4.json", {})
    configured = read_json(CONFIG / "locked_squad.json", {})
    locked = effective_planning_squad(team, configured, latest)
    candidates = build_candidates(predictions, universe)
    interactions = build_tactical_interactions(predictions, universe, understat)
    reconciled, affordability = reconcile_owned_costs(candidates, locked)
    owned_ids = {
        int(row.get("element"))
        for row in locked.get("players") or []
        if row.get("element") is not None
    }
    by_id = {player.element: player for player in reconciled}
    missing = sorted(owned_ids - set(by_id))
    if missing:
        raise RuntimeError(f"owned players absent from candidate universe: {missing}")
    current = tuple(by_id[element] for element in sorted(owned_ids))
    external, pruning_proofs = safe_prune_incoming_players(
        reconciled,
        owned_ids,
        interactions=interactions,
        prices=prices,
        predictions=predictions,
        universe=universe,
    )
    pools = {position: [] for position in POSITION_COUNTS}
    for player in external:
        pools[player.position].append(player)
    for position in pools:
        pools[position].sort(key=lambda row: row.element)
    optimizer_fingerprint = _semantic_fingerprint(
        predictions,
        universe,
        locked,
        understat,
        candidates=candidates,
        tactical_interactions=interactions,
        prices=prices,
    )
    return {
        "predictions": predictions,
        "universe": universe,
        "team": team,
        "latest": latest,
        "prices": prices,
        "understat": understat,
        "locked": locked,
        "candidates": candidates,
        "interactions": interactions,
        "reconciled": reconciled,
        "affordability": affordability,
        "current": current,
        "pools": pools,
        "pruning_proofs": pruning_proofs,
        "optimizer_input_fingerprint": optimizer_fingerprint,
    }


def _task_id(out_ids: tuple[int, ...], root_start: int, root_end: int) -> str:
    out = "-".join(str(element) for element in out_ids)
    return f"OUT[{out}]@ROOT[{root_start}:{root_end}]"


def _outgoing_task_rows(material: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, Any]]:
    planner = registry["planner"]
    max_task_work = int(planner["max_estimated_combinations_per_task"])
    current = material["current"]
    pools = material["pools"]
    budget = int(material["affordability"]["available_budget_tenths"])
    tasks: list[dict[str, Any]] = []

    for replacements in range(1, 4):
        for outs_raw in combinations(current, replacements):
            outs = tuple(sorted(outs_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
            out_ids = tuple(sorted(player.element for player in outs))
            out_set = set(out_ids)
            keep_cost = sum(player.cost for player in current if player.element not in out_set)
            need = Counter(player.position for player in outs)
            groups = [
                (position, int(need[position]))
                for position in sorted(need, key=lambda p: (_POSITION_ORDER.get(p, 99), p))
                if int(need[position]) > 0
            ]
            filtered_sizes = {
                position: sum(1 for player in pools[position] if keep_cost + player.cost <= budget)
                for position, _count in groups
            }
            if any(filtered_sizes[position] < count for position, count in groups):
                root_position, root_count = groups[0]
                tasks.append({
                    "task_id": _task_id(out_ids, 0, 0),
                    "out_ids": list(out_ids),
                    "replacements": replacements,
                    "root_position": root_position,
                    "root_count": root_count,
                    "root_start": 0,
                    "root_end": 0,
                    "root_combination_count": 0,
                    "estimated_work": 0,
                    "filtered_pool_sizes": filtered_sizes,
                })
                continue

            root_position, root_count = groups[0]
            root_combinations = comb(filtered_sizes[root_position], root_count)
            suffix_estimate = 1
            for position, count in groups[1:]:
                suffix_estimate *= comb(filtered_sizes[position], count)
            root_chunk = max(1, max_task_work // max(1, suffix_estimate))
            root_chunk = min(root_chunk, max(1, root_combinations))
            for start in range(0, root_combinations, root_chunk):
                end = min(root_combinations, start + root_chunk)
                tasks.append({
                    "task_id": _task_id(out_ids, start, end),
                    "out_ids": list(out_ids),
                    "replacements": replacements,
                    "root_position": root_position,
                    "root_count": root_count,
                    "root_start": start,
                    "root_end": end,
                    "root_combination_count": root_combinations,
                    "estimated_work": (end - start) * suffix_estimate,
                    "filtered_pool_sizes": filtered_sizes,
                })
    return tasks


def _prove_task_partition(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(task["task_id"]) for task in tasks]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate V4 shard task id generated")
    by_out: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}
    for task in tasks:
        key = tuple(int(x) for x in task["out_ids"])
        by_out.setdefault(key, []).append((int(task["root_start"]), int(task["root_end"]), int(task["root_combination_count"])))
    for out_ids, ranges in by_out.items():
        ranges.sort()
        expected_total = ranges[0][2] if ranges else 0
        cursor = 0
        for start, end, total in ranges:
            if total != expected_total:
                raise RuntimeError(f"root combination total mismatch for outgoing task {out_ids}")
            if start != cursor or end < start:
                raise RuntimeError(f"gap/overlap in root ranges for outgoing task {out_ids}: cursor={cursor}, range=({start},{end})")
            cursor = end
        if cursor != expected_total:
            raise RuntimeError(f"root range coverage incomplete for outgoing task {out_ids}: {cursor}!={expected_total}")
    return {
        "task_count": len(tasks),
        "unique_task_count": len(set(ids)),
        "outgoing_set_count": len(by_out),
        "all_task_ids_unique": True,
        "root_ranges_complete_and_disjoint_per_outgoing_set": True,
    }


def _balance(tasks: list[dict[str, Any]], registry: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    planner = registry["planner"]
    positive_tasks = [task for task in tasks if int(task["estimated_work"]) > 0]
    total_work = sum(int(task["estimated_work"]) for task in positive_tasks)
    target = int(planner["target_combinations_per_shard"])
    desired = max(1, math.ceil(total_work / target))
    shard_count = max(int(planner["min_shards"]), desired)
    shard_count = min(int(planner["max_shards"]), shard_count)
    shard_count = min(max(1, len(tasks)), shard_count)
    shards = [
        {"shard_id": index, "estimated_work": 0, "tasks": []}
        for index in range(shard_count)
    ]
    for task in sorted(tasks, key=lambda row: (-int(row["estimated_work"]), str(row["task_id"]))):
        target_shard = min(shards, key=lambda row: (int(row["estimated_work"]), int(row["shard_id"])))
        target_shard["tasks"].append(task)
        target_shard["estimated_work"] += int(task["estimated_work"])
    assigned = [str(task["task_id"]) for shard in shards for task in shard["tasks"]]
    expected = [str(task["task_id"]) for task in tasks]
    if sorted(assigned) != sorted(expected) or len(assigned) != len(set(assigned)):
        raise RuntimeError("shard assignment does not exactly cover unique planned tasks")
    loads = [int(shard["estimated_work"]) for shard in shards]
    return shards, {
        "strategy": str(planner.get("strategy")),
        "estimated_total_work": total_work,
        "target_combinations_per_shard": target,
        "derived_shard_count": shard_count,
        "min_estimated_shard_work": min(loads) if loads else 0,
        "max_estimated_shard_work": max(loads) if loads else 0,
        "mean_estimated_shard_work": round(total_work / max(1, shard_count), 2),
        "task_cover_complete": True,
        "task_assignment_disjoint": True,
    }


def build_plan() -> dict[str, Any]:
    registry = load_registry()
    material = _load_material()
    tasks = _outgoing_task_rows(material, registry)
    partition_proof = _prove_task_partition(tasks)
    shards, balance = _balance(tasks, registry)
    plan = {
        "schema_version": 1,
        "contract": CONTRACT,
        "execution_only": True,
        "authority_owner": "optimization",
        "optimizer_input_fingerprint": material["optimizer_input_fingerprint"],
        "execution_code_fingerprint": _execution_code_fingerprint(),
        "planning_gw": material["locked"].get("planning_gw"),
        "baseline_gw": material["locked"].get("baseline_gw"),
        "registry": registry,
        "universe": {
            "candidate_count": len(material["candidates"]),
            "safe_pruned_count": len(material["pruning_proofs"]),
            "remaining_external_count": sum(len(rows) for rows in material["pools"].values()),
            "pool_sizes": {position: len(rows) for position, rows in material["pools"].items()},
        },
        "partition_proof": partition_proof,
        "balance": balance,
        "shards": shards,
        "matrix": [{"shard_id": int(shard["shard_id"])} for shard in shards],
        "contracts": {
            "workers_are_execution_only": True,
            "task_cover_is_complete_and_disjoint": True,
            "same_optimizer_fingerprint_required": True,
            "same_execution_code_fingerprint_required": True,
            "no_candidate_pruning_introduced_by_partition": True,
        },
    }
    return plan


def _emit_github_output(matrix: list[dict[str, int]]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-matrix", action="store_true")
    parser.add_argument("--output", default=str(PLAN_FILE))
    args = parser.parse_args()
    plan = build_plan()
    atomic_json(Path(args.output), plan)
    if args.emit_matrix:
        _emit_github_output(plan["matrix"])
        print(json.dumps(plan["matrix"], separators=(",", ":")))
    else:
        print(json.dumps({
            "contract": CONTRACT,
            "shards": len(plan["shards"]),
            "tasks": plan["partition_proof"]["task_count"],
            "estimated_total_work": plan["balance"]["estimated_total_work"],
            "max_estimated_shard_work": plan["balance"]["max_estimated_shard_work"],
        }, separators=(",", ":")))


if __name__ == "__main__":
    main()
