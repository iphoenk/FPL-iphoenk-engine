from __future__ import annotations

from collections import Counter
from heapq import heappush, heapreplace
from itertools import combinations

from src.engines import v4_wc_package_audit as base
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, reconcile_owned_costs, validate_squad


def _gw_value(player, index: int) -> float:
    return player.gw_xpts[index] if index < len(player.gw_xpts) else 0.0


def _prefix(values) -> tuple[float, ...]:
    out = [0.0]
    for value in sorted(values, reverse=True):
        out.append(out[-1] + value)
    return tuple(out)


def _keep_profile(players, affected_positions: frozenset[str]) -> dict:
    ps = list(players)
    by_pos = {pos: [p for p in ps if p.position == pos] for pos in POSITION_COUNTS}
    gw_values = []
    gw_prefix = []
    for index in range(5):
        values = {pos: tuple(_gw_value(p, index) for p in by_pos[pos]) for pos in POSITION_COUNTS}
        gw_values.append(values)
        gw_prefix.append({
            pos: (_prefix(values[pos]) if pos not in affected_positions else None)
            for pos in POSITION_COUNTS
        })
    return {
        "cost": sum(p.cost for p in ps),
        "objective": sum(p.objective for p in ps),
        "x3": sum(p.x3 for p in ps),
        "x5": sum(p.x5 for p in ps),
        "x10": sum(p.x10 for p in ps),
        "x15": sum(p.x15 for p in ps),
        "gw_total": tuple(sum(_gw_value(p, i) for p in ps) for i in range(5)),
        "gw_values": tuple(gw_values),
        "gw_prefix": tuple(gw_prefix),
        "affected_positions": affected_positions,
    }


def _best_xi_from_prefix(prefix: dict[str, tuple[float, ...]]) -> float:
    gp, dp, mp, fp = prefix["GK"], prefix["DEF"], prefix["MID"], prefix["FWD"]
    gk = gp[1]
    return max(
        gk + dp[3] + mp[4] + fp[3], gk + dp[3] + mp[5] + fp[2],
        gk + dp[4] + mp[3] + fp[3], gk + dp[4] + mp[4] + fp[2],
        gk + dp[4] + mp[5] + fp[1], gk + dp[5] + mp[2] + fp[3],
        gk + dp[5] + mp[3] + fp[2], gk + dp[5] + mp[4] + fp[1],
    )


def _metric_tuple(profile: dict, chosen) -> tuple:
    chosen = tuple(chosen)
    chosen_by_pos = {
        pos: tuple(player for player in chosen if player.position == pos)
        for pos in profile["affected_positions"]
    }
    xi5 = 0.0
    utility5 = 0.0
    for index in range(5):
        prefixes = dict(profile["gw_prefix"][index])
        chosen_total = 0.0
        for pos, players in chosen_by_pos.items():
            additions = tuple(_gw_value(player, index) for player in players)
            chosen_total += sum(additions)
            prefixes[pos] = _prefix((*profile["gw_values"][index][pos], *additions))
        xi = _best_xi_from_prefix(prefixes)
        total = profile["gw_total"][index] + chosen_total
        xi5 += xi
        utility5 += xi + .12 * (total - xi)

    return (
        profile["cost"] + sum(p.cost for p in chosen),
        round(profile["objective"] + sum(p.objective for p in chosen), 4),
        round(profile["x3"] + sum(p.x3 for p in chosen), 2),
        round(profile["x5"] + sum(p.x5 for p in chosen), 2),
        round(profile["x10"] + sum(p.x10 for p in chosen), 2),
        round(profile["x15"] + sum(p.x15 for p in chosen), 2),
        round(xi5, 2),
        round(utility5, 2),
    )


def _materialize_candidate(compact: tuple, k: int, budget: int, basecost: int, cm: dict) -> dict:
    (
        outs, chosen, target_cost, objective, x3, x5, x10, x15, xi5, utility5,
        risk_delta, risk_penalty, adjusted_xi, adjusted_utility,
    ) = compact
    return {
        "replacements": k,
        "target_cost": target_cost,
        "target_itb": budget - target_cost,
        "delta_cost": target_cost - basecost,
        "delta_objective": round(objective - cm["objective"], 4),
        "delta_squad_xpts_3": round(x3 - cm["squad_xpts_3"], 2),
        "delta_squad_xpts_5": round(x5 - cm["squad_xpts_5"], 2),
        "delta_squad_xpts_10": round(x10 - cm["squad_xpts_10"], 2),
        "delta_squad_xpts_15": round(x15 - cm["squad_xpts_15"], 2),
        "delta_best_xi_xpts_5": round(xi5 - cm["best_xi_xpts_5"], 2),
        "delta_bench_adjusted_utility_5": round(utility5 - cm["bench_adjusted_utility_5"], 2),
        "risk_delta": round(risk_delta, 3),
        "risk_penalty": round(risk_penalty, 3),
        "adjusted_best_xi_gain_5": round(adjusted_xi, 2),
        "adjusted_utility_gain_5": round(adjusted_utility, 2),
        "classification": base.package_class(adjusted_xi, adjusted_utility, k),
        "out": [base.payload(p) for p in outs],
        "in": [base.payload(p) for p in chosen],
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
    results: dict[str, list[dict]] = {}
    profile_cache: dict[tuple[int, ...], dict] = {}
    evaluated = 0
    survivor_replacements = 0
    full_package_dicts_avoided = 0

    for k in range(1, max_replacements + 1):
        top_heap: list[tuple] = []
        sequence = 0
        for outs in combinations(cur, k):
            outids = {p.element for p in outs}
            need = Counter(p.position for p in outs)
            if any(len(bp[pos]) < n for pos, n in need.items()):
                continue
            out_unc = sum(p.uncertainty for p in outs)
            keep = [p for p in cur if p.element not in outids]
            profile_key = tuple(sorted(outids))
            profile = profile_cache.get(profile_key)
            if profile is None:
                profile = _keep_profile(keep, frozenset(need))
                profile_cache[profile_key] = profile
            sorted_outs = tuple(sorted(outs, key=lambda player: (player.position, player.name)))

            for chosen in base._candidate_states(cur, outids, need, bp, budget, k, beam_size):
                if len(chosen) != k:
                    continue
                evaluated += 1
                (
                    target_cost, objective, x3, x5, x10, x15, xi5, utility5,
                ) = _metric_tuple(profile, chosen)
                dxi = xi5 - cm["best_xi_xpts_5"]
                du = utility5 - cm["bench_adjusted_utility_5"]
                risk_delta = sum(p.uncertainty for p in chosen) - out_unc
                risk_penalty = max(0, risk_delta) * .35 + max(0, k - 1) * .20
                adjusted_xi = dxi - risk_penalty
                adjusted_utility = du - risk_penalty
                delta_objective = round(objective - cm["objective"], 4)
                target_itb = budget - target_cost
                rank = (
                    round(adjusted_utility, 2),
                    round(adjusted_xi, 2),
                    delta_objective,
                    target_itb,
                )
                sorted_chosen = tuple(sorted(chosen, key=lambda player: (player.position, player.name)))
                compact = (
                    sorted_outs, sorted_chosen, target_cost, objective, x3, x5, x10, x15,
                    xi5, utility5, risk_delta, risk_penalty, adjusted_xi, adjusted_utility,
                )
                entry = (*rank, -sequence, compact)
                sequence += 1
                if len(top_heap) < top_per_size:
                    heappush(top_heap, entry)
                elif entry[:-1] > top_heap[0][:-1]:
                    heapreplace(top_heap, entry)
                    survivor_replacements += 1
                else:
                    full_package_dicts_avoided += 1

        ordered = sorted(top_heap, key=lambda entry: entry[:-1], reverse=True)
        results[str(k)] = [
            _materialize_candidate(entry[-1], k, budget, basecost, cm)
            for entry in ordered
        ]

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
        "engine": "v4.7.2-wc-package-audit-performance-hotfix-streaming-topk",
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
            "metrics_cache_entries": len(profile_cache),
            "metrics_cache_kind": "outgoing_keep_profiles_reused_across_incoming_states",
            "evaluated_packages": evaluated,
            "keep_profiles": len(profile_cache),
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "single_pass_metrics": True,
            "score_only_hotloop": True,
            "compact_target_cache": True,
            "redundant_target_validation_removed": True,
            "candidate_reuse_supported": True,
            "packed_club_signature": True,
            "top_packages_only_payload_materialization": True,
            "compact_keep_profile": True,
            "scalar_delta_metrics": True,
            "position_value_reuse": True,
            "exact_streaming_top_packages": True,
            "stable_top_package_ties": True,
            "target_metric_cache_removed": True,
            "survivor_replacements": survivor_replacements,
            "full_package_dicts_avoided": full_package_dicts_avoided,
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
            "search": "unchanged shortlisted k<=2 / beam k=3-4 plus exact streaming top-package retention",
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "risk_penalty_enabled": True,
            "search_width_unchanged": True,
        },
    }
