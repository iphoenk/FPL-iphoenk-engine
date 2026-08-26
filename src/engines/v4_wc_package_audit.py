from __future__ import annotations
import json
from collections import Counter
from itertools import combinations
from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import (
    BUDGET_TENTHS, MAX_PER_CLUB, POSITION_COUNTS, build_candidates, best_xi,
    validate_squad, reconcile_owned_costs, _group_by_position, _best_xi_score_grouped,
)

OUTFILE = DATA / "wc_package_audit_v4.json"


def payload(p):
    return {
        "element": p.element, "name": p.name, "position": p.position, "team": p.team,
        "team_id": p.team_id, "cost": p.cost, "xpts_3": round(p.x3, 2),
        "xpts_5": round(p.x5, 2), "xpts_10": round(p.x10, 2), "xpts_15": round(p.x15, 2),
        "uncertainty": round(p.uncertainty, 3), "objective": round(p.objective, 4),
    }


def package_class(dxi, du, k):
    xr = {1: 1.5, 2: 2.5, 3: 3.5, 4: 4.5}[k]
    ur = {1: 1.8, 2: 3.0, 3: 4.2, 4: 5.4}[k]
    if dxi >= xr and du >= ur:
        return "MATERIAL_UPGRADE"
    if dxi >= xr * .55 and du >= ur * .55:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_BASELINE"


def _package_class(delta_x5, delta_obj, replacements):
    return package_class(delta_x5, delta_obj, replacements)


def _gw_value(p, idx):
    return p.gw_xpts[idx] if idx < len(p.gw_xpts) else 0.0


def _fast_metrics(players, include_detail=False):
    ps = list(players)
    by = _group_by_position(ps)
    xi5 = 0.0
    utility5 = 0.0
    detail = []
    for i in range(5):
        score = _best_xi_score_grouped(by, i)
        total = sum(_gw_value(p, i) for p in ps)
        xi5 += score
        utility5 += score + .12 * (total - score)
        if include_detail:
            _, ids = best_xi(ps, i)
            detail.append({"gw_offset": i + 1, "xpts": round(score, 2), "elements": ids})
    out = {
        "cost": sum(p.cost for p in ps),
        "objective": round(sum(p.objective for p in ps), 4),
        "squad_xpts_3": round(sum(p.x3 for p in ps), 2),
        "squad_xpts_5": round(sum(p.x5 for p in ps), 2),
        "squad_xpts_10": round(sum(p.x10 for p in ps), 2),
        "squad_xpts_15": round(sum(p.x15 for p in ps), 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(utility5, 2),
    }
    if include_detail:
        out["best_xi_by_gw"] = detail
    return out


def frontier(cands, ids, n=7):
    out = []
    for pos in POSITION_COUNTS:
        rows = [p for p in cands if p.position == pos and p.element not in ids]
        rows.sort(key=lambda p: (p.objective - .12 * p.uncertainty, p.x5, -p.cost), reverse=True)
        out += rows[:n]
    return out


def _bounded_ins_states(cur, outids, need, bp, budget, beam=28):
    keep = [p for p in cur if p.element not in outids]
    base_cost = sum(p.cost for p in keep)
    base_clubs = 0
    for p in keep:
        base_clubs += 1 << ((p.team_id - 1) * 2)
    slots = []
    for pos, n in need.items():
        slots += [pos] * n
    states = [(tuple(), base_cost, base_clubs, 0.0)]
    for pos in slots:
        nxt = []
        for chosen, cost, clubs, score in states:
            used = {p.element for p in chosen}
            for p in bp[pos]:
                shift = (p.team_id - 1) * 2
                if p.element in used or cost + p.cost > budget or ((clubs >> shift) & 0b11) >= MAX_PER_CLUB:
                    continue
                nxt.append((chosen + (p,), cost + p.cost, clubs + (1 << shift), score + p.objective - .12 * p.uncertainty))
        nxt.sort(key=lambda s: (s[3], -s[1]), reverse=True)
        dedup, seen = [], set()
        for s in nxt:
            key = tuple(sorted(p.element for p in s[0]))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(s)
            if len(dedup) >= beam:
                break
        states = dedup
        if not states:
            break
    return [s[0] for s in states]


def _candidate_states(cur, outids, need, bp, budget, k, beam_size):
    if k >= 3:
        return _bounded_ins_states(cur, outids, need, bp, budget, beam_size)
    pools = [list(combinations(bp[pos], n)) for pos, n in need.items()]
    states = [tuple()]
    for comboset in pools:
        states = [s + c for s in states for c in comboset if len({p.element for p in s + c}) == len(s + c)]
    keep = [p for p in cur if p.element not in outids]
    keep_cost = sum(p.cost for p in keep)
    clubs = 0
    for p in keep:
        clubs += 1 << ((p.team_id - 1) * 2)
    legal = []
    for chosen in states:
        if keep_cost + sum(p.cost for p in chosen) > budget:
            continue
        cc = clubs
        ok = True
        for p in chosen:
            shift = (p.team_id - 1) * 2
            if ((cc >> shift) & 0b11) >= MAX_PER_CLUB:
                ok = False
                break
            cc += 1 << shift
        if ok:
            legal.append((sum(p.objective - .12 * p.uncertainty for p in chosen), chosen))
    legal.sort(key=lambda x: x[0], reverse=True)
    cap = 16 if k == 1 else 30
    return [x[1] for x in legal[:cap]]


def audit_packages(predictions, universe, locked, max_replacements=4, budget=None,
                   per_position_frontier=7, top_per_size=8, beam_size=28):
    cands = build_candidates(predictions, universe)
    return audit_packages_from_candidates(cands, locked, max_replacements, budget, per_position_frontier, top_per_size, beam_size)


def audit_packages_from_candidates(cands, locked, max_replacements=4, budget=None,
                                   per_position_frontier=7, top_per_size=8, beam_size=28):
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
    cur = [by[e] for e in ids]
    ok, reason = validate_squad(cur, budget)
    if not ok:
        raise RuntimeError(f"baseline invalid: {reason}")

    fr = frontier(cands, ids, per_position_frontier)
    bp = {pos: [p for p in fr if p.position == pos] for pos in POSITION_COUNTS}
    cm = _fast_metrics(cur, include_detail=True)
    basecost = cm["cost"]
    results = {}
    metrics_cache = {}

    def metrics(target):
        key = tuple(sorted(p.element for p in target))
        if key not in metrics_cache:
            metrics_cache[key] = _fast_metrics(target, include_detail=False)
        return metrics_cache[key]

    evaluated = 0
    for k in range(1, max_replacements + 1):
        packs = []
        for outs in combinations(cur, k):
            outids = {p.element for p in outs}
            need = Counter(p.position for p in outs)
            if any(len(bp[pos]) < n for pos, n in need.items()):
                continue
            out_unc = sum(p.uncertainty for p in outs)
            keep = [p for p in cur if p.element not in outids]
            for chosen in _candidate_states(cur, outids, need, bp, budget, k, beam_size):
                if len(chosen) != k:
                    continue
                target = keep + list(chosen)
                tm = metrics(target)
                evaluated += 1
                dxi = tm["best_xi_xpts_5"] - cm["best_xi_xpts_5"]
                du = tm["bench_adjusted_utility_5"] - cm["bench_adjusted_utility_5"]
                risk_delta = sum(p.uncertainty for p in chosen) - out_unc
                risk_penalty = max(0, risk_delta) * .35 + max(0, k - 1) * .20
                adj_xi = dxi - risk_penalty
                adj_util = du - risk_penalty
                packs.append({
                    "replacements": k,
                    "_out_players": sorted(outs, key=lambda x: (x.position, x.name)),
                    "_in_players": sorted(chosen, key=lambda x: (x.position, x.name)),
                    "target_cost": tm["cost"], "target_itb": budget - tm["cost"],
                    "delta_cost": tm["cost"] - basecost,
                    "delta_objective": round(tm["objective"] - cm["objective"], 4),
                    "delta_squad_xpts_3": round(tm["squad_xpts_3"] - cm["squad_xpts_3"], 2),
                    "delta_squad_xpts_5": round(tm["squad_xpts_5"] - cm["squad_xpts_5"], 2),
                    "delta_squad_xpts_10": round(tm["squad_xpts_10"] - cm["squad_xpts_10"], 2),
                    "delta_squad_xpts_15": round(tm["squad_xpts_15"] - cm["squad_xpts_15"], 2),
                    "delta_best_xi_xpts_5": round(dxi, 2),
                    "delta_bench_adjusted_utility_5": round(du, 2),
                    "risk_delta": round(risk_delta, 3), "risk_penalty": round(risk_penalty, 3),
                    "adjusted_best_xi_gain_5": round(adj_xi, 2),
                    "adjusted_utility_gain_5": round(adj_util, 2),
                    "classification": package_class(adj_xi, adj_util, k),
                })
        packs.sort(key=lambda r: (r["adjusted_utility_gain_5"], r["adjusted_best_xi_gain_5"], r["delta_objective"], r["target_itb"]), reverse=True)
        selected = packs[:top_per_size]
        for row in selected:
            row["out"] = [payload(p) for p in row.pop("_out_players")]
            row["in"] = [payload(p) for p in row.pop("_in_players")]
        results[str(k)] = selected

    best = {k: (rows[0] if rows else None) for k, rows in results.items()}
    mat = [x for x in best.values() if x and x["classification"] == "MATERIAL_UPGRADE"]
    opt = [x for x in best.values() if x and x["classification"] == "OPTIONAL_IMPROVEMENT"]
    if mat:
        overall = max(mat, key=lambda x: (x["adjusted_utility_gain_5"], x["adjusted_best_xi_gain_5"]))
        verdict = "MATERIAL_UPGRADE"
    elif opt:
        overall = max(opt, key=lambda x: (x["adjusted_utility_gain_5"], x["adjusted_best_xi_gain_5"]))
        verdict = "OPTIONAL_IMPROVEMENT"
    else:
        overall = None
        verdict = "KEEP_15"

    return {
        "schema_version": 472,
        "engine": "v4.7.2-wc-package-audit-performance-hotfix",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "affordability": affordability,
        "baseline": cm | {"itb": budget - basecost},
        "screened_players": len(cands), "frontier_players": len(fr),
        "max_replacements": max_replacements,
        "best_by_replacement_count": best, "packages": results,
        "overall_verdict": verdict, "recommended_package": overall,
        "performance": {
            "metrics_cache_entries": len(metrics_cache),
            "evaluated_packages": evaluated,
            "frontier_per_position": per_position_frontier,
            "beam_size": beam_size,
            "single_pass_metrics": True,
            "score_only_hotloop": True,
            "compact_target_cache": True,
            "redundant_target_validation_removed": True,
            "candidate_reuse_supported": True,
            "packed_club_signature": True,
            "top_packages_only_payload_materialization": True,
        },
        "guardrails": {
            "max_per_club": MAX_PER_CLUB, "budget_tenths": budget,
            "position_counts": POSITION_COUNTS, "larger_packages_require_higher_gain": True,
            "owned_price_basis": "sell_cost", "unowned_price_basis": "now_cost",
            "ranking_metric": "risk-adjusted best-XI plus bench-adjusted 5GW utility",
            "search": "shortlisted k<=2, bounded beam k=3-4, score-only compact memoized metrics",
            "frontier_per_position": per_position_frontier, "beam_size": beam_size,
            "risk_penalty_enabled": True,
            "search_width_unchanged": True,
        },
    }


def run():
    out = audit_packages(
        read_json(DATA / "predictions_v4.json", {}),
        read_json(DATA / "universe.json", {}),
        read_json(CONFIG / "locked_squad.json", {}),
    )
    atomic_json(OUTFILE, out)
    print(json.dumps({"engine": out["engine"], "overall_verdict": out["overall_verdict"], "cache_entries": out["performance"]["metrics_cache_entries"]}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
