from __future__ import annotations

import argparse
import json
from itertools import combinations as canonical_combinations
from pathlib import Path
from typing import Any, Iterator

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_package_search import search_full_universe_packages
from src.engines.v4_full_universe_shard_planner import (
    PLAN_FILE,
    _execution_code_fingerprint,
    _load_material,
    load_plan,
)
from src.utils import DATA, atomic_json


CONTRACT = "V4_FULL_UNIVERSE_SHARD_RESULT_V1"
DEFAULT_DIR = DATA / "runtime" / "v4_full_universe_shards"


def _shard(plan: dict[str, Any], shard_id: int) -> dict[str, Any]:
    matches = [row for row in plan.get("shards") or [] if int(row.get("shard_id")) == int(shard_id)]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one shard definition for shard_id={shard_id}, got {len(matches)}")
    return matches[0]


def _ranges_by_out(tasks: list[dict[str, Any]]) -> dict[tuple[int, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for task in tasks:
        out_ids = tuple(sorted(int(element) for element in task.get("out_ids") or []))
        if len(out_ids) != int(task.get("replacements") or 0):
            raise RuntimeError(f"invalid shard task outgoing identity: {task}")
        grouped.setdefault(out_ids, []).append(task)
    for out_ids, rows in grouped.items():
        roots = {(str(row.get("root_position")), int(row.get("root_count") or 0)) for row in rows}
        if len(roots) != 1:
            raise RuntimeError(f"inconsistent root contract for outgoing set {out_ids}: {sorted(roots)}")
        ordered = sorted((int(row.get("root_start") or 0), int(row.get("root_end") or 0)) for row in rows)
        for left, right in zip(ordered, ordered[1:]):
            if left[1] > right[0]:
                raise RuntimeError(f"overlapping root ranges assigned inside shard for outgoing set {out_ids}")
    return grouped


def _execute_filtered_search(material: dict[str, Any], tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], set[str]]:
    allowed = _ranges_by_out(tasks)
    assigned_ids = {str(task["task_id"]) for task in tasks}
    owned = tuple(sorted(player.element for player in material["current"]))
    processed: set[str] = set()
    active_out: dict[str, tuple[int, ...] | None] = {"ids": None}
    original = core.combinations

    def filtered_combinations(iterable, count: int) -> Iterator[tuple]:
        seq = tuple(iterable)
        candidate_elements = tuple(sorted(getattr(item, "element", -1) for item in seq))
        if len(seq) == 15 and candidate_elements == owned and int(count) in (1, 2, 3):
            def outgoing() -> Iterator[tuple]:
                for combo in canonical_combinations(seq, count):
                    out_ids = tuple(sorted(player.element for player in combo))
                    rows = allowed.get(out_ids)
                    if not rows:
                        continue
                    active_out["ids"] = out_ids
                    processed.update(str(row["task_id"]) for row in rows)
                    try:
                        yield combo
                    finally:
                        active_out["ids"] = None
            return outgoing()

        out_ids = active_out["ids"]
        if out_ids is not None:
            rows = allowed[out_ids]
            root_position = str(rows[0].get("root_position"))
            root_count = int(rows[0].get("root_count") or 0)
            is_candidate_group = bool(seq) and all(hasattr(item, "element") and hasattr(item, "position") for item in seq)
            if is_candidate_group and int(count) == root_count and all(str(item.position) == root_position for item in seq):
                ranges = sorted((int(row.get("root_start") or 0), int(row.get("root_end") or 0)) for row in rows)

                def root_subset() -> Iterator[tuple]:
                    range_index = 0
                    for ordinal, combo in enumerate(canonical_combinations(seq, count)):
                        while range_index < len(ranges) and ordinal >= ranges[range_index][1]:
                            range_index += 1
                        if range_index >= len(ranges):
                            break
                        start, end = ranges[range_index]
                        if start <= ordinal < end:
                            yield combo
                return root_subset()

        return canonical_combinations(seq, count)

    core.combinations = filtered_combinations
    try:
        result = search_full_universe_packages(
            material["candidates"],
            material["locked"],
            predictions=material["predictions"],
            universe=material["universe"],
            understat=material["understat"],
            interactions=material["interactions"],
            prices=material["prices"],
            max_replacements=3,
        )
    finally:
        core.combinations = original

    if processed != assigned_ids:
        missing = sorted(assigned_ids - processed)
        unexpected = sorted(processed - assigned_ids)
        raise RuntimeError(f"shard task execution coverage mismatch missing={missing} unexpected={unexpected}")
    return result, processed


def run_shard(shard_id: int, *, plan_path: Path = PLAN_FILE, output_path: Path | None = None) -> dict[str, Any]:
    plan = load_plan(plan_path)
    shard = _shard(plan, shard_id)
    material = _load_material()
    current_optimizer_fingerprint = str(material["optimizer_input_fingerprint"])
    current_code_fingerprint = _execution_code_fingerprint()
    if current_optimizer_fingerprint != str(plan.get("optimizer_input_fingerprint") or ""):
        raise RuntimeError("optimizer input fingerprint changed after shard planning")
    if current_code_fingerprint != str(plan.get("execution_code_fingerprint") or ""):
        raise RuntimeError("execution code fingerprint changed after shard planning")

    tasks = list(shard.get("tasks") or [])
    if not tasks:
        raise RuntimeError(f"shard_id={shard_id} has no tasks")
    result, processed = _execute_filtered_search(material, tasks)
    result["overall_verdict"] = "SHARD_EXECUTION_ONLY"
    result["recommended_package"] = None
    result["decision_authority"] = "EXECUTION_ONLY_SHARD_PARTIAL"
    result["execution_authorized"] = False
    result.setdefault("search", {})["status"] = "SHARD_PARTIAL_EXACT"
    result["search"]["global_optimality_guaranteed_under_declared_package_semantics"] = False
    result["search"]["shard_local_exactness"] = True
    result.setdefault("efficient_frontier", {})["status"] = "LOCAL_EXACT"
    result["shard_execution"] = {
        "schema_version": 1,
        "contract": CONTRACT,
        "execution_only": True,
        "shard_id": int(shard_id),
        "optimizer_input_fingerprint": current_optimizer_fingerprint,
        "execution_code_fingerprint": current_code_fingerprint,
        "assigned_task_ids": sorted(str(task["task_id"]) for task in tasks),
        "processed_task_ids": sorted(processed),
        "assigned_task_count": len(tasks),
        "estimated_work": int(shard.get("estimated_work") or 0),
        "authority_owner": "optimization",
        "workers_may_not_publish_final_package_authority": True,
        "canonical_search_kernel_reused": True,
        "partition_only_changes_execution_topology": True,
    }
    destination = output_path or (DEFAULT_DIR / f"shard_{int(shard_id):03d}.json")
    atomic_json(destination, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-id", type=int, required=True)
    parser.add_argument("--plan", default=str(PLAN_FILE))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run_shard(
        args.shard_id,
        plan_path=Path(args.plan),
        output_path=Path(args.output) if args.output else None,
    )
    print(json.dumps({
        "contract": CONTRACT,
        "shard_id": args.shard_id,
        "tasks": result["shard_execution"]["assigned_task_count"],
        "estimated_work": result["shard_execution"]["estimated_work"],
        "packages_evaluated": ((result.get("search") or {}).get("diagnostics") or {}).get("packages_evaluated"),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
