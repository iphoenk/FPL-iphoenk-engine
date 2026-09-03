from __future__ import annotations

from pathlib import Path

PATH = Path("src/engines/v4_full_universe_package_search_core.py")


def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    a = source.index(start)
    b = source.index(end, a)
    return source[:a] + replacement.rstrip() + "\n\n" + source[b:]


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    old_order = '        filtered[pos] = sorted(rows, key=lambda row: row.element)'
    new_order = '        filtered[pos] = sorted(rows, key=lambda row: (-row.x5, -row.x15, row.cost, row.element))'
    if old_order not in text:
        raise SystemExit("incoming ordering target missing")
    text = text.replace(old_order, new_order, 1)

    structural = '''def _structural_flexibility(target: tuple[Candidate, ...], itb: int) -> float:
    # All callers pass a legal target squad. For a legal 15-player squad with
    # max three per club, aggregate open club capacity is 20*3 - 15 = 45.
    open_club_capacity = max(0, 20 * MAX_PER_CLUB - len(target))
    return round(min(1.0, 0.55 * min(1.0, max(0, itb) / 20.0) + 0.45 * min(1.0, open_club_capacity / 45.0)), 4)


def _structural_flexibility_exact_size(squad_size: int, itb: int) -> float:
    open_club_capacity = max(0, 20 * MAX_PER_CLUB - int(squad_size))
    return round(min(1.0, 0.55 * min(1.0, max(0, itb) / 20.0) + 0.45 * min(1.0, open_club_capacity / 45.0)), 4)
'''
    text = replace_between(text, "def _structural_flexibility(", "def _frontier_vector(", structural)

    frontier = '''def _frontier_tuple(row: dict) -> tuple[float, ...]:
    # Normalize every governed frontier dimension to maximize. Cached tuples
    # remove repeated dict construction in the exact streaming Pareto scan.
    cached = row.get("_frontier_vec")
    if cached is not None:
        return tuple(cached)
    return (
        _f(row.get("net_xpts_3")),
        _f(row.get("net_xpts_5")),
        _f(row.get("net_xpts_10")),
        _f(row.get("net_xpts_15")),
        _f(row.get("structural_flexibility")),
        _f(row.get("tactical_role_confidence")),
        _f(row.get("opponent_matchup_confidence")),
        -_f(row.get("hit_cost")),
        -_f(row.get("xmins_uncertainty")),
        -_f(row.get("projection_uncertainty")),
        -_f(row.get("tactical_uncertainty")),
        -_f(row.get("price_risk")),
        -_f(row.get("roster_change_uncertainty")),
    )


def _dominates_vector(left: tuple[float, ...], right: tuple[float, ...], epsilon: float) -> bool:
    strict = False
    for a, b in zip(left, right):
        if a + epsilon < b:
            return False
        if a > b + epsilon:
            strict = True
    return strict


def _dominates_package(left: dict, right: dict, epsilon: float) -> bool:
    return _dominates_vector(_frontier_tuple(left), _frontier_tuple(right), epsilon)


def _frontier_insert(frontier: list[dict], row: dict, epsilon: float) -> tuple[bool, int]:
    row_vec = _frontier_tuple(row)
    survivors: list[dict] = []
    removed = 0
    for incumbent in frontier:
        incumbent_vec = _frontier_tuple(incumbent)
        if _dominates_vector(incumbent_vec, row_vec, epsilon):
            return False, 0
        if _dominates_vector(row_vec, incumbent_vec, epsilon):
            removed += 1
        else:
            survivors.append(incumbent)
    survivors.append(row)
    frontier[:] = survivors
    return True, removed


def _compact_for_frontier(row: dict) -> dict:
    keys = (
        "package_id", "replacements", "target_cost", "target_itb", "hit_cost",
        "net_xpts_3", "net_xpts_5", "net_xpts_10", "net_xpts_15",
        "xmins_uncertainty", "projection_uncertainty", "tactical_uncertainty",
        "price_risk", "roster_change_uncertainty", "tactical_role_confidence",
        "opponent_matchup_confidence", "structural_flexibility",
    )
    compact = {key: row.get(key) for key in keys}
    compact["_out_ids"] = tuple(row.get("_out_ids") or ())
    compact["_in_ids"] = tuple(row.get("_in_ids") or ())
    compact["_frontier_vec"] = _frontier_tuple(compact)
    return compact
'''
    text = replace_between(text, "def _frontier_vector(", "def _rank(", frontier)

    evaluation = '''def _risk_aggregate(players: tuple[Candidate, ...], risk_by_element: dict[int, dict]) -> dict:
    rows = [risk_by_element[player.element] for player in players]
    count = max(1, len(rows))

    def avg(key: str, default: float = 0.0) -> float:
        return sum(_f(row.get(key), default) for row in rows) / count

    return {
        "projection_uncertainty": avg("projection_uncertainty"),
        "xmins_uncertainty": avg("xmins_uncertainty"),
        "tactical_uncertainty": avg("tactical_uncertainty"),
        "roster_change_uncertainty": avg("roster_change_uncertainty"),
        "price_risk": avg("price_risk", 0.2),
        "tactical_role_confidence": avg("tactical_role_confidence"),
        "opponent_matchup_confidence": avg("opponent_matchup_confidence"),
    }


def _cheap_package_row(
    outs: tuple[Candidate, ...],
    ins: tuple[Candidate, ...],
    baseline_metrics: dict,
    locked: dict,
    policy: dict,
    outgoing_risk: dict,
    incoming_risk: dict,
) -> dict:
    k = len(ins)
    hit = _hit_cost(k, locked, policy)
    dx3 = sum(player.x3 for player in ins) - sum(player.x3 for player in outs)
    dx5 = sum(player.x5 for player in ins) - sum(player.x5 for player in outs)
    dx10 = sum(player.x10 for player in ins) - sum(player.x10 for player in outs)
    dx15 = sum(player.x15 for player in ins) - sum(player.x15 for player in outs)
    risks = {
        "projection_uncertainty": round(max(0.0, incoming_risk["projection_uncertainty"] - outgoing_risk["projection_uncertainty"]), 4),
        "xmins_uncertainty": round(max(0.0, incoming_risk["xmins_uncertainty"] - outgoing_risk["xmins_uncertainty"]), 4),
        "tactical_uncertainty": round(max(0.0, incoming_risk["tactical_uncertainty"] - outgoing_risk["tactical_uncertainty"]), 4),
        "roster_change_uncertainty": round(max(0.0, incoming_risk["roster_change_uncertainty"] - outgoing_risk["roster_change_uncertainty"]), 4),
        "price_risk": round(incoming_risk["price_risk"], 4),
        "tactical_role_confidence": round(incoming_risk["tactical_role_confidence"], 4),
        "opponent_matchup_confidence": round(incoming_risk["opponent_matchup_confidence"], 4),
    }
    risk_penalty = (
        0.35 * risks["projection_uncertainty"]
        + 0.30 * risks["xmins_uncertainty"]
        + 0.25 * risks["tactical_uncertainty"]
        + 0.20 * risks["roster_change_uncertainty"]
    )
    incoming_cost = sum(player.cost for player in ins)
    outgoing_cost = sum(player.cost for player in outs)
    itb = int(locked.get("itb_tenths") or 0) + outgoing_cost - incoming_cost
    target_cost = int(baseline_metrics.get("cost") or 0) + incoming_cost - outgoing_cost
    target_squad_x5 = _f(baseline_metrics.get("squad_xpts_5")) + dx5
    # bench-adjusted utility = 0.88*XI + 0.12*squad <= squad total.
    # Risk and hit penalties are non-negative, so this is a conservative exact
    # upper bound for the primary _rank dimension.
    utility_upper = target_squad_x5 - _f(baseline_metrics.get("bench_adjusted_utility_5")) - hit - risk_penalty
    row = {
        "package_id": _package_id(outs, ins),
        "replacements": k,
        "_out_ids": tuple(player.element for player in outs),
        "_in_ids": tuple(player.element for player in ins),
        "target_cost": target_cost,
        "target_itb": itb,
        "delta_cost": incoming_cost - outgoing_cost,
        "hit_cost": hit,
        "gross_xpts_3": round(dx3, 3),
        "gross_xpts_5": round(dx5, 3),
        "gross_xpts_10": round(dx10, 3),
        "gross_xpts_15": round(dx15, 3),
        "net_xpts_3": round(dx3 - hit, 3),
        "net_xpts_5": round(dx5 - hit, 3),
        "net_xpts_10": round(dx10 - hit, 3),
        "net_xpts_15": round(dx15 - hit, 3),
        "delta_squad_xpts_3": round(dx3, 3),
        "delta_squad_xpts_5": round(dx5, 3),
        "delta_squad_xpts_10": round(dx10, 3),
        "delta_squad_xpts_15": round(dx15, 3),
        "risk_penalty": round(risk_penalty, 4),
        "projection_uncertainty": risks["projection_uncertainty"],
        "xmins_uncertainty": risks["xmins_uncertainty"],
        "tactical_uncertainty": risks["tactical_uncertainty"],
        "roster_change_uncertainty": risks["roster_change_uncertainty"],
        "price_risk": risks["price_risk"],
        "tactical_role_confidence": risks["tactical_role_confidence"],
        "opponent_matchup_confidence": risks["opponent_matchup_confidence"],
        "structural_flexibility": _structural_flexibility_exact_size(15, itb),
        "utility_upper_bound_5": round(utility_upper, 6),
        "exact_utility_materialized": False,
    }
    row["_frontier_vec"] = _frontier_tuple(row)
    return row


def _exactify_package(row: dict, target_metrics: dict, baseline_metrics: dict) -> dict:
    out = dict(row)
    dxi = _f(target_metrics.get("best_xi_xpts_5")) - _f(baseline_metrics.get("best_xi_xpts_5"))
    du = _f(target_metrics.get("bench_adjusted_utility_5")) - _f(baseline_metrics.get("bench_adjusted_utility_5"))
    hit = _f(out.get("hit_cost"))
    risk_penalty = _f(out.get("risk_penalty"))
    adjusted_xi = dxi - hit - risk_penalty
    adjusted_util = du - hit - risk_penalty
    out.update({
        "delta_best_xi_xpts_5": round(dxi, 3),
        "delta_bench_adjusted_utility_5": round(du, 3),
        "adjusted_best_xi_gain_5": round(adjusted_xi, 3),
        "adjusted_utility_gain_5": round(adjusted_util, 3),
        "classification": reference.package_class(adjusted_xi, adjusted_util, int(out.get("replacements") or 0)),
        "exact_utility_materialized": True,
    })
    return out


def _can_enter_exact_top(row: dict, current_top: list[dict], limit: int) -> bool:
    if len(current_top) < limit:
        return True
    threshold = _f(current_top[-1].get("adjusted_utility_gain_5"), float("-inf"))
    # Strictly lower admissible upper bound cannot enter. Equality still requires
    # exact materialization because later _rank tie-breakers may decide.
    return _f(row.get("utility_upper_bound_5"), float("inf")) + 1e-12 >= threshold
'''
    text = replace_between(text, "def _evaluate_package(", "def _finalize_package(", evaluation)

    old_cache = '''    keep_profile_cache: dict[tuple[int, ...], dict] = {}\n    chosen_profile_cache: dict[tuple[int, ...], dict] = {}\n    position_prefix_cache: dict = {}'''
    new_cache = '''    keep_profile_cache: dict[tuple[int, ...], dict] = {}\n    chosen_profile_cache: dict[tuple[int, ...], dict] = {}\n    incoming_risk_cache: dict[tuple[int, ...], dict] = {}\n    exact_row_cache: dict[str, dict] = {}\n    position_prefix_cache: dict = {}\n    diagnostics["exact_utility_evaluations"] = 0\n    diagnostics["exact_utility_pruned_by_admissible_bound"] = 0'''
    if old_cache not in text:
        raise SystemExit("cache target missing")
    text = text.replace(old_cache, new_cache, 1)

    start = '            for ins_raw in _incoming_combinations(pools, need, keep, derived_budget, diagnostics):\n'
    end = '\n    frontier.sort(key=_rank, reverse=True)'
    a = text.index(start)
    b = text.index(end, a)
    loop = '''            outgoing_risk = _risk_aggregate(outs, risk_by_element)
            for ins_raw in _incoming_combinations(pools, need, keep, derived_budget, diagnostics):
                ins = tuple(sorted(ins_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
                diagnostics["packages_evaluated"] += 1
                in_ids = tuple(player.element for player in ins)
                incoming_risk = incoming_risk_cache.get(in_ids)
                if incoming_risk is None:
                    incoming_risk = _risk_aggregate(ins, risk_by_element)
                    incoming_risk_cache[in_ids] = incoming_risk
                cheap = _cheap_package_row(
                    outs, ins, baseline_metrics, locked, policy, outgoing_risk, incoming_risk,
                )

                compact = _compact_for_frontier(cheap)
                retained, removed = _frontier_insert(frontier, compact, frontier_epsilon)
                if not retained:
                    diagnostics["packages_dominated_on_frontier"] += 1
                elif removed:
                    diagnostics["packages_dominated_on_frontier"] += removed

                if not _can_enter_exact_top(cheap, top_by_k[k], top_per_size):
                    diagnostics["exact_utility_pruned_by_admissible_bound"] += 1
                    continue

                chosen_profile = chosen_profile_cache.get(in_ids)
                if chosen_profile is None:
                    chosen_profile = _chosen_profile(ins)
                    chosen_profile_cache[in_ids] = chosen_profile
                target_metrics = _metrics_from_profiles(
                    keep_profile, chosen_profile, position_prefix_cache=position_prefix_cache,
                )
                exact = _exactify_package(cheap, target_metrics, baseline_metrics)
                diagnostics["exact_utility_evaluations"] += 1
                exact_row_cache[exact["package_id"]] = exact
                _retain_top(top_by_k[k], exact, top_per_size)
'''
    text = text[:a] + loop + text[b:]

    old_tail = '''    frontier.sort(key=_rank, reverse=True)\n    diagnostics["packages_retained_on_frontier"] = len(frontier)\n\n    finalized_cache: dict[str, dict] = {}'''
    new_tail = '''    # Frontier membership is exact from additive projection/risk dimensions.
    # Materialize expensive XI/bench utility only for Pareto survivors not already
    # exactified during admissible top-N screening.
    def exactify_retained(row: dict) -> dict:
        package_id = str(row.get("package_id") or "")
        if package_id == "ROLL_BASELINE":
            return roll
        cached = exact_row_cache.get(package_id)
        if cached is not None:
            return cached
        outs = tuple(by_id[element] for element in row.get("_out_ids") or ())
        ins = tuple(by_id[element] for element in row.get("_in_ids") or ())
        out_ids = tuple(sorted(player.element for player in outs))
        keep_profile = keep_profile_cache.get(out_ids)
        if keep_profile is None:
            keep_profile = _keep_profile_from_baseline(baseline_profile, outs)
            keep_profile_cache[out_ids] = keep_profile
        in_ids = tuple(player.element for player in ins)
        chosen_profile = chosen_profile_cache.get(in_ids)
        if chosen_profile is None:
            chosen_profile = _chosen_profile(ins)
            chosen_profile_cache[in_ids] = chosen_profile
        target_metrics = _metrics_from_profiles(
            keep_profile, chosen_profile, position_prefix_cache=position_prefix_cache,
        )
        exact = _exactify_package(row, target_metrics, baseline_metrics)
        exact_row_cache[package_id] = exact
        diagnostics["exact_utility_evaluations"] += 1
        return exact

    frontier = [exactify_retained(row) for row in frontier]
    frontier.sort(key=_rank, reverse=True)
    diagnostics["packages_retained_on_frontier"] = len(frontier)
    diagnostics["exact_utility_fraction"] = round(
        diagnostics["exact_utility_evaluations"] / max(1, diagnostics["packages_evaluated"]), 6
    )
    best_by_k = {str(k): (top_by_k[k][0] if top_by_k[k] else None) for k in range(1, max_replacements + 1)}

    finalized_cache: dict[str, dict] = {}'''
    if old_tail not in text:
        raise SystemExit("tail target missing")
    text = text.replace(old_tail, new_tail, 1)

    old_governance = '            "expensive_evidence_materialized_only_after_exact_selection": True,\n'
    new_governance = (
        old_governance
        + '            "utility_pruning_uses_admissible_upper_bound": True,\n'
        + '            "admissible_bound_preserves_rank_ties": True,\n'
    )
    if old_governance not in text:
        raise SystemExit("governance target missing")
    text = text.replace(old_governance, new_governance, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
