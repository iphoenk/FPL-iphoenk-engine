from __future__ import annotations

import json

from src.models.package_optimizer_v2 import load_config as load_optimizer_config
from src.runtime_v3.package_optimizer_shards import load_policy


def validate() -> dict:
    policy = load_policy()
    planner = policy.get("planner") or {}
    contracts = policy.get("contracts") or {}
    optimizer = load_optimizer_config()
    local_keep = int(planner.get("top_keep_per_shard") or 0)
    global_top = int(optimizer.get("monte_carlo_top_n") or 0)
    if local_keep < global_top:
        raise RuntimeError(
            "shard local retention is too small for exact global top-K fan-in: "
            f"local_keep={local_keep} global_top={global_top}"
        )
    required_true = (
        "complete_outgoing_pair_task_cover_required",
        "duplicate_pair_task_forbidden",
        "missing_pair_task_forbidden",
        "all_shards_require_same_optimizer_input_fingerprint",
        "shards_may_not_write_package_optimizer",
        "shards_may_not_write_package_decision",
        "shard_partition_may_not_prune_candidates",
        "shard_partition_may_not_change_scoring",
        "shard_partition_may_not_change_sequential_legality",
        "local_frontier_reduction_must_be_exact",
        "business_authority_is_not_sharded",
    )
    missing = [key for key in required_true if contracts.get(key) is not True]
    if missing:
        raise RuntimeError(f"shard governance contract disabled: {missing}")
    return {
        "status": "PASS",
        "registry": policy.get("registry"),
        "local_top_keep": local_keep,
        "global_top_required": global_top,
        "hidden_top_n_search_authority": False,
        "complete_exact_fan_in": True,
    }


def main() -> int:
    print(json.dumps(validate(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
