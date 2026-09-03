from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.engines.v4_full_universe_shard_kernel import CONTRACT as KERNEL_CONTRACT, execute_tasks
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
    top_keep = int((((plan.get("registry") or {}).get("planner") or {}).get("top_keep_per_shard") or 0))
    if top_keep <= 0:
        raise RuntimeError("shard plan requires positive registry-owned top_keep_per_shard")

    result, processed = execute_tasks(material, tasks, top_per_size=top_keep)
    assigned_ids = {str(task["task_id"]) for task in tasks}
    if processed != assigned_ids:
        raise RuntimeError(
            f"shard task execution coverage mismatch missing={sorted(assigned_ids-processed)} "
            f"unexpected={sorted(processed-assigned_ids)}"
        )
    result["overall_verdict"] = "SHARD_EXECUTION_ONLY"
    result["recommended_package"] = None
    result["decision_authority"] = "EXECUTION_ONLY_SHARD_PARTIAL"
    result["execution_authorized"] = False
    result["shard_execution"] = {
        "schema_version": 1,
        "contract": CONTRACT,
        "kernel_contract": KERNEL_CONTRACT,
        "execution_only": True,
        "shard_id": int(shard_id),
        "optimizer_input_fingerprint": current_optimizer_fingerprint,
        "execution_code_fingerprint": current_code_fingerprint,
        "assigned_task_ids": sorted(assigned_ids),
        "processed_task_ids": sorted(processed),
        "assigned_task_count": len(tasks),
        "estimated_work": int(shard.get("estimated_work") or 0),
        "authority_owner": "optimization",
        "workers_may_not_publish_final_package_authority": True,
        "canonical_search_kernel_reused": True,
        "explicit_task_kernel": True,
        "monolithic_full_search_invocation": False,
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
