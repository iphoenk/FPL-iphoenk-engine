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
        if pos not in POSITION_COUNTS:
            continue
        if u.get("status") in {"u", "s"}:
            continue
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


def optimize_squad(candidates: list[Candidate], locked_ids: set[int] | None = None, budget: int = BUDGET_TENTHS,
                   pool_sizes: dict[str, int] | None = None, beam_size: int = 6000) -> dict:
    locked_ids = locked_ids or set()
    pool_sizes = pool_sizes or {"GK": 20, "DEF": 34, "MID": 40, "FWD": 28}
    by_pos = {pos: _pool([p for p in candidates if p.position == pos], locked_ids, pool_sizes[pos]) for pos in POSITION_COUNTS}

    # State: selected tuple, cost, club counts, score, last index used for current position.
    states = [(tuple(), 0, Counter(), 0.0, -1)]
    for pos in ["GK", "DEF", "MID", "FWD"]:
        need = POSITION_COUNTS[pos]
        pool = by_pos[pos]
        # reset position-local combination index
        states = [(sel, cost, clubs, score, -1) for sel, cost, clubs, score, _ in states]
        for _slot in range(need):
            nxt = []
            for selected, cost, clubs, score, last_idx in states:
                for idx in range(last_idx + 1, len(pool)):
                    p = pool[idx]
                    if p.element in {x.element for x in selected}:
                        continue
                    new_cost = cost + p.cost
                    if new_cost > budget:
                        continue
                    if clubs[p.team_id] >= MAX_PER_CLUB:
                        continue
                    cc = clubs.copy(); cc[p.team_id] += 1
                    nxt.append((selected + (p,), new_cost, cc, score + p.objective, idx))
            nxt.sort(key=lambda s: (s[3], -s[1]), reverse=True)
            states = nxt[:beam_size]
            if not states:
                raise RuntimeError(f"no legal optimizer state while selecting {pos}")

    best = max(states, key=lambda s: (s[3], -s[1]))
    ok, reason = validate_squad(best[0], budget)
    if not ok:
        raise RuntimeError(f"optimizer produced invalid squad: {reason}")
    return {
        "players": list(best[0]),
        "cost": best[1],
        "itb": budget - best[1],
        "objective": best[3],
        "screened_players": len(candidates),
        "pool_sizes": pool_sizes,
    }


def squad_metrics(players: Iterable[Candidate]) -> dict:
    ps = list(players)
    return {
        "cost": sum(p.cost for p in ps),
        "objective": round(sum(p.objective for p in ps), 4),
        "xpts_3": round(sum(p.x3 for p in ps), 2),
        "xpts_5": round(sum(p.x5 for p in ps), 2),
        "xpts_10": round(sum(p.x10 for p in ps), 2),
        "xpts_15": round(sum(p.x15 for p in ps), 2),
    }


def classify_gain(delta_objective: float, delta_x5: float) -> str:
    if delta_x5 >= 5.0 and delta_objective >= 0.8:
        return "MATERIAL_UPGRADE"
    if delta_x5 >= 2.0 and delta_objective >= 0.3:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_15"


def decision_report(predictions: dict, universe: dict, locked: dict, budget: int = BUDGET_TENTHS) -> dict:
    candidates = build_candidates(predictions, universe)
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
    out_ids = locked_ids - target_ids
    in_ids = target_ids - locked_ids
    outs = sorted((by_id[x] for x in out_ids), key=lambda p: (p.position, p.name))
    ins = sorted((by_id[x] for x in in_ids), key=lambda p: (p.position, p.name))
    delta_obj = target_m["objective"] - current_m["objective"]
    delta_x5 = target_m["xpts_5"] - current_m["xpts_5"]

    direct = []
    baseline_itb = int(locked.get("itb_tenths", 0) or 0)
    for owned in current:
        alternatives = [p for p in candidates if p.position == owned.position and p.element not in locked_ids and p.cost <= owned.cost + baseline_itb]
        alternatives.sort(key=lambda p: p.objective, reverse=True)
        if alternatives:
            c = alternatives[0]
            direct.append({"owned": owned.element,"owned_name": owned.name,"challenger": c.element,"challenger_name": c.name,"position": owned.position,"cost_delta": c.cost-owned.cost,"objective_delta": round(c.objective-owned.objective,4),"xpts5_delta": round(c.x5-owned.x5,2)})
    direct.sort(key=lambda x: x["objective_delta"], reverse=True)

    return {
        "schema_version": 441,
        "engine": "v4.4.1-wc-optimizer",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "budget_tenths": budget,
        "baseline_itb_tenths": baseline_itb,
        "screened_players": len(candidates),
        "current": current_m,
        "optimized": target_m | {"itb": optimized["itb"]},
        "delta": {"objective": round(delta_obj, 4), "xpts_5": round(delta_x5, 2)},
        "classification": classify_gain(delta_obj, delta_x5),
        "out": [{"element": p.element,"name": p.name,"position": p.position,"cost": p.cost} for p in outs],
        "in": [{"element": p.element,"name": p.name,"position": p.position,"cost": p.cost} for p in ins],
        "optimized_elements": [p.element for p in target],
        "direct_challengers": direct[:15],
        "hard_constraints": {"squad_size":15,"positions":POSITION_COUNTS,"budget_tenths":budget,"max_per_club":MAX_PER_CLUB},
    }
