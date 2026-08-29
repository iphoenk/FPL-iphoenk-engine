from __future__ import annotations

from collections import Counter
from heapq import heappush, heapreplace
from itertools import combinations

from src.engines import v4_wc_package_audit as base
from src.engines.v4_optimizer_primitives import gw_value as _gw_value
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, reconcile_owned_costs, validate_squad


def _prefix(values) -> list[float]:
    out = [0.0]
    for value in values:
        out.append(out[-1] + value)
    return out


def _club_signature(players) -> int:
    signature = 0
    for player in players:
        signature += 1 << ((player.team_id - 1) * 2)
    return signature


def _keep_profile(players) -> dict:
    ps = list(players)
    by_pos = {pos: [p for p in ps if p.position == pos] for pos in POSITION_COUNTS}
    gw_sorted = []
    gw_prefix = []
    for index in range(5):
        sorted_by_pos = {
            pos: sorted((_gw_value(p, index) for p in by_pos[pos]), reverse=True)
            for pos in POSITION_COUNTS
        }
        gw_sorted.append(sorted_by_pos)
        gw_prefix.append({pos: _prefix(values) for pos, values in sorted_by_pos.items()})
    objective_terms = tuple(p.objective for p in ps)
    return {
        "cost": sum(p.cost for p in ps),
        "objective": sum(objective_terms),
        "objective_terms": objective_terms,
        "objective_elements": tuple((p.element, p.objective) for p in ps),
        "x3": sum(p.x3 for p in ps),
        "x5": sum(p.x5 for p in ps),
        "x10": sum(p.x10 for p in ps),
        "x15": sum(p.x15 for p in ps),
        "gw_total": [sum(_gw_value(p, i) for p in ps) for i in range(5)],
        "gw_sorted": gw_sorted,
        "gw_prefix": gw_prefix,
    }


def _keep_profile_from_baseline(baseline: dict, outs) -> dict:
    """Derive an OUT-set profile while preserving reference float order exactly.

    CPython 3.12 gives ``sum(float_iterable)`` improved numerical semantics, so a
    baseline-total-minus-outs shortcut is not guaranteed to round identically to the
    reference target sum. Preserve the ordered objective terms and let ``sum`` see the
    exact same keep sequence that the reference audit sees.
    """
    outs = tuple(outs)
    out_ids = {p.element for p in outs}
    objective_terms = tuple(
        value for element, value in baseline["objective_elements"] if element not in out_ids
    )
    out_by_pos = {pos: [p for p in outs if p.position == pos] for pos in POSITION_COUNTS}
    gw_sorted = []
    gw_prefix = []
    for index in range(5):
        sorted_by_pos = {}
        prefix_by_pos = {}
        for pos in POSITION_COUNTS:
            removals = out_by_pos[pos]
            if not removals:
                sorted_by_pos[pos] = baseline["gw_sorted"][index][pos]
                prefix_by_pos[pos] = baseline["gw_prefix"][index][pos]
                continue
            values = list(baseline["gw_sorted"][index][pos])
            for player in removals:
                values.remove(_gw_value(player, index))
            sorted_by_pos[pos] = values
            prefix_by_pos[pos] = _prefix(values)
        gw_sorted.append(sorted_by_pos)
        gw_prefix.append(prefix_by_pos)
    return {
        "cost": baseline["cost"] - sum(p.cost for p in outs),
        "objective": sum(objective_terms),
        "objective_terms": objective_terms,
        "x3": baseline["x3"] - sum(p.x3 for p in outs),
        "x5": baseline["x5"] - sum(p.x5 for p in outs),
        "x10": baseline["x10"] - sum(p.x10 for p in outs),
        "x15": baseline["x15"] - sum(p.x15 for p in outs),
        "gw_total": [
            baseline["gw_total"][index] - sum(_gw_value(p, index) for p in outs)
            for index in range(5)
        ],
        "gw_sorted": gw_sorted,
        "gw_prefix": gw_prefix,
    }


def _chosen_profile(chosen) -> dict:
    ps = tuple(chosen)
    gw_by_pos = []
    for index in range(5):
        row = {pos: [] for pos in POSITION_COUNTS}
        for player in ps:
            row[player.position].append(_gw_value(player, index))
        gw_by_pos.append(row)
    objective_terms = tuple(p.objective for p in ps)
    return {
        "cost": sum(p.cost for p in ps),
        "objective": sum(objective_terms),
        "objective_terms": objective_terms,
        "x3": sum(p.x3 for p in ps),
        "x5": sum(p.x5 for p in ps),
        "x10": sum(p.x10 for p in ps),
        "x15": sum(p.x15 for p in ps),
        "gw_total": [sum(_gw_value(p, i) for p in ps) for i in range(5)],
        "gw_by_pos": gw_by_pos,
    }


def _best_xi_from_prefix(prefix: dict[str, list[float]]) -> float:
    gk = prefix["GK"][1]
    dp = prefix["DEF"]
    mp = prefix["MID"]
    fp = prefix["FWD"]
    return max(
        gk + dp[3] + mp[4] + fp[3],
        gk + dp[3] + mp[5] + fp[2],
        gk + dp[4] + mp[3] + fp[3],
        gk + dp[4] + mp[4] + fp[2],
        gk + dp[4] + mp[5] + fp[1],
        gk + dp[5] + mp[2] + fp[3],
        gk + dp[5] + mp[3] + fp[2],
        gk + dp[5] + mp[4] + fp[1],
    )


def _metrics_from_profiles(profile: dict, chosen_profile: dict) -> dict:
    xi5 = 0.0
    utility5 = 0.0
    for index in range(5):
        prefixes = {}
        additions = chosen_profile["gw_by_pos"][index]
        for pos in POSITION_COUNTS:
            if additions[pos]:
                merged = sorted(profile["gw_sorted"][index][pos] + additions[pos], reverse=True)
                prefixes[pos] = _prefix(merged)
            else:
                prefixes[pos] = profile["gw_prefix"][index][pos]
        xi = _best_xi_from_prefix(prefixes)
        total = profile["gw_total"][index] + chosen_profile["gw_total"][index]
        xi5 += xi
        utility5 += xi + .12 * (total - xi)
    objective = sum(profile["objective_terms"] + chosen_profile["objective_terms"])
    return {
        "cost": profile["cost"] + chosen_profile["cost"],
        "objective": round(objective, 4),
        "squad_xpts_3": round(profile["x3"] + chosen_profile["x3"], 2),
        "squad_xpts_5": round(profile["x5"] + chosen_profile["x5"], 2),
        "squad_xpts_10": round(profile["x10"] + chosen_profile["x10"], 2),
        "squad_xpts_15": round(profile["x15"] + chosen_profile["x15"], 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(utility5, 2),
    }


def _small_candidate_template(need: Counter, bp: dict) -> list[tuple]:
    pools = [list(combinations(bp[pos], count)) for pos, count in need.items()]
    states = [tuple()]
    for comboset in pools:
        states = [state + combo for state in states for combo in comboset if len({p.element for p in state + combo}) == len(state + combo)]
    scored = [(sum(p.objective - .12 * p.uncertainty for p in chosen), chosen) for chosen in states]
    scored.sort(key=lambda row: row[0], reverse=True)
    return [chosen for _, chosen in scored]


def _legal_small_candidates(template: list[tuple], keep_cost: int, clubs: int, budget: int, k: int) -> list[tuple]:
    cap = 16 if k == 1 else 30
    legal = []
    for chosen in template:
        if keep_cost + sum(p.cost for p in chosen) > budget:
            continue
        signature = clubs
        ok = True
        for player in chosen:
            shift = (player.team_id - 1) * 2
            if ((signature >> shift) & 0b11) >= MAX_PER_CLUB:
                ok = False
                break
            signature += 1 << shift
        if ok:
            legal.append(chosen)
            if len(legal) >= cap:
                break
    return legal


def _bounded_candidate_states(need: Counter, bp: dict, keep_cost: int, clubs: int, budget: int, beam: int) -> list[tuple]:
    """Exact bounded-beam semantics with precomputed baseline cost/club signature."""
    slots = []
    for pos, count in need.items():
        slots += [pos] * count
    states = [(tuple(), keep_cost, clubs, 0.0)]
    for pos in slots:
        nxt = []
        for chosen, cost, signature, score in states:
            used = {p.element for p in chosen}
            for player in bp[pos]:
                shift = (player.team_id - 1) * 2
                if player.element in used or cost + player.cost > budget or ((signature >> shift) & 0b11) >= MAX_PER_CLUB:
                    continue
                nxt.append((
                    chosen + (player,),
                    cost + player.cost,
                    signature + (1 << shift),
                    score + player.objective - .12 * player.uncertainty,
                ))
        nxt.sort(key=lambda state: (state[3], -state[1]), reverse=True)
        dedup, seen = [], set()
        for state in nxt:
            key = tuple(sorted(p.element for p in state[0]))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(state)
            if len(dedup) >= beam:
                break
        states = dedup
        if not states:
            break
    return [state[0] for state in states]


def _materialize_package(compact: tuple, k: int, basecost: int, budget: int) -> dict:
    outs, chosen, tm, dxi, du, risk_delta, risk_penalty, adj_xi, adj_util = compact
    return {
        "replacements": k,
        "out": [base.payload(p) for p in sorted(outs, key=lambda x: (x.position, x.name))],
        "in": [base.payload(p) for p in sorted(chosen, key=lambda x: (x.position, x.name))],
        "target_cost": tm["cost"],
        "target_itb": budget - tm["cost"],
        "delta_cost": tm["cost"] - basecost,
        "delta_objective": round(tm["objective"] - 0.0, 4),
        "delta_squad_xpts_3": tm["squad_xpts_3"],
        "delta_squad_xpts_5": tm["squad_xpts_5"],
        "delta_squad_xpts_10": tm["squad_xpts_10"],
        "delta_squad_xpts_15": tm["squad_xpts_15"],
        "delta_best_xi_xpts_5": round(dxi, 2),
        "delta_bench_adjusted_utility_5": round(du, 2),
        "risk_delta": round(risk_delta, 3),
        "risk_penalty": round(risk_penalty, 3),
        "adjusted_best_xi_gain_5": round(adj_xi, 2),
        "adjusted_utility_gain_5": round(adj_util, 2),
        "classification": base.package_class(adj_xi, adj_util, k),
    }


def audit_packages_from_candidates_fast(
    cands,
    locked,
    max_replacements: int = 4,
    budget: int | None = None,
    per_position_frontier: int = 7,
    top_per_size: int = 8,
    beam_size: int = 28,
) -> dict:
    cands, affordability = reconcile_owned_costs(cands, locked)
    derived_budget = int(affordability["available_budget_tenths"])
    budget = derived_budget if budget is None else int(budget)
    if budget != derived_budget:
        raise RuntimeError(f"budget override {budget} disagrees with reconciled sell value {derived_budget}")

    by = {p.element: p for p in cands}
    ids = {int(x["element"]) for x in locked.get("players", [])}
    missing = ids - set(by)
    if missing:
        raise RuntimeError(f"baseline players missing from candidate universe: {sorted(missing)}")
    cur = [by[element] for element in ids]
    ok, reason = validate_squad(cur, budget)
    if not ok:
        raise RuntimeError(f"baseline invalid: {reason}")

    fr = base.frontier(cands, ids, per_position_frontier)
    bp = {pos: [p for p in fr if p.position == pos] for pos in POSITION_COUNTS}
    cm = base._fast_metrics(cur, include_detail=True)
    basecost = cm["cost"]
    baseline_profile = _keep_profile(cur)
    baseline_clubs = _club_signature(cur)
    results: dict[str, list[dict]] = {}
    keep_profiles = 0
    evaluated = 0
    small_templates: dict[tuple, list[tuple]] = {}
    small_template_hits = 0
    bounded_states: dict[tuple, list[tuple]] = {}
    bounded_state_hits = 0
    chosen_profiles: dict[tuple[int, ...], dict] = {}
    chosen_profile_hits = 0

    for k in range(1, max_replacements + 1):
        heap: list[tuple] = []
        sequence = 0
        for outs in combinations(cur, k):
            need = Counter(p.position for p in outs)
            if any(len(bp[pos]) < count for pos, count in need.items()):
                continue
            out_unc = sum(p.uncertainty for p in outs)
            keep_cost = basecost - sum(p.cost for p in outs)
            keep_clubs = baseline_clubs
            for player in outs:
                keep_clubs -= 1 << ((player.team_id - 1) * 2)
            profile = _keep_profile_from_baseline(baseline_profile, outs)
            keep_profiles += 1
            need_key = tuple(need.items())

            if k <= 2:
                template = small_templates.get(need_key)
                if template is None:
                    template = _small_candidate_template(need, bp)
                    small_templates[need_key] = template
                else:
                    small_template_hits += 1
                candidate_states = _legal_small_candidates(template, keep_cost, keep_clubs, budget, k)
            else:
                state_key = (need_key, keep_cost, keep_clubs)
                candidate_states = bounded_states.get(state_key)
                if candidate_states is None:
                    candidate_states = _bounded_candidate_states(need, bp, keep_cost, keep_clubs, budget, beam_size)
                    bounded_states[state_key] = candidate_states
                else:
                    bounded_state_hits += 1

            for chosen in candidate_states:
                if len(chosen) != k:
                    continue
                chosen_key = tuple(p.element for p in chosen)
                chosen_profile = chosen_profiles.get(chosen_key)
                if chosen_profile is None:
                    chosen_profile = _chosen_profile(chosen)
                    chosen_profiles[chosen_key] = chosen_profile
                else:
                    chosen_profile_hits += 1
                tm = _metrics_from_profiles(profile, chosen_profile)
                evaluated += 1
                dxi = tm["best_xi_xpts_5"] - cm["best_xi_xpts_5"]
                du = tm["bench_adjusted_utility_5"] - cm["bench_adjusted_utility_5"]
                risk_delta = sum(p.uncertainty for p in chosen) - out_unc
                risk_penalty = max(0, risk_delta) * .35 + max(0, k - 1) * .20
                adj_xi = dxi - risk_penalty
                adj_util = du - risk_penalty

                delta_objective = round(tm["objective"] - cm["objective"], 4)
                rank = (
                    round(adj_util, 2),
                    round(adj_xi, 2),
                    delta_objective,
                    budget - tm["cost"],
                    -sequence,
                )
                compact = (tuple(outs), tuple(chosen), tm, dxi, du, risk_delta, risk_penalty, adj_xi, adj_util)
                entry = (*rank, compact)
                sequence += 1
                if len(heap) < top_per_size:
                    heappush(heap, entry)
                elif entry[:5] > heap[0][:5]:
                    heapreplace(heap, entry)

        selected = []
        for entry in sorted(heap, key=lambda row: row[:5], reverse=True):
            row = _materialize_package(entry[5], k, basecost, budget)
            tm = entry[5][2]
            row["delta_objective"] = round(tm["objective"] - cm["objective"], 4)
            row["delta_squad_xpts_3"] = round(tm["squad_xpts_3"] - cm["squad_xpts_3"], 2)
            row["delta_squad_xpts_5"] = round(tm["squad_xpts_5"] - cm["squad_xpts_5"], 2)
            row["delta_squad_xpts_10"] = round(tm["squad_xpts_10"] - cm["squad_xpts_10"], 2)
            row["delta_squad_xpts_15"] = round(tm["squad_xpts_15"] - cm["squad_xpts_15"], 2)
            selected.append(row)
        results[str(k)] = selected

    best = {key: (rows[0] if rows else None) for key, rows in results.items()}
    material = [row for row in best.values() if row and row["classification"] == "MATERIAL_UPGRADE"]
    optional = [row for row in best.values() if row and row["classification"] == "OPTIONAL_IMPROVEMENT"]
    if material:
        overall = max(material, key=lambda row: (row["adjusted_utility_gain_5"], row["adjusted_best_xi_gain_5"]))
        verdict = "MATERIAL_UPGRADE"
    elif optional:
        overall = max(optional, key=lambda row: (row["adjusted_utility_gain_5"], row["adjusted_best_xi_gain_5"]))
        verdict = "OPTIONAL_IMPROVEMENT"
    else:
        overall = None
        verdict = "KEEP_15"

    return {
        "schema_version": 472,
        "engine": "v4.7.2-wc-package-audit-performance-hotfix-state-reuse",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "affordability": affordability,
        "baseline": cm | {"itb": budget - basecost},
        "screened_players": len(cands),
        "frontier_players": len(fr),
        "max_replacements": max_replacements,
        "best_by_replacement_count": best,
        "packages": results,
        "overall_verdict": verdict,
        "recommended_package": overall,
        "performance": {
            "evaluated_packages": evaluated,
            "keep_profiles": keep_profiles,
            "small_candidate_templates": len(small_templates),
            "small_candidate_template_hits": small_template_hits,
            "bounded_state_cache_entries": len(bounded_states),
            "bounded_state_cache_hits": bounded_state_hits,
            "chosen_profile_cache_entries": len(chosen_profiles),
            "chosen_profile_cache_hits": chosen_profile_hits,
            "target_metrics_cache_removed": True,
            "baseline_keep_profile_reuse": True,
            "precomputed_baseline_club_signature": True,
            "bounded_state_structural_cache": True,
            "sorted_keep_position_prefixes": True,
            "unaffected_position_prefix_reuse": True,
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "single_pass_metrics": True,
            "score_only_hotloop": True,
            "redundant_target_validation_removed": True,
            "candidate_reuse_supported": True,
            "packed_club_signature": True,
            "top_packages_only_payload_materialization": True,
            "exact_streaming_top_packages": True,
            "stable_top_package_tie_semantics": True,
            "full_result_sort_removed": True,
            "compact_keep_profile": True,
            "scalar_delta_metrics": True,
            "position_value_reuse": True,
            "small_package_candidate_template_cache": True,
            "exact_reference_float_accumulation": True,
            "search_quality_reduction": False,
        },
        "guardrails": {
            "max_per_club": MAX_PER_CLUB,
            "budget_tenths": budget,
            "position_counts": POSITION_COUNTS,
            "larger_packages_require_higher_gain": True,
            "owned_price_basis": "sell_cost",
            "unowned_price_basis": "now_cost",
            "ranking_metric": "risk-adjusted best-XI plus bench-adjusted 5GW utility",
            "search": "shortlisted k<=2, bounded beam k=3-4, exact structural-state and prefix reuse",
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "risk_penalty_enabled": True,
            "search_width_unchanged": True,
        },
    }