from __future__ import annotations

from pathlib import Path

from tools.v4_exact_branch_bound_patch_temp import main as apply_branch_bound

PATH = Path("src/engines/v4_full_universe_package_search_core.py")


def main() -> None:
    apply_branch_bound()
    text = PATH.read_text(encoding="utf-8")

    old_imports = "from collections import Counter, defaultdict\nfrom itertools import combinations, permutations\nfrom typing import Any, Iterable, Iterator\n"
    new_imports = "from collections import Counter, defaultdict\nfrom concurrent.futures import ProcessPoolExecutor\nfrom itertools import combinations, permutations\nfrom math import comb\nfrom multiprocessing import get_context\nimport os\nfrom typing import Any, Iterable, Iterator\n"
    if old_imports not in text:
        raise SystemExit("parallel import target missing")
    text = text.replace(old_imports, new_imports, 1)

    marker = "def search_full_universe_packages(\n"
    insert_at = text.index(marker)
    helpers = r'''_PARALLEL_SEARCH_CONTEXT: dict | None = None


def _search_diag_template() -> dict:
    return {
        "search_nodes": 0,
        "incoming_combinations_considered": 0,
        "packages_evaluated": 0,
        "packages_rejected_by_budget": 0,
        "packages_rejected_by_budget_bound": 0,
        "packages_rejected_by_club_limit": 0,
        "packages_rejected_by_legality": 0,
        "packages_dominated_on_frontier": 0,
        "packages_pruned_by_admissible_branch_bound": 0,
        "exact_utility_evaluations": 0,
        "exact_utility_pruned_by_admissible_bound": 0,
    }


def _merge_numeric_diagnostics(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            target[key] = target.get(key, 0) + value


def _parallel_search_shard(jobs: tuple[tuple[int, tuple[int, ...]], ...]) -> dict:
    ctx = _PARALLEL_SEARCH_CONTEXT
    if ctx is None:
        raise RuntimeError("parallel package-search context not initialized")

    current = ctx["current"]
    by_id = ctx["by_id"]
    pools = ctx["pools"]
    derived_budget = ctx["derived_budget"]
    baseline_profile = ctx["baseline_profile"]
    baseline_metrics = ctx["baseline_metrics"]
    locked = ctx["locked"]
    policy = ctx["policy"]
    risk_by_element = ctx["risk_by_element"]
    top_per_size = ctx["top_per_size"]
    frontier_epsilon = ctx["frontier_epsilon"]
    position_extrema = ctx["position_extrema"]
    roll = ctx["roll"]

    diagnostics = _search_diag_template()
    local_top = {k: [] for k in range(1, int(ctx["max_replacements"]) + 1)}
    # Keep a lossless exact-dominance frontier locally. Configured epsilon is
    # applied only by the parent merge, preserving canonical tolerance semantics.
    local_frontier: list[dict] = [_compact_for_frontier(roll)]

    keep_profile_cache: dict[tuple[int, ...], dict] = {}
    chosen_profile_cache: dict[tuple[int, ...], dict] = {}
    incoming_risk_cache: dict[tuple[int, ...], dict] = {}
    position_prefix_cache: dict = {}

    for k, out_ids in jobs:
        outs = tuple(by_id[element] for element in out_ids)
        out_set = set(out_ids)
        keep = tuple(player for player in current if player.element not in out_set)
        need = Counter(player.position for player in outs)
        keep_profile = keep_profile_cache.get(out_ids)
        if keep_profile is None:
            keep_profile = _keep_profile_from_baseline(baseline_profile, outs)
            keep_profile_cache[out_ids] = keep_profile
        outgoing_risk = _risk_aggregate(outs, risk_by_element)

        def prefix_prunable(chosen_prefix, remaining_need):
            bound_vec, utility_upper = _admissible_prefix_bounds(
                chosen_prefix,
                remaining_need,
                outs=outs,
                outgoing_risk=outgoing_risk,
                risk_by_element=risk_by_element,
                extrema=position_extrema,
                baseline_metrics=baseline_metrics,
                locked=locked,
                policy=policy,
                k=k,
            )
            frontier_blocked = any(
                _dominates_vector(_frontier_tuple(incumbent), bound_vec, frontier_epsilon)
                for incumbent in local_frontier
            )
            if not frontier_blocked or len(local_top[k]) < top_per_size:
                return False
            threshold = _f(local_top[k][-1].get("adjusted_utility_gain_5"), float("-inf"))
            return utility_upper + 1e-12 < threshold

        for ins_raw in _incoming_combinations(
            pools,
            need,
            keep,
            derived_budget,
            diagnostics,
            prefix_prunable=prefix_prunable,
        ):
            ins = tuple(sorted(ins_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
            diagnostics["packages_evaluated"] += 1
            in_ids = tuple(player.element for player in ins)
            incoming_risk = incoming_risk_cache.get(in_ids)
            if incoming_risk is None:
                incoming_risk = _risk_aggregate(ins, risk_by_element)
                incoming_risk_cache[in_ids] = incoming_risk
            cheap = _cheap_package_row(
                outs,
                ins,
                baseline_metrics,
                locked,
                policy,
                outgoing_risk,
                incoming_risk,
            )

            compact = _compact_for_frontier(cheap)
            retained, removed = _frontier_insert(local_frontier, compact, 0.0)
            if not retained:
                diagnostics["packages_dominated_on_frontier"] += 1
            elif removed:
                diagnostics["packages_dominated_on_frontier"] += removed

            if not _can_enter_exact_top(cheap, local_top[k], top_per_size):
                diagnostics["exact_utility_pruned_by_admissible_bound"] += 1
                continue

            chosen_profile = chosen_profile_cache.get(in_ids)
            if chosen_profile is None:
                chosen_profile = _chosen_profile(ins)
                chosen_profile_cache[in_ids] = chosen_profile
            target_metrics = _metrics_from_profiles(
                keep_profile,
                chosen_profile,
                position_prefix_cache=position_prefix_cache,
            )
            exact = _exactify_package(cheap, target_metrics, baseline_metrics)
            diagnostics["exact_utility_evaluations"] += 1
            _retain_top(local_top[k], exact, top_per_size)

    return {
        "top_by_k": local_top,
        "frontier": [row for row in local_frontier if row.get("package_id") != "ROLL_BASELINE"],
        "diagnostics": diagnostics,
    }


def _outgoing_job_cost(job: tuple[int, tuple[int, ...]], by_id: dict[int, Candidate], pools: dict[str, list[Candidate]]) -> int:
    _k, out_ids = job
    need = Counter(by_id[element].position for element in out_ids)
    estimate = 1
    for pos, count in need.items():
        available = len(pools.get(pos, ()))
        if available < count:
            return 0
        estimate *= comb(available, int(count))
    return estimate


def _balanced_outgoing_shards(
    jobs: list[tuple[int, tuple[int, ...]]],
    workers: int,
    by_id: dict[int, Candidate],
    pools: dict[str, list[Candidate]],
) -> list[tuple[tuple[int, tuple[int, ...]], ...]]:
    workers = max(1, min(int(workers), len(jobs)))
    shards: list[list[tuple[int, tuple[int, ...]]]] = [[] for _ in range(workers)]
    loads = [0] * workers
    ranked = sorted(
        jobs,
        key=lambda job: (_outgoing_job_cost(job, by_id, pools), job[0], job[1]),
        reverse=True,
    )
    for job in ranked:
        index = min(range(workers), key=lambda idx: (loads[idx], idx))
        shards[index].append(job)
        loads[index] += _outgoing_job_cost(job, by_id, pools)
    return [tuple(shard) for shard in shards if shard]

'''
    text = text[:insert_at] + helpers + text[insert_at:]

    start = "    keep_profile_cache: dict[tuple[int, ...], dict] = {}\n"
    end = "    frontier.sort(key=_rank, reverse=True)\n"
    a = text.index(start)
    b = text.index(end, a)
    parallel_block = r'''    position_extrema = _build_position_extrema(pools, risk_by_element, max_replacements)
    all_jobs: list[tuple[int, tuple[int, ...]]] = []
    for k in range(1, max_replacements + 1):
        for outs_raw in combinations(current, k):
            outs = tuple(sorted(outs_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
            all_jobs.append((k, tuple(player.element for player in outs)))

    configured_workers = max(1, int(search_cfg.get("parallel_shards") or 4))
    cpu_workers = max(1, int(os.cpu_count() or 1))
    workers = min(configured_workers, cpu_workers, len(all_jobs))
    shards = _balanced_outgoing_shards(all_jobs, workers, by_id, pools)
    diagnostics["parallel_shards"] = len(shards)
    diagnostics["outgoing_jobs"] = len(all_jobs)

    global _PARALLEL_SEARCH_CONTEXT
    _PARALLEL_SEARCH_CONTEXT = {
        "current": current,
        "by_id": by_id,
        "pools": pools,
        "derived_budget": derived_budget,
        "baseline_profile": baseline_profile,
        "baseline_metrics": baseline_metrics,
        "locked": locked,
        "policy": policy,
        "risk_by_element": risk_by_element,
        "top_per_size": top_per_size,
        "frontier_epsilon": frontier_epsilon,
        "position_extrema": position_extrema,
        "roll": roll,
        "max_replacements": max_replacements,
    }
    try:
        if len(shards) <= 1 or not hasattr(os, "fork"):
            shard_results = [_parallel_search_shard(shard) for shard in shards]
        else:
            with ProcessPoolExecutor(max_workers=len(shards), mp_context=get_context("fork")) as executor:
                shard_results = list(executor.map(_parallel_search_shard, shards))
    finally:
        _PARALLEL_SEARCH_CONTEXT = None

    for result in shard_results:
        _merge_numeric_diagnostics(diagnostics, result.get("diagnostics") or {})
        for k in range(1, max_replacements + 1):
            for row in (result.get("top_by_k") or {}).get(k, []):
                _retain_top(top_by_k[k], row, top_per_size)
        for compact in result.get("frontier") or []:
            retained, removed = _frontier_insert(frontier, compact, frontier_epsilon)
            if not retained:
                diagnostics["packages_dominated_on_frontier"] += 1
            elif removed:
                diagnostics["packages_dominated_on_frontier"] += removed

    for k in range(1, max_replacements + 1):
        best_by_k[str(k)] = top_by_k[k][0] if top_by_k[k] else None

'''
    text = text[:a] + parallel_block + text[b:]

    old_governance = '            "branch_pruning_requires_frontier_and_top_impossibility": True,\n'
    new_governance = old_governance + '            "parallel_outgoing_shards_preserve_exact_union": True,\n            "local_frontier_uses_zero_epsilon_before_canonical_merge": True,\n'
    if old_governance not in text:
        raise SystemExit("parallel governance target missing")
    text = text.replace(old_governance, new_governance, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
