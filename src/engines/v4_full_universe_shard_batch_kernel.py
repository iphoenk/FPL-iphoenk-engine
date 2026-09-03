from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_exact_batch import BatchContext, evaluate_batch
from src.engines.v4_full_universe_shard_kernel import (
    _POSITION_ORDER,
    _diagnostics,
    _roll_baseline,
    _task_incoming,
)
from src.engines.v4_wc_optimizer import Candidate


CONTRACT = "V4_FULL_UNIVERSE_EXACT_BATCH_SHARD_KERNEL_V1"


def _consume_rows(
    rows: Iterable[dict[str, Any]],
    *,
    k: int,
    top_by_k: dict[int, list[dict]],
    best_by_k: dict[str, dict | None],
    frontier: list[dict],
    frontier_epsilon: float,
    top_per_size: int,
    diagnostics: dict[str, Any],
) -> None:
    for row in rows:
        row.pop("batch_execution_only", None)
        diagnostics["packages_evaluated"] += 1
        core._retain_top(top_by_k[k], row, top_per_size)
        incumbent = best_by_k[str(k)]
        if incumbent is None or core._rank(row) > core._rank(incumbent):
            best_by_k[str(k)] = row
        before = len(frontier)
        compact = core._compact_for_frontier(row)
        core._frontier_insert(frontier, compact, frontier_epsilon)
        after = len(frontier)
        if compact not in frontier:
            diagnostics["packages_dominated_on_frontier"] += 1
        elif after <= before:
            diagnostics["packages_dominated_on_frontier"] += max(0, before + 1 - after)


def execute_tasks(
    material: dict[str, Any],
    tasks: list[dict[str, Any]],
    *,
    top_per_size: int,
    batch_size: int,
) -> tuple[dict[str, Any], set[str]]:
    """Execute exact planned tasks with vectorized numeric scoring.

    Task generation, legality, safe pruning, ranking, skyline semantics and final
    authority are unchanged. Only the numeric evaluation of already-legal incoming
    tuples is batched. The global reducer still scalar-rehydrates every row that may
    become published authority.
    """
    if batch_size <= 0:
        raise RuntimeError("exact batch shard kernel requires positive batch_size")

    policy = core._policy()
    search_cfg = policy.get("search") or {}
    maximum = int(search_cfg.get("maximum_replacements") or 3)
    if maximum < 1:
        raise RuntimeError("invalid maximum_replacements in package search policy")

    current = material["current"]
    locked = material["locked"]
    pools = material["pools"]
    reconciled = material["reconciled"]
    affordability = material["affordability"]
    budget = int(affordability["available_budget_tenths"])
    interactions = material["interactions"]
    prices = material["prices"]
    understat = material["understat"]
    by_id = {player.element: player for player in reconciled}
    interaction_map = core._interaction_rows(interactions)
    price_map = core._price_rows(prices)
    risk_by_element = {
        player.element: core._player_risk(player, interaction_map, price_map)
        for player in reconciled
    }

    baseline_metrics = core.reference._fast_metrics(current, include_detail=False)
    roll = _roll_baseline(current, baseline_metrics, locked, interaction_map)
    diagnostics = _diagnostics(material)
    diagnostics["batch_size"] = int(batch_size)
    diagnostics["batch_flushes"] = 0
    diagnostics["batch_scored_packages"] = 0
    frontier_epsilon = core._f(search_cfg.get("frontier_epsilon"), 0.01)
    frontier: list[dict] = []
    core._frontier_insert(frontier, core._compact_for_frontier(roll), frontier_epsilon)
    top_by_k = {k: [] for k in range(1, maximum + 1)}
    best_by_k: dict[str, dict | None] = {str(k): None for k in range(1, maximum + 1)}
    processed: set[str] = set()

    grouped: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for task in tasks:
        replacements = int(task.get("replacements") or 0)
        if replacements < 1 or replacements > maximum:
            raise RuntimeError(f"task replacement count outside governed search policy: {replacements}")
        out_ids = tuple(sorted(int(value) for value in task.get("out_ids") or []))
        grouped.setdefault(out_ids, []).append(task)

    for out_ids in sorted(grouped, key=lambda ids: (len(ids), ids)):
        outs = tuple(sorted(
            (by_id[element] for element in out_ids),
            key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element),
        ))
        out_set = set(out_ids)
        keep = tuple(player for player in current if player.element not in out_set)
        need = Counter(player.position for player in outs)
        k = len(outs)
        batch_context = BatchContext(
            outs=outs,
            keep=keep,
            baseline_metrics=baseline_metrics,
            locked=locked,
            policy=policy,
            risk_by_element=risk_by_element,
        )

        for task in sorted(grouped[out_ids], key=lambda row: (int(row.get("root_start") or 0), str(row.get("task_id")))):
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id in processed:
                raise RuntimeError(f"duplicate/blank shard task execution: {task_id!r}")

            buffer: list[tuple[Candidate, ...]] = []

            def flush() -> None:
                if not buffer:
                    return
                batch_rows = evaluate_batch(batch_context, buffer)
                if len(batch_rows) != len(buffer):
                    raise RuntimeError("exact batch scorer returned incomplete row set")
                diagnostics["batch_flushes"] += 1
                diagnostics["batch_scored_packages"] += len(batch_rows)
                _consume_rows(
                    batch_rows,
                    k=k,
                    top_by_k=top_by_k,
                    best_by_k=best_by_k,
                    frontier=frontier,
                    frontier_epsilon=frontier_epsilon,
                    top_per_size=top_per_size,
                    diagnostics=diagnostics,
                )
                buffer.clear()

            for ins_raw in _task_incoming(
                pools=pools,
                need=need,
                keep=keep,
                budget=budget,
                task=task,
                diagnostics=diagnostics,
            ):
                ins = tuple(sorted(ins_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
                buffer.append(ins)
                if len(buffer) >= batch_size:
                    flush()
            flush()
            processed.add(task_id)

    if diagnostics["packages_evaluated"] != diagnostics["batch_scored_packages"]:
        raise RuntimeError("batch execution accounting mismatch")

    frontier.sort(key=core._rank, reverse=True)
    diagnostics["packages_retained_on_frontier"] = len(frontier)
    finalized_cache: dict[str, dict] = {}

    def finalize(row: dict | None) -> dict | None:
        if row is None:
            return None
        package_id = str(row.get("package_id") or "")
        if package_id == "ROLL_BASELINE":
            return roll
        cached = finalized_cache.get(package_id)
        if cached is None:
            cached = core._finalize_package(
                row,
                by_id=by_id,
                current=current,
                locked=locked,
                prices=prices,
                policy=policy,
                budget=budget,
            )
            finalized_cache[package_id] = cached
        return cached

    frontier = [finalize(row) for row in frontier]
    top_by_k = {k: [finalize(row) for row in rows] for k, rows in top_by_k.items()}
    best_by_k = {key: finalize(row) for key, row in best_by_k.items()}
    packages = [row for k in range(1, maximum + 1) for row in top_by_k[k]]

    result = {
        "schema_version": 3,
        "contract": core.CONTRACT,
        "engine": "v4-full-universe-transfer-package-search-shard-exact-batch-v1",
        "overall_verdict": "SHARD_EXECUTION_ONLY",
        "recommended_package": None,
        "roll_baseline": roll,
        "baseline": baseline_metrics,
        "affordability": affordability,
        "best_by_replacement_count": best_by_k,
        "packages": packages,
        "efficient_frontier": {
            "status": "LOCAL_EXACT",
            "dominance_epsilon": frontier_epsilon,
            "rows": frontier,
            "categories": {},
            "maximize": (policy.get("efficient_frontier") or {}).get("maximize") or [],
            "minimize": (policy.get("efficient_frontier") or {}).get("minimize") or [],
        },
        "search": {
            "status": "SHARD_PARTIAL_EXACT",
            "global_optimality_guaranteed_under_declared_package_semantics": False,
            "shard_local_exactness": True,
            "full_eligible_universe_participates_before_safe_pruning": True,
            "watchlist_candidate_authority": False,
            "heuristic_candidate_cutoff": False,
            "beam_cutoff": False,
            "maximum_replacements": maximum,
            "safe_pruning_rule": "SAME_TEAM_SAME_POSITION_PARETO_DOMINANCE",
            "pruning_proofs": material["pruning_proofs"],
            "diagnostics": diagnostics,
        },
        "tactical_interaction_health": (interactions or {}).get("health") or {"status": "UNAVAILABLE"},
        "understat_rolling_player_intelligence": {
            "requested_windows": [1, 3, 5],
            "source_support": "SOURCE_SERIES_UNAVAILABLE" if not bool((understat or {}).get("player_match_series")) else "AVAILABLE",
            "season_aggregate_preserved": True,
            "source_absence_does_not_exclude_player": True,
        },
        "governance": {
            "official_fpl_factual_authority": True,
            "watchlist_is_output_only": True,
            "benchmark_players_are_not_search_seeds": True,
            "hardcoded_target_players": False,
            "no_silent_optimizer_truncation": True,
            "price_projection_separate_from_current_fact": True,
            "price_cannot_independently_authorize_transfer": True,
            "tactical_direct_xpts_multiplier": False,
            "tactical_direct_xmins_mutation": False,
            "global_optimality_claim_requires_safe_pruning_proof": True,
            "all_enumerated_packages_legal_by_exact_generator_constraints": True,
            "retained_packages_revalidated_with_canonical_validate_squad": True,
            "expensive_evidence_materialized_only_after_exact_selection": True,
            "sharding_changes_execution_topology_only": True,
            "batching_changes_numeric_execution_topology_only": True,
            "published_rows_require_scalar_rehydration_in_reducer": True,
        },
    }
    return result, processed
