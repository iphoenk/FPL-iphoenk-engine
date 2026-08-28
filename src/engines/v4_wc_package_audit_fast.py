from __future__ import annotations

from collections import Counter
from heapq import heappush, heapreplace
from itertools import combinations

from src.engines import v4_wc_package_audit as base
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, reconcile_owned_costs, validate_squad


def _gw_value(player, index: int) -> float:
    return player.gw_xpts[index] if index < len(player.gw_xpts) else 0.0


def _keep_profile(players) -> dict:
    ps = list(players)
    by_pos = {pos: [p for p in ps if p.position == pos] for pos in POSITION_COUNTS}
    return {
        "cost": sum(p.cost for p in ps),
        "objective": sum(p.objective for p in ps),
        "x3": sum(p.x3 for p in ps),
        "x5": sum(p.x5 for p in ps),
        "x10": sum(p.x10 for p in ps),
        "x15": sum(p.x15 for p in ps),
        "gw_total": [sum(_gw_value(p, i) for p in ps) for i in range(5)],
        "gw_by_pos": [
            {pos: [_gw_value(p, i) for p in by_pos[pos]] for pos in POSITION_COUNTS}
            for i in range(5)
        ],
    }


def _best_xi_from_values(by: dict[str, list[float]]) -> float:
    gk = max(by["GK"], default=0.0)
    dv = sorted(by["DEF"], reverse=True)
    mv = sorted(by["MID"], reverse=True)
    fv = sorted(by["FWD"], reverse=True)
    dp = [0.0]
    mp = [0.0]
    fp = [0.0]
    for value in dv:
        dp.append(dp[-1] + value)
    for value in mv:
        mp.append(mp[-1] + value)
    for value in fv:
        fp.append(fp[-1] + value)
    return max(
        gk + dp[3] + mp[4] + fp[3], gk + dp[3] + mp[5] + fp[2],
        gk + dp[4] + mp[3] + fp[3], gk + dp[4] + mp[4] + fp[2],
        gk + dp[4] + mp[5] + fp[1], gk + dp[5] + mp[2] + fp[3],
        gk + dp[5] + mp[3] + fp[2], gk + dp[5] + mp[4] + fp[1],
    )


def _metrics_from_keep_profile(profile: dict, chosen) -> dict:
    chosen = tuple(chosen)
    xi5 = 0.0
    utility5 = 0.0
    for index in range(5):
        by = {pos: list(profile["gw_by_pos"][index][pos]) for pos in POSITION_COUNTS}
        chosen_total = 0.0
        for player in chosen:
            value = _gw_value(player, index)
            by[player.position].append(value)
            chosen_total += value
        xi = _best_xi_from_values(by)
        total = profile["gw_total"][index] + chosen_total
        xi5 += xi
        utility5 += xi + .12 * (total - xi)
    return {
        "cost": profile["cost"] + sum(p.cost for p in chosen),
        "objective": round(profile["objective"] + sum(p.objective for p in chosen), 4),
        "squad_xpts_3": round(profile["x3"] + sum(p.x3 for p in chosen), 2),
        "squad_xpts_5": round(profile["x5"] + sum(p.x5 for p in chosen), 2),
        "squad_xpts_10": round(profile["x10"] + sum(p.x10 for p in chosen), 2),
        "squad_xpts_15": round(profile["x15"] + sum(p.x15 for p in chosen), 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(utility5, 2),
    }


def _materialize_package(compact: tuple, k: int, basecost: int, budget: int) -> dict:
    outs, chosen, tm, dxi, du, risk_delta, risk_penalty, adj_xi, adj_util = compact
    return {
        "replacements": k,
        "out": [base.payload(p) for p in sorted(outs, key=lambda x: (x.position, x.name))],
        "in": [base.payload(p) for p in sorted(chosen, key=lambda x: (x.position, x.name))],
        "target_cost": tm["cost"],
        "target_itb": budget - tm["cost"],
        "delta_cost": tm["cost"] - basecost,
        "delta_objective": round(tm["objective"] - 0.0, 4),  # replaced by caller below
        "delta_squad_xpts_3": tm["squad_xpts_3"],              # replaced by caller below
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
    results: dict[str, list[dict]] = {}
    metrics_cache: dict[tuple[int, ...], dict] = {}
    metrics_cache_hits = 0
    keep_profiles = 0
    evaluated = 0

    for k in range(1, max_replacements + 1):
        heap: list[tuple] = []
        sequence = 0
        for outs in combinations(cur, k):
            outids = {p.element for p in outs}
            need = Counter(p.position for p in outs)
            if any(len(bp[pos]) < n for pos, n in need.items()):
                continue
            out_unc = sum(p.uncertainty for p in outs)
            keep = [p for p in cur if p.element not in outids]
            profile = _keep_profile(keep)
            keep_profiles += 1
            keep_ids = tuple(p.element for p in keep)

            for chosen in base._candidate_states(cur, outids, need, bp, budget, k, beam_size):
                if len(chosen) != k:
                    continue
                key = tuple(sorted((*keep_ids, *(p.element for p in chosen))))
                if key in metrics_cache:
                    tm = metrics_cache[key]
                    metrics_cache_hits += 1
                else:
                    tm = _metrics_from_keep_profile(profile, chosen)
                    metrics_cache[key] = tm
                evaluated += 1
                dxi = tm["best_xi_xpts_5"] - cm["best_xi_xpts_5"]
                du = tm["bench_adjusted_utility_5"] - cm["bench_adjusted_utility_5"]
                risk_delta = sum(p.uncertainty for p in chosen) - out_unc
                risk_penalty = max(0, risk_delta) * .35 + max(0, k - 1) * .20
                adj_xi = dxi - risk_penalty
                adj_util = du - risk_penalty

                # Exact same ranking as the previous stable full sort, but keep only
                # the top output rows. All candidate states are still evaluated.
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
        "engine": "v4.7.2-wc-package-audit-performance-hotfix-compact-profile",
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
            "metrics_cache_entries": len(metrics_cache),
            "metrics_cache_hits": metrics_cache_hits,
            "evaluated_packages": evaluated,
            "keep_profiles": keep_profiles,
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "single_pass_metrics": True,
            "score_only_hotloop": True,
            "compact_target_cache": True,
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
            "search": "shortlisted k<=2, bounded beam k=3-4, compact keep-profile evaluator",
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "risk_penalty_enabled": True,
            "search_width_unchanged": True,
        },
    }
