from __future__ import annotations

from collections import Counter
from itertools import combinations, islice
from typing import Any, Iterator

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, Candidate


CONTRACT = "V4_FULL_UNIVERSE_EXACT_SHARD_KERNEL_V1"
_POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}


def _diagnostics(material: dict[str, Any]) -> dict[str, Any]:
    reconciled = material["reconciled"]
    current = material["current"]
    proofs = material["pruning_proofs"]
    pools = material["pools"]
    return {
        "input_universe_size": len(material["candidates"]),
        "eligible_universe_size": len(reconciled),
        "owned_players": len(current),
        "unowned_before_safe_pruning": len(reconciled) - len(current),
        "safely_pruned_players": len(proofs),
        "remaining_incoming_players": sum(len(rows) for rows in pools.values()),
        "search_nodes": 0,
        "incoming_combinations_considered": 0,
        "packages_evaluated": 0,
        "packages_rejected_by_budget": 0,
        "packages_rejected_by_budget_bound": 0,
        "packages_rejected_by_club_limit": 0,
        "packages_rejected_by_legality": 0,
        "packages_dominated_on_frontier": 0,
        "packages_retained_on_frontier": 0,
        "potential_cutoff_diagnostics": [],
    }


def _roll_baseline(
    current: tuple[Candidate, ...],
    baseline_metrics: dict[str, Any],
    locked: dict[str, Any],
    interaction_map: dict[int, dict],
) -> dict[str, Any]:
    return {
        "package_id": "ROLL_BASELINE",
        "replacements": 0,
        "out": [],
        "in": [],
        "target_cost": baseline_metrics.get("cost"),
        "target_itb": int(locked.get("itb_tenths") or 0),
        "delta_cost": 0,
        "hit_cost": 0,
        "gross_xpts_3": 0.0,
        "gross_xpts_5": 0.0,
        "gross_xpts_10": 0.0,
        "gross_xpts_15": 0.0,
        "net_xpts_3": 0.0,
        "net_xpts_5": 0.0,
        "net_xpts_10": 0.0,
        "net_xpts_15": 0.0,
        "delta_squad_xpts_3": 0.0,
        "delta_squad_xpts_5": 0.0,
        "delta_squad_xpts_10": 0.0,
        "delta_squad_xpts_15": 0.0,
        "delta_best_xi_xpts_5": 0.0,
        "delta_bench_adjusted_utility_5": 0.0,
        "risk_penalty": 0.0,
        "adjusted_best_xi_gain_5": 0.0,
        "adjusted_utility_gain_5": 0.0,
        "projection_uncertainty": 0.0,
        "xmins_uncertainty": 0.0,
        "tactical_uncertainty": 0.0,
        "roster_change_uncertainty": 0.0,
        "price_risk": 0.0,
        "tactical_role_confidence": core._mean([
            core._f((interaction_map.get(player.element) or {}).get("confidence_dimensions", {}).get("player_role_confidence"))
            for player in current
        ]),
        "opponent_matchup_confidence": core._mean([
            core._f((interaction_map.get(player.element) or {}).get("confidence_dimensions", {}).get("Understat_confidence"))
            for player in current
        ]),
        "structural_flexibility": core._structural_flexibility(current, int(locked.get("itb_tenths") or 0)),
        "classification": "ROLL_BASELINE",
        "price_scenario": {"state": "CURRENT_FACT", "price_alone_cannot_authorize_transfer": True},
        "staggered_best_route": None,
        "governance": {"watchlist_candidate_authority": False, "post_transfer_legality_recomputed": True},
    }


def _task_incoming(
    *,
    pools: dict[str, list[Candidate]],
    need: Counter,
    keep: tuple[Candidate, ...],
    budget: int,
    task: dict[str, Any],
    diagnostics: dict[str, Any],
) -> Iterator[tuple[Candidate, ...]]:
    keep_cost = sum(player.cost for player in keep)
    keep_clubs = core._club_counts(keep)
    groups = [
        (position, int(need[position]))
        for position in sorted(need, key=lambda p: (_POSITION_ORDER.get(p, 99), p))
        if int(need[position]) > 0
    ]
    if not groups:
        return

    root_position = str(task.get("root_position"))
    root_count = int(task.get("root_count") or 0)
    if groups[0] != (root_position, root_count):
        raise RuntimeError(
            f"task root contract mismatch expected={groups[0]} actual={(root_position, root_count)}"
        )

    filtered: dict[str, list[Candidate]] = {}
    for position, count in groups:
        rows = sorted(
            (row for row in pools.get(position, []) if keep_cost + row.cost <= budget),
            key=lambda row: row.element,
        )
        filtered[position] = rows
        if len(rows) < count:
            return

    min_group_cost = {
        position: sum(sorted(row.cost for row in filtered[position])[:count])
        for position, count in groups
    }
    suffix_min = [0] * (len(groups) + 1)
    for index in range(len(groups) - 1, -1, -1):
        position, _count = groups[index]
        suffix_min[index] = suffix_min[index + 1] + min_group_cost[position]

    root_start = int(task.get("root_start") or 0)
    root_end = int(task.get("root_end") or 0)
    expected_total = int(task.get("root_combination_count") or 0)
    root_all_count = len(list(combinations(filtered[root_position], root_count))) if root_count == 0 else None
    if root_count == 0:
        if expected_total not in (0, root_all_count):
            raise RuntimeError("zero-count root task has inconsistent cardinality")
        return

    def recurse(
        group_index: int,
        chosen: tuple[Candidate, ...],
        chosen_cost: int,
        clubs: Counter,
    ) -> Iterator[tuple[Candidate, ...]]:
        diagnostics["search_nodes"] += 1
        if keep_cost + chosen_cost + suffix_min[group_index] > budget:
            diagnostics["packages_rejected_by_budget_bound"] += 1
            return
        if group_index >= len(groups):
            yield chosen
            return

        position, count = groups[group_index]
        source = combinations(filtered[position], count)
        if group_index == 0:
            source = islice(source, root_start, root_end)
        for combo in source:
            diagnostics["incoming_combinations_considered"] += 1
            combo_cost = sum(player.cost for player in combo)
            if keep_cost + chosen_cost + combo_cost + suffix_min[group_index + 1] > budget:
                diagnostics["packages_rejected_by_budget"] += 1
                continue
            combo_counts = Counter(player.team_id for player in combo)
            if any(clubs.get(team_id, 0) + combo_counts[team_id] > MAX_PER_CLUB for team_id in combo_counts):
                diagnostics["packages_rejected_by_club_limit"] += 1
                continue
            next_clubs = clubs.copy()
            next_clubs.update(combo_counts)
            yield from recurse(group_index + 1, chosen + combo, chosen_cost + combo_cost, next_clubs)

    yield from recurse(0, tuple(), 0, keep_clubs)


def execute_tasks(
    material: dict[str, Any],
    tasks: list[dict[str, Any]],
    *,
    top_per_size: int,
) -> tuple[dict[str, Any], set[str]]:
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

    baseline_profile = core._keep_profile(current)
    baseline_metrics = core.reference._fast_metrics(current, include_detail=False)
    roll = _roll_baseline(current, baseline_metrics, locked, interaction_map)
    diagnostics = _diagnostics(material)
    frontier_epsilon = core._f(search_cfg.get("frontier_epsilon"), 0.01)
    frontier: list[dict] = []
    core._frontier_insert(frontier, core._compact_for_frontier(roll), frontier_epsilon)
    top_by_k = {k: [] for k in range(1, maximum + 1)}
    best_by_k: dict[str, dict | None] = {str(k): None for k in range(1, maximum + 1)}
    chosen_profile_cache: dict[tuple[int, ...], dict] = {}
    keep_profile_cache: dict[tuple[int, ...], dict] = {}
    position_prefix_cache: dict = {}
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
        keep = tuple(player for player in current if player.element not in set(out_ids))
        need = Counter(player.position for player in outs)
        keep_profile = keep_profile_cache.get(out_ids)
        if keep_profile is None:
            keep_profile = core._keep_profile_from_baseline(baseline_profile, outs)
            keep_profile_cache[out_ids] = keep_profile
        k = len(outs)

        for task in sorted(grouped[out_ids], key=lambda row: (int(row.get("root_start") or 0), str(row.get("task_id")))):
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id in processed:
                raise RuntimeError(f"duplicate/blank shard task execution: {task_id!r}")
            for ins_raw in _task_incoming(
                pools=pools,
                need=need,
                keep=keep,
                budget=budget,
                task=task,
                diagnostics=diagnostics,
            ):
                ins = tuple(sorted(ins_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
                target = keep + ins
                diagnostics["packages_evaluated"] += 1
                in_ids = tuple(player.element for player in ins)
                chosen_profile = chosen_profile_cache.get(in_ids)
                if chosen_profile is None:
                    chosen_profile = core._chosen_profile(ins)
                    chosen_profile_cache[in_ids] = chosen_profile
                target_metrics = core._metrics_from_profiles(
                    keep_profile,
                    chosen_profile,
                    position_prefix_cache=position_prefix_cache,
                )
                row = core._evaluate_package(
                    outs,
                    ins,
                    target,
                    target_metrics,
                    baseline_metrics,
                    locked,
                    policy,
                    interaction_map,
                    price_map,
                    risk_by_element,
                )
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
            processed.add(task_id)

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
        "engine": "v4-full-universe-transfer-package-search-shard-exact-v1",
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
        },
    }
    return result, processed
