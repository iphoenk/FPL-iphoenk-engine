from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
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
    """Multi-horizon WC objective expressed as expected points per GW.

    Primary horizon is 3-5 GWs, with a smaller strategic 10-15 GW tail.
    Uncertainty receives a modest penalty so fragile projections do not dominate.
    """
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
        status = u.get("status")
        if status in {"u", "s"}:
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


def _position_combos(cands: list[Candidate], n: int, locked_ids: set[int], pool_size: int) -> list[tuple[Candidate, ...]]:
    ranked = sorted(cands, key=lambda p: (p.objective, p.x5, -p.cost), reverse=True)
    forced = [p for p in ranked if p.element in locked_ids]
    pool = ranked[:pool_size]
    seen = {p.element for p in pool}
    pool.extend(p for p in forced if p.element not in seen)
    combos = []
    for combo in combinations(pool, n):
        clubs = Counter(p.team_id for p in combo)
        if max(clubs.values(), default=0) <= MAX_PER_CLUB:
            combos.append(combo)
    combos.sort(key=lambda c: sum(p.objective for p in c), reverse=True)
    # Keep a generous frontier. All universe players are screened before pruning.
    return combos[:12000]


def optimize_squad(candidates: list[Candidate], locked_ids: set[int] | None = None, budget: int = BUDGET_TENTHS,
                   pool_sizes: dict[str, int] | None = None, beam_size: int = 12000) -> dict:
    locked_ids = locked_ids or set()
    pool_sizes = pool_sizes or {"GK": 20, "DEF": 34, "MID": 40, "FWD": 28}
    by_pos = {pos: [p for p in candidates if p.position == pos] for pos in POSITION_COUNTS}
    combo_sets = {pos: _position_combos(by_pos[pos], n, locked_ids, pool_sizes[pos]) for pos, n in POSITION_COUNTS.items()}

    # Beam joins position-complete combinations while enforcing budget and club limits.
    states = [(tuple(), 0, Counter(), 0.0)]
    for pos in ["GK", "DEF", "MID", "FWD"]:
        nxt = []
        for current, cost, clubs, score in states:
            for combo in combo_sets[pos]:
                new_cost = cost + sum(p.cost for p in combo)
                if new_cost > budget:
                    continue
                cc = clubs.copy()
                valid = True
                for p in combo:
                    cc[p.team_id] += 1
                    if cc[p.team_id] > MAX_PER_CLUB:
                        valid = False
                        break
                if not valid:
                    continue
                nxt.append((current + combo, new_cost, cc, score + sum(p.objective for p in combo)))
        nxt.sort(key=lambda s: s[3], reverse=True)
        states = nxt[:beam_size]
        if not states:
            raise RuntimeError(f"no legal optimizer state after {pos}")

    best = states[0]
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
    # Squad objective is per-GW across 15 players. Require a meaningful margin before disturbing a WC lock.
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
    out_ids = locked_ids - {p.element for p in target}
    in_ids = {p.element for p in target} - locked_ids
    outs = sorted((by_id[x] for x in out_ids), key=lambda p: p.position)
    ins = sorted((by_id[x] for x in in_ids), key=lambda p: p.position)
    delta_obj = target_m["objective"] - current_m["objective"]
    delta_x5 = target_m["xpts_5"] - current_m["xpts_5"]

    # Direct challengers: best same-position alternatives against every locked player.
    direct = []
    for owned in current:
        alternatives = [p for p in candidates if p.position == owned.position and p.element not in locked_ids and p.cost <= owned.cost + int(locked.get("itb_tenths", 0) or 0)]
        alternatives.sort(key=lambda p: p.objective, reverse=True)
        if alternatives:
            c = alternatives[0]
            direct.append({
                "owned": owned.element,
                "owned_name": owned.name,
                "challenger": c.element,
                "challenger_name": c.name,
                "position": owned.position,
                "cost_delta": c.cost - owned.cost,
                "objective_delta": round(c.objective - owned.objective, 4),
                "xpts5_delta": round(c.x5 - owned.x5, 2),
            })
    direct.sort(key=lambda x: x["objective_delta"], reverse=True)

    return {
        "schema_version": 441,
        "engine": "v4.4.1-wc-optimizer",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "budget_tenths": budget,
        "baseline_itb_tenths": int(locked.get("itb_tenths", 0) or 0),
        "screened_players": len(candidates),
        "current": current_m,
        "optimized": target_m | {"itb": optimized["itb"]},
        "delta": {"objective": round(delta_obj, 4), "xpts_5": round(delta_x5, 2)},
        "classification": classify_gain(delta_obj, delta_x5),
        "out": [{"element": p.element, "name": p.name, "position": p.position, "cost": p.cost} for p in outs],
        "in": [{"element": p.element, "name": p.name, "position": p.position, "cost": p.cost} for p in ins],
        "optimized_elements": [p.element for p in target],
        "direct_challengers": direct[:15],
        "hard_constraints": {"squad_size": 15, "positions": POSITION_COUNTS, "budget_tenths": budget, "max_per_club": MAX_PER_CLUB},
    }
