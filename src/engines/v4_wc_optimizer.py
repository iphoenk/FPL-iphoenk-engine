from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

POSITION_COUNTS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
BUDGET_TENTHS = 1000
MAX_PER_CLUB = 3


@dataclass(frozen=True)
class Candidate:
    element: int
    name: str
    position: str
    team_id: int
    team: str
    cost: int
    x3: float
    x5: float
    x10: float
    x15: float
    uncertainty: float
    objective: float
    gw_xpts: tuple[float, ...]


def _f(v, default=0.0) -> float:
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


def player_objective(pred: dict) -> float:
    x3 = _f(pred.get("xpts_3")) / 3.0
    x5 = _f(pred.get("xpts_5")) / 5.0
    x10 = _f(pred.get("xpts_10")) / 10.0
    x15 = _f(pred.get("xpts_15")) / 15.0
    unc = _f(pred.get("uncertainty"))
    return 0.25 * x3 + 0.50 * x5 + 0.15 * x10 + 0.10 * x15 - 0.08 * unc


def build_candidates(predictions: dict, universe: dict) -> list[Candidate]:
    by_element = {int(p["element"]): p for p in universe.get("players", [])}
    out: list[Candidate] = []
    for pred in predictions.get("players", []):
        eid = int(pred.get("element"))
        u = by_element.get(eid)
        if not u:
            continue
        pos = u.get("position") or pred.get("position")
        if pos not in POSITION_COUNTS or u.get("status") in {"u", "s"}:
            continue
        fx = tuple(_f(x.get("xpts")) for x in pred.get("fixtures", [])[:15])
        out.append(Candidate(
            element=eid,
            name=u.get("name") or pred.get("name") or str(eid),
            position=pos,
            team_id=int(u.get("team_id")),
            team=u.get("team") or str(u.get("team_id")),
            cost=int(u.get("now_cost") or 0),
            x3=_f(pred.get("xpts_3")),
            x5=_f(pred.get("xpts_5")),
            x10=_f(pred.get("xpts_10")),
            x15=_f(pred.get("xpts_15")),
            uncertainty=_f(pred.get("uncertainty")),
            objective=player_objective(pred),
            gw_xpts=fx,
        ))
    return out


def validate_squad(players: Iterable[Candidate], budget: int = BUDGET_TENTHS) -> tuple[bool, str]:
    ps = list(players)
    if len(ps) != 15:
        return False, "squad_count"
    counts = Counter(p.position for p in ps)
    if any(counts.get(pos, 0) != n for pos, n in POSITION_COUNTS.items()):
        return False, "position_structure"
    if sum(p.cost for p in ps) > budget:
        return False, "budget"
    clubs = Counter(p.team_id for p in ps)
    if clubs and max(clubs.values()) > MAX_PER_CLUB:
        return False, "club_limit"
    if len({p.element for p in ps}) != 15:
        return False, "duplicate"
    return True, "ok"


def _pool(cands: list[Candidate], locked_ids: set[int], pool_size: int) -> list[Candidate]:
    ranked = sorted(cands, key=lambda p: (p.objective, p.x5, -p.cost), reverse=True)
    pool = ranked[:pool_size]
    seen = {p.element for p in pool}
    pool.extend(p for p in ranked if p.element in locked_ids and p.element not in seen)
    return pool


def _gw_value(p: Candidate, idx: int) -> float:
    return p.gw_xpts[idx] if idx < len(p.gw_xpts) else 0.0


def best_xi(players: Iterable[Candidate], gw_index: int) -> tuple[float, list[int]]:
    ps = list(players)
    by = {pos: sorted([p for p in ps if p.position == pos], key=lambda x: _gw_value(x, gw_index), reverse=True) for pos in POSITION_COUNTS}
    if any(len(by[pos]) < POSITION_COUNTS[pos] for pos in POSITION_COUNTS):
        return 0.0, []
    gk = by["GK"][0]
    best_score = -1.0
    best_ids: list[int] = []
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if not (1 <= f <= 3):
                continue
            chosen = [gk] + by["DEF"][:d] + by["MID"][:m] + by["FWD"][:f]
            score = sum(_gw_value(p, gw_index) for p in chosen)
            if score > best_score:
                best_score = score
                best_ids = [p.element for p in chosen]
    return max(0.0, best_score), best_ids


def _group_by_position(players: Iterable[Candidate]) -> dict[str, list[Candidate]]:
    by = {pos: [] for pos in POSITION_COUNTS}
    for p in players:
        by[p.position].append(p)
    return by


def _best_xi_score_grouped(by: dict[str, list[Candidate]], gw_index: int) -> float:
    """Score-only legal XI evaluator used in hot loops. Semantics match best_xi()."""
    gk = max((_gw_value(p, gw_index) for p in by["GK"]), default=0.0)
    dv = sorted((_gw_value(p, gw_index) for p in by["DEF"]), reverse=True)
    mv = sorted((_gw_value(p, gw_index) for p in by["MID"]), reverse=True)
    fv = sorted((_gw_value(p, gw_index) for p in by["FWD"]), reverse=True)
    dp = [0.0]
    mp = [0.0]
    fp = [0.0]
    for v in dv: dp.append(dp[-1] + v)
    for v in mv: mp.append(mp[-1] + v)
    for v in fv: fp.append(fp[-1] + v)
    best = 0.0
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3:
                score = gk + dp[d] + mp[m] + fp[f]
                if score > best:
                    best = score
    return best


def squad_utility_fast(players: Iterable[Candidate], horizon: int = 5, bench_weight: float = 0.12) -> float:
    """Equivalent to squad_utility but avoids regrouping the 15-player squad for every GW."""
    ps = list(players)
    by = _group_by_position(ps)
    total = 0.0
    for i in range(horizon):
        xi_score = _best_xi_score_grouped(by, i)
        squad_total = sum(_gw_value(p, i) for p in ps)
        total += xi_score + bench_weight * (squad_total - xi_score)
    return total


def squad_utility(players: Iterable[Candidate], horizon: int = 5, bench_weight: float = 0.12) -> float:
    ps = list(players)
    total = 0.0
    for i in range(horizon):
        xi_score, xi_ids = best_xi(ps, i)
        ids = set(xi_ids)
        bench = sum(_gw_value(p, i) for p in ps if p.element not in ids)
        total += xi_score + bench_weight * bench
    return total


def optimize_squad(candidates: list[Candidate], locked_ids: set[int] | None = None, budget: int = BUDGET_TENTHS,
                   pool_sizes: dict[str, int] | None = None, beam_size: int = 6000) -> dict:
    locked_ids = locked_ids or set()
    pool_sizes = pool_sizes or {"GK": 20, "DEF": 34, "MID": 40, "FWD": 28}
    by_pos = {pos: _pool([p for p in candidates if p.position == pos], locked_ids, pool_sizes[pos]) for pos in POSITION_COUNTS}
    states = [(tuple(), 0, Counter(), 0.0, -1)]
    for pos in ["GK", "DEF", "MID", "FWD"]:
        pool = by_pos[pos]
        states = [(sel, cost, clubs, score, -1) for sel, cost, clubs, score, _ in states]
        for _slot in range(POSITION_COUNTS[pos]):
            nxt = []
            for selected, cost, clubs, score, last_idx in states:
                for idx in range(last_idx + 1, len(pool)):
                    p = pool[idx]
                    new_cost = cost + p.cost
                    if new_cost > budget or clubs[p.team_id] >= MAX_PER_CLUB:
                        continue
                    cc = clubs.copy()
                    cc[p.team_id] += 1
                    nxt.append((selected + (p,), new_cost, cc, score + p.objective, idx))
            nxt.sort(key=lambda s: (s[3], -s[1]), reverse=True)
            states = nxt[:beam_size]
            if not states:
                raise RuntimeError(f"no legal optimizer state while selecting {pos}")

    # All complete beam states are structurally legal by construction. Avoid validating
    # thousands of finalists; validate only the winner as a fail-closed invariant check.
    finalists = [
        (squad_utility_fast(selected, 5), heuristic, -cost, selected, cost)
        for selected, cost, _clubs, heuristic, _ in states
    ]
    if not finalists:
        raise RuntimeError("optimizer produced no legal finalist")
    best = max(finalists, key=lambda x: (x[0], x[1], x[2]))
    ok, reason = validate_squad(best[3], budget)
    if not ok:
        raise RuntimeError(f"optimizer winner failed legality invariant: {reason}")
    return {
        "players": list(best[3]), "cost": best[4], "itb": budget - best[4],
        "objective": best[1], "xi_utility_5": best[0], "screened_players": len(candidates),
        "pool_sizes": pool_sizes, "beam_size": beam_size,
        "performance": {"fast_finalist_scoring": True, "winner_only_legality_check": True},
    }


def squad_metrics(players: Iterable[Candidate]) -> dict:
    ps = list(players)
    xi5 = 0.0
    xi_detail = []
    for i in range(5):
        score, ids = best_xi(ps, i)
        xi5 += score
        xi_detail.append({"gw_offset": i + 1, "xpts": round(score, 2), "elements": ids})
    return {
        "cost": sum(p.cost for p in ps),
        "objective": round(sum(p.objective for p in ps), 4),
        "squad_xpts_3": round(sum(p.x3 for p in ps), 2),
        "squad_xpts_5": round(sum(p.x5 for p in ps), 2),
        "squad_xpts_10": round(sum(p.x10 for p in ps), 2),
        "squad_xpts_15": round(sum(p.x15 for p in ps), 2),
        "best_xi_xpts_5": round(xi5, 2),
        "bench_adjusted_utility_5": round(squad_utility_fast(ps, 5), 2),
        "best_xi_by_gw": xi_detail,
    }


def classify_gain(delta_utility: float, delta_xi5: float) -> str:
    if delta_xi5 >= 4.0 and delta_utility >= 4.5:
        return "MATERIAL_UPGRADE"
    if delta_xi5 >= 1.5 and delta_utility >= 2.0:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_15"


def decision_report(predictions: dict, universe: dict, locked: dict, budget: int = BUDGET_TENTHS) -> dict:
    candidates = build_candidates(predictions, universe)
    return decision_report_from_candidates(candidates, locked, budget)


def decision_report_from_candidates(candidates: list[Candidate], locked: dict, budget: int = BUDGET_TENTHS) -> dict:
    by_id = {p.element: p for p in candidates}
    locked_ids = {int(p["element"]) for p in locked.get("players", [])}
    missing = sorted(locked_ids - set(by_id))
    if missing:
        raise RuntimeError(f"locked players absent from candidate universe: {missing}")
    current = [by_id[eid] for eid in locked_ids]
    ok, reason = validate_squad(current, budget)
    if not ok:
        raise RuntimeError(f"locked squad invalid: {reason}")

    optimized = optimize_squad(candidates, locked_ids=locked_ids, budget=budget)
    target = optimized["players"]
    current_m = squad_metrics(current)
    target_m = squad_metrics(target)
    target_ids = {p.element for p in target}
    outs = sorted((by_id[x] for x in locked_ids - target_ids), key=lambda p: (p.position, p.name))
    ins = sorted((by_id[x] for x in target_ids - locked_ids), key=lambda p: (p.position, p.name))
    delta_xi5 = target_m["best_xi_xpts_5"] - current_m["best_xi_xpts_5"]
    delta_utility = target_m["bench_adjusted_utility_5"] - current_m["bench_adjusted_utility_5"]

    direct = []
    baseline_itb = int(locked.get("itb_tenths", 0) or 0)
    for owned in current:
        alternatives = [p for p in candidates if p.position == owned.position and p.element not in locked_ids and p.cost <= owned.cost + baseline_itb]
        alternatives.sort(key=lambda p: p.objective, reverse=True)
        if alternatives:
            c = alternatives[0]
            direct.append({
                "owned": owned.element, "owned_name": owned.name, "challenger": c.element,
                "challenger_name": c.name, "position": owned.position, "cost_delta": c.cost - owned.cost,
                "objective_delta": round(c.objective - owned.objective, 4), "xpts5_delta": round(c.x5 - owned.x5, 2),
            })
    direct.sort(key=lambda x: x["objective_delta"], reverse=True)

    return {
        "schema_version": 446, "engine": "v4.4.5-wc-optimizer-fast-finalist",
        "wildcard_active": bool(locked.get("wildcard_active")), "budget_tenths": budget,
        "baseline_itb_tenths": baseline_itb, "screened_players": len(candidates),
        "current": current_m, "optimized": target_m | {"itb": optimized["itb"]},
        "delta": {"best_xi_xpts_5": round(delta_xi5, 2), "bench_adjusted_utility_5": round(delta_utility, 2)},
        "classification": classify_gain(delta_utility, delta_xi5),
        "out": [{"element": p.element, "name": p.name, "position": p.position, "cost": p.cost} for p in outs],
        "in": [{"element": p.element, "name": p.name, "position": p.position, "cost": p.cost} for p in ins],
        "optimized_elements": [p.element for p in target], "direct_challengers": direct[:15],
        "hard_constraints": {"squad_size": 15, "positions": POSITION_COUNTS, "budget_tenths": budget, "max_per_club": MAX_PER_CLUB, "legal_xi": True},
        "performance": {"fast_finalist_scoring": True, "winner_only_legality_check": True, "beam_size_unchanged": optimized["beam_size"] == 6000},
    }
