from __future__ import annotations

from collections import Counter
from pathlib import Path

from tools.v4_exact_lazy_utility_patch_temp import main as apply_lazy_patch

PATH = Path("src/engines/v4_full_universe_package_search_core.py")


def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    a = source.index(start)
    b = source.index(end, a)
    return source[:a] + replacement.rstrip() + "\n\n" + source[b:]


def main() -> None:
    apply_lazy_patch()
    text = PATH.read_text(encoding="utf-8")

    generator = '''def _incoming_combinations(
    pools: dict[str, list[Candidate]],
    need: Counter,
    keep: tuple[Candidate, ...],
    budget: int,
    diagnostics: dict,
    *,
    prefix_prunable=None,
) -> Iterator[tuple[Candidate, ...]]:
    """Enumerate every non-pruned legal incoming package exactly.

    The recursion is slot-level rather than materializing same-position
    combinations eagerly, so an admissible caller-supplied bound can stop an
    entire subtree only when no completion can reach either the exact top-N or
    the Pareto frontier. No beam, candidate cutoff, or approximate width is
    introduced.
    """
    keep_cost = sum(player.cost for player in keep)
    keep_clubs = _club_counts(keep)
    positions: list[str] = []
    for pos in sorted(need, key=lambda p: (_POSITION_ORDER.get(p, 99), p)):
        positions.extend([pos] * int(need[pos]))

    filtered: dict[str, list[Candidate]] = {}
    min_costs: dict[tuple[str, int], int] = {}
    for pos in set(positions):
        rows = [row for row in pools.get(pos, []) if keep_cost + row.cost <= budget]
        filtered[pos] = sorted(rows, key=lambda row: (-row.x5, -row.x15, row.cost, row.element))
        required = int(need[pos])
        if len(rows) < required:
            return
        cheapest = sorted(row.cost for row in rows)
        for count in range(0, required + 1):
            min_costs[(pos, count)] = sum(cheapest[:count])

    def remaining_counter(slot_index: int) -> Counter:
        return Counter(positions[slot_index:])

    def optimistic_remaining_cost(slot_index: int) -> int:
        remaining = remaining_counter(slot_index)
        return sum(min_costs[(pos, int(count))] for pos, count in remaining.items())

    starts: dict[str, int] = {pos: 0 for pos in filtered}
    clubs = keep_clubs.copy()

    def recurse(slot_index: int, chosen: tuple[Candidate, ...], chosen_cost: int) -> Iterator[tuple[Candidate, ...]]:
        diagnostics["search_nodes"] += 1
        remaining = remaining_counter(slot_index)
        if keep_cost + chosen_cost + optimistic_remaining_cost(slot_index) > budget:
            diagnostics["packages_rejected_by_budget_bound"] += 1
            return
        if prefix_prunable is not None and prefix_prunable(chosen, remaining):
            diagnostics["packages_pruned_by_admissible_branch_bound"] += 1
            return
        if slot_index >= len(positions):
            yield chosen
            return

        pos = positions[slot_index]
        rows = filtered[pos]
        start = starts[pos]
        next_remaining_cost = optimistic_remaining_cost(slot_index + 1)
        for idx in range(start, len(rows)):
            player = rows[idx]
            diagnostics["incoming_combinations_considered"] += 1
            if keep_cost + chosen_cost + player.cost + next_remaining_cost > budget:
                diagnostics["packages_rejected_by_budget"] += 1
                continue
            if clubs.get(player.team_id, 0) >= MAX_PER_CLUB:
                diagnostics["packages_rejected_by_club_limit"] += 1
                continue
            previous_start = starts[pos]
            starts[pos] = idx + 1
            clubs[player.team_id] += 1
            yield from recurse(slot_index + 1, chosen + (player,), chosen_cost + player.cost)
            clubs[player.team_id] -= 1
            starts[pos] = previous_start

    yield from recurse(0, tuple(), 0)


def _build_position_extrema(
    pools: dict[str, list[Candidate]],
    risk_by_element: dict[int, dict],
    max_replacements: int,
) -> dict[tuple[str, int], dict[str, float]]:
    extrema: dict[tuple[str, int], dict[str, float]] = {}
    for pos, rows in pools.items():
        if not rows:
            continue
        for count in range(0, max_replacements + 1):
            if count == 0:
                extrema[(pos, count)] = {
                    "cost_min": 0.0, "x3_max": 0.0, "x5_max": 0.0, "x10_max": 0.0, "x15_max": 0.0,
                    "projection_uncertainty_min": 0.0, "xmins_uncertainty_min": 0.0,
                    "tactical_uncertainty_min": 0.0, "roster_change_uncertainty_min": 0.0,
                    "price_risk_min": 0.0, "tactical_role_confidence_max": 0.0,
                    "opponent_matchup_confidence_max": 0.0,
                }
                continue
            if len(rows) < count:
                continue
            def top_sum(values):
                return sum(sorted(values, reverse=True)[:count])
            def low_sum(values):
                return sum(sorted(values)[:count])
            extrema[(pos, count)] = {
                "cost_min": low_sum([float(player.cost) for player in rows]),
                "x3_max": top_sum([float(player.x3) for player in rows]),
                "x5_max": top_sum([float(player.x5) for player in rows]),
                "x10_max": top_sum([float(player.x10) for player in rows]),
                "x15_max": top_sum([float(player.x15) for player in rows]),
                "projection_uncertainty_min": low_sum([_f(risk_by_element[player.element].get("projection_uncertainty")) for player in rows]),
                "xmins_uncertainty_min": low_sum([_f(risk_by_element[player.element].get("xmins_uncertainty")) for player in rows]),
                "tactical_uncertainty_min": low_sum([_f(risk_by_element[player.element].get("tactical_uncertainty")) for player in rows]),
                "roster_change_uncertainty_min": low_sum([_f(risk_by_element[player.element].get("roster_change_uncertainty")) for player in rows]),
                "price_risk_min": low_sum([_f(risk_by_element[player.element].get("price_risk"), 0.2) for player in rows]),
                "tactical_role_confidence_max": top_sum([_f(risk_by_element[player.element].get("tactical_role_confidence")) for player in rows]),
                "opponent_matchup_confidence_max": top_sum([_f(risk_by_element[player.element].get("opponent_matchup_confidence")) for player in rows]),
            }
    return extrema


def _admissible_prefix_bounds(
    chosen: tuple[Candidate, ...],
    remaining_need: Counter,
    *,
    outs: tuple[Candidate, ...],
    outgoing_risk: dict,
    risk_by_element: dict[int, dict],
    extrema: dict[tuple[str, int], dict[str, float]],
    baseline_metrics: dict,
    locked: dict,
    policy: dict,
    k: int,
) -> tuple[tuple[float, ...], float]:
    incoming = {
        "cost_min": sum(float(player.cost) for player in chosen),
        "x3_max": sum(float(player.x3) for player in chosen),
        "x5_max": sum(float(player.x5) for player in chosen),
        "x10_max": sum(float(player.x10) for player in chosen),
        "x15_max": sum(float(player.x15) for player in chosen),
        "projection_uncertainty_min": 0.0,
        "xmins_uncertainty_min": 0.0,
        "tactical_uncertainty_min": 0.0,
        "roster_change_uncertainty_min": 0.0,
        "price_risk_min": 0.0,
        "tactical_role_confidence_max": 0.0,
        "opponent_matchup_confidence_max": 0.0,
    }
    for player in chosen:
        risk = risk_by_element[player.element]
        incoming["projection_uncertainty_min"] += _f(risk.get("projection_uncertainty"))
        incoming["xmins_uncertainty_min"] += _f(risk.get("xmins_uncertainty"))
        incoming["tactical_uncertainty_min"] += _f(risk.get("tactical_uncertainty"))
        incoming["roster_change_uncertainty_min"] += _f(risk.get("roster_change_uncertainty"))
        incoming["price_risk_min"] += _f(risk.get("price_risk"), 0.2)
        incoming["tactical_role_confidence_max"] += _f(risk.get("tactical_role_confidence"))
        incoming["opponent_matchup_confidence_max"] += _f(risk.get("opponent_matchup_confidence"))
    for pos, count_raw in remaining_need.items():
        count = int(count_raw)
        bound = extrema[(pos, count)]
        for key, value in bound.items():
            incoming[key] += value

    out_x3 = sum(float(player.x3) for player in outs)
    out_x5 = sum(float(player.x5) for player in outs)
    out_x10 = sum(float(player.x10) for player in outs)
    out_x15 = sum(float(player.x15) for player in outs)
    hit = float(_hit_cost(k, locked, policy))
    divisor = float(max(1, k))

    def delta_min(key: str) -> float:
        return max(0.0, incoming[key] / divisor - _f(outgoing_risk.get(key.replace("_min", ""))))

    itb_max = int(locked.get("itb_tenths") or 0) + sum(player.cost for player in outs) - int(incoming["cost_min"])
    vector = (
        incoming["x3_max"] - out_x3 - hit,
        incoming["x5_max"] - out_x5 - hit,
        incoming["x10_max"] - out_x10 - hit,
        incoming["x15_max"] - out_x15 - hit,
        _structural_flexibility_exact_size(15, itb_max),
        min(1.0, incoming["tactical_role_confidence_max"] / divisor),
        min(1.0, incoming["opponent_matchup_confidence_max"] / divisor),
        -hit,
        -delta_min("xmins_uncertainty_min"),
        -delta_min("projection_uncertainty_min"),
        -delta_min("tactical_uncertainty_min"),
        -(incoming["price_risk_min"] / divisor),
        -delta_min("roster_change_uncertainty_min"),
    )
    target_squad_x5_upper = _f(baseline_metrics.get("squad_xpts_5")) + incoming["x5_max"] - out_x5
    utility_upper = target_squad_x5_upper - _f(baseline_metrics.get("bench_adjusted_utility_5")) - hit
    return vector, utility_upper
'''
    text = replace_between(text, "def _incoming_combinations(", "def _price_rows(", generator)

    old_diag = '        "packages_retained_on_frontier": 0,\n        "potential_cutoff_diagnostics": [],'
    new_diag = '        "packages_retained_on_frontier": 0,\n        "packages_pruned_by_admissible_branch_bound": 0,\n        "potential_cutoff_diagnostics": [],'
    if old_diag not in text:
        raise SystemExit("diagnostic insertion target missing")
    text = text.replace(old_diag, new_diag, 1)

    old_cache = '''    incoming_risk_cache: dict[tuple[int, ...], dict] = {}\n    exact_row_cache: dict[str, dict] = {}\n    position_prefix_cache: dict = {}'''
    new_cache = '''    incoming_risk_cache: dict[tuple[int, ...], dict] = {}\n    exact_row_cache: dict[str, dict] = {}\n    position_prefix_cache: dict = {}\n    position_extrema = _build_position_extrema(pools, risk_by_element, max_replacements)'''
    if old_cache not in text:
        raise SystemExit("lazy cache target missing")
    text = text.replace(old_cache, new_cache, 1)

    old_loop = '''            outgoing_risk = _risk_aggregate(outs, risk_by_element)\n            for ins_raw in _incoming_combinations(pools, need, keep, derived_budget, diagnostics):'''
    new_loop = '''            outgoing_risk = _risk_aggregate(outs, risk_by_element)\n\n            def prefix_prunable(chosen_prefix, remaining_need):\n                bound_vec, utility_upper = _admissible_prefix_bounds(\n                    chosen_prefix, remaining_need,\n                    outs=outs, outgoing_risk=outgoing_risk, risk_by_element=risk_by_element,\n                    extrema=position_extrema, baseline_metrics=baseline_metrics, locked=locked, policy=policy, k=k,\n                )\n                frontier_blocked = any(\n                    _dominates_vector(_frontier_tuple(incumbent), bound_vec, frontier_epsilon)\n                    for incumbent in frontier\n                )\n                if not frontier_blocked or len(top_by_k[k]) < top_per_size:\n                    return False\n                threshold = _f(top_by_k[k][-1].get("adjusted_utility_gain_5"), float("-inf"))\n                top_blocked = utility_upper + 1e-12 < threshold\n                return top_blocked\n\n            for ins_raw in _incoming_combinations(\n                pools, need, keep, derived_budget, diagnostics, prefix_prunable=prefix_prunable,\n            ):'''
    if old_loop not in text:
        raise SystemExit("search-loop target missing")
    text = text.replace(old_loop, new_loop, 1)

    old_gov = '            "expensive_evidence_materialized_only_after_exact_selection": True,\n'
    new_gov = '            "expensive_evidence_materialized_only_after_exact_selection": True,\n            "admissible_branch_bound_preserves_exact_top_and_frontier": True,\n            "branch_pruning_requires_frontier_and_top_impossibility": True,\n'
    if old_gov not in text:
        raise SystemExit("governance target missing")
    text = text.replace(old_gov, new_gov, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
