from __future__ import annotations

from src.rules import SQUAD_RULES


def legal_counts(players):
    expected = {k: int(v) for k, v in (SQUAD_RULES.get("position_counts") or {}).items()}
    max_per_club = int(SQUAD_RULES.get("max_players_per_club") or 0)
    counts = {k: 0 for k in expected}
    clubs = {}
    for p in players:
        position = p["position"]
        if position not in counts:
            return False
        counts[position] += 1
        club = p.get("team_id", p.get("team"))
        clubs[club] = clubs.get(club, 0) + 1
    return counts == expected and max(clubs.values(), default=0) <= max_per_club


def score_squad(players, horizon=5):
    total = 0.0
    for p in players:
        series = p.get("xpts_by_gw")
        total += sum(series[:horizon]) if series else float(p.get("projected_points_5gw") or p.get("projected_points") or 0)
    return total


def evaluate_package(current_squad: list[dict], outs: list[int], ins: list[dict], budget_tenths: int | None = None, hit_cost: int = 0, horizon: int = 5, captain_delta: float = 0, bench_delta: float = 0):
    remain = [p for p in current_squad if p["element"] not in set(outs)]
    candidate = remain + ins
    total = sum(int(p.get("price", p.get("now_cost", 0))) for p in candidate)
    rules_budget = int(SQUAD_RULES.get("budget_tenths") or 0)
    budget = rules_budget if budget_tenths is None else int(budget_tenths)
    expected_size = int(SQUAD_RULES.get("squad_size") or 0)
    valid = len(candidate) == expected_size and legal_counts(candidate) and total <= budget
    before = score_squad(current_squad, horizon)
    after = score_squad(candidate, horizon) if len(candidate) == expected_size else 0
    net = after - before - hit_cost + captain_delta + bench_delta if valid else None
    return {
        "valid": valid,
        "total_cost": total,
        "budget": budget,
        "horizon": horizon,
        "before_xpts": round(before, 2),
        "after_xpts": round(after, 2) if valid else None,
        "hit_cost": hit_cost,
        "captain_delta": captain_delta,
        "bench_delta": bench_delta,
        "net_gain": round(net, 2) if net is not None else None,
    }
