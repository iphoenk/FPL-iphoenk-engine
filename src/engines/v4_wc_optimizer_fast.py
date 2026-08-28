from __future__ import annotations

from heapq import heappush, heapreplace
from typing import Iterable

from src.engines import v4_wc_optimizer as base
from src.engines.v4_optimizer_primitives import gw_value as _gw_value
from src.engines.v4_wc_optimizer import Candidate, MAX_PER_CLUB, POSITION_COUNTS


DEFAULT_POOL_SIZES = {"GK": 20, "DEF": 34, "MID": 40, "FWD": 28}


def _squad_utility_fixed(players: tuple[Candidate, ...], horizon: int = 5, bench_weight: float = .12) -> float:
    """Equivalent to base.squad_utility_fast for optimizer-finalist position order.

    The WC beam selects positions in the fixed order GK, DEF, MID, FWD, so the
    final 15-player tuple has deterministic slices. Avoiding a dictionary/grouping
    pass for every finalist removes repeated Python allocation without changing
    formation or scoring semantics.
    """
    if len(players) != 15:
        return base.squad_utility_fast(players, horizon, bench_weight)
    gks = players[:2]
    defs = players[2:7]
    mids = players[7:12]
    fwds = players[12:15]
    total_utility = 0.0
    for index in range(horizon):
        gk = max(_gw_value(p, index) for p in gks)
        dv = sorted((_gw_value(p, index) for p in defs), reverse=True)
        mv = sorted((_gw_value(p, index) for p in mids), reverse=True)
        fv = sorted((_gw_value(p, index) for p in fwds), reverse=True)
        dp = [0.0]
        mp = [0.0]
        fp = [0.0]
        for value in dv:
            dp.append(dp[-1] + value)
        for value in mv:
            mp.append(mp[-1] + value)
        for value in fv:
            fp.append(fp[-1] + value)
        xi = max(
            gk + dp[3] + mp[4] + fp[3], gk + dp[3] + mp[5] + fp[2],
            gk + dp[4] + mp[3] + fp[3], gk + dp[4] + mp[4] + fp[2],
            gk + dp[4] + mp[5] + fp[1], gk + dp[5] + mp[2] + fp[3],
            gk + dp[5] + mp[3] + fp[2], gk + dp[5] + mp[4] + fp[1],
        )
        squad_total = (
            sum(_gw_value(p, index) for p in gks)
            + sum(_gw_value(p, index) for p in defs)
            + sum(_gw_value(p, index) for p in mids)
            + sum(_gw_value(p, index) for p in fwds)
        )
        total_utility += xi + bench_weight * (squad_total - xi)
    return total_utility


def _exact_streaming_beam(
    states: list[tuple],
    pool: list[Candidate],
    costs: list[int],
    team_shifts: list[int],
    team_bits: list[int],
    objectives: list[float],
    budget: int,
    beam_size: int,
) -> tuple[list[tuple], dict]:
    """Return the exact same top-k ordering as materialize+nlargest.

    Ranking is (heuristic, -cost), with original generation order resolving exact
    ties. The heap carries -sequence solely to preserve heapq.nlargest stability.
    Because the pool is objective-nonincreasing, once a state's best remaining
    primary score is strictly below the heap floor, later candidates cannot enter
    the beam. Equality is never pruned because cost/tie order can still matter.
    """
    heap: list[tuple[float, int, int, tuple]] = []
    sequence = 0
    generated = 0
    bound_pruned = 0
    plen = len(pool)
    monotonic = all(objectives[i] >= objectives[i + 1] for i in range(max(0, plen - 1)))

    for selected, cost, signature, score, last_idx in states:
        for idx in range(last_idx + 1, plen):
            if monotonic and len(heap) >= beam_size and score + objectives[idx] < heap[0][0]:
                bound_pruned += plen - idx
                break
            new_cost = cost + costs[idx]
            if new_cost > budget:
                continue
            shift = team_shifts[idx]
            if ((signature >> shift) & 0b11) >= MAX_PER_CLUB:
                continue
            new_score = score + objectives[idx]
            state = (
                selected + (pool[idx],),
                new_cost,
                signature + team_bits[idx],
                new_score,
                idx,
            )
            # Earlier generated states win exact key ties, matching heapq.nlargest.
            entry = (new_score, -new_cost, -sequence, state)
            sequence += 1
            generated += 1
            if len(heap) < beam_size:
                heappush(heap, entry)
            elif entry[:3] > heap[0][:3]:
                heapreplace(heap, entry)

    ordered = [entry[3] for entry in sorted(heap, key=lambda row: row[:3], reverse=True)]
    return ordered, {
        "generated_states": generated,
        "objective_bound_pruned": bound_pruned,
        "objective_order_monotonic": monotonic,
    }


def optimize_squad_fast(
    candidates: list[Candidate],
    locked_ids: set[int] | None = None,
    budget: int = base.BUDGET_TENTHS,
    pool_sizes: dict[str, int] | None = None,
    beam_size: int = 6000,
) -> dict:
    locked_ids = locked_ids or set()
    pool_sizes = pool_sizes or dict(DEFAULT_POOL_SIZES)
    by_pos = {
        pos: base._pool([p for p in candidates if p.position == pos], locked_ids, pool_sizes[pos])
        for pos in POSITION_COUNTS
    }
    states: list[tuple] = [(tuple(), 0, 0, 0.0, -1)]
    generated_states = 0
    bound_pruned = 0
    monotonic_all = True

    for pos in ("GK", "DEF", "MID", "FWD"):
        pool = by_pos[pos]
        costs = [p.cost for p in pool]
        objectives = [p.objective for p in pool]
        team_shifts = [base._club_shift(p.team_id) for p in pool]
        team_bits = [1 << shift for shift in team_shifts]
        states = [(selected, cost, sig, score, -1) for selected, cost, sig, score, _ in states]
        for _slot in range(POSITION_COUNTS[pos]):
            states, stats = _exact_streaming_beam(
                states, pool, costs, team_shifts, team_bits, objectives, budget, beam_size
            )
            generated_states += stats["generated_states"]
            bound_pruned += stats["objective_bound_pruned"]
            monotonic_all = monotonic_all and stats["objective_order_monotonic"]
            if not states:
                raise RuntimeError(f"no legal optimizer state while selecting {pos}")

    best = max(
        (
            (_squad_utility_fixed(selected, 5), heuristic, -cost, selected, cost)
            for selected, cost, _signature, heuristic, _ in states
        ),
        key=lambda row: (row[0], row[1], row[2]),
    )
    ok, reason = base.validate_squad(best[3], budget)
    if not ok:
        raise RuntimeError(f"optimizer winner failed legality invariant: {reason}")
    return {
        "players": list(best[3]),
        "cost": best[4],
        "itb": budget - best[4],
        "objective": best[1],
        "xi_utility_5": best[0],
        "screened_players": len(candidates),
        "pool_sizes": pool_sizes,
        "beam_size": beam_size,
        "performance": {
            "fast_finalist_scoring": True,
            "winner_only_legality_check": True,
            "packed_club_signature": True,
            "counter_copy_eliminated": True,
            "precomputed_club_bits": True,
            "bounded_top_k_same_beam": True,
            "exact_streaming_topk": True,
            "stable_tie_semantics": True,
            "safe_objective_bound": monotonic_all,
            "fixed_position_finalist_scoring": True,
            "finalist_materialization_removed": True,
            "generated_states": generated_states,
            "objective_bound_pruned": bound_pruned,
        },
    }


def decision_report_from_candidates_fast(
    candidates: list[Candidate], locked: dict, budget: int | None = None
) -> dict:
    candidates, affordability = base.reconcile_owned_costs(candidates, locked)
    derived_budget = int(affordability["available_budget_tenths"])
    budget = derived_budget if budget is None else int(budget)
    if budget != derived_budget:
        raise RuntimeError(f"budget override {budget} disagrees with reconciled sell value {derived_budget}")

    by_id = {p.element: p for p in candidates}
    locked_ids = {int(p["element"]) for p in locked.get("players", [])}
    missing = sorted(locked_ids - set(by_id))
    if missing:
        raise RuntimeError(f"locked players absent from candidate universe: {missing}")
    current = [by_id[element] for element in locked_ids]
    ok, reason = base.validate_squad(current, budget)
    if not ok:
        raise RuntimeError(f"locked squad invalid: {reason}")

    optimized = optimize_squad_fast(candidates, locked_ids=locked_ids, budget=budget)
    target = optimized["players"]
    current_m = base.squad_metrics(current)
    target_m = base.squad_metrics(target)
    target_ids = {p.element for p in target}
    outs = sorted((by_id[x] for x in locked_ids - target_ids), key=lambda p: (p.position, p.name))
    ins = sorted((by_id[x] for x in target_ids - locked_ids), key=lambda p: (p.position, p.name))
    dx = target_m["best_xi_xpts_5"] - current_m["best_xi_xpts_5"]
    du = target_m["bench_adjusted_utility_5"] - current_m["bench_adjusted_utility_5"]

    direct = []
    baseline_itb = int(locked.get("itb_tenths", 0) or 0)
    external = [p for p in candidates if p.element not in locked_ids]
    ext_by_pos = {
        pos: sorted([p for p in external if p.position == pos], key=lambda p: p.objective, reverse=True)
        for pos in POSITION_COUNTS
    }
    for owned in current:
        for challenger in ext_by_pos[owned.position]:
            if challenger.cost <= owned.cost + baseline_itb:
                direct.append({
                    "owned": owned.element,
                    "owned_name": owned.name,
                    "challenger": challenger.element,
                    "challenger_name": challenger.name,
                    "position": owned.position,
                    "cost_delta": challenger.cost - owned.cost,
                    "objective_delta": round(challenger.objective - owned.objective, 4),
                    "xpts5_delta": round(challenger.x5 - owned.x5, 2),
                })
                break
    direct.sort(key=lambda row: row["objective_delta"], reverse=True)

    return {
        "schema_version": 492,
        "engine": "v4.9.3-wc-optimizer-exact-streaming",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "budget_tenths": budget,
        "baseline_itb_tenths": baseline_itb,
        "affordability": affordability,
        "screened_players": len(candidates),
        "current": current_m,
        "optimized": target_m | {"itb": optimized["itb"]},
        "delta": {
            "best_xi_xpts_5": round(dx, 2),
            "bench_adjusted_utility_5": round(du, 2),
        },
        "classification": base.classify_gain(du, dx),
        "out": [
            {"element": p.element, "name": p.name, "position": p.position, "sell_cost": p.cost}
            for p in outs
        ],
        "in": [
            {"element": p.element, "name": p.name, "position": p.position, "now_cost": p.cost}
            for p in ins
        ],
        "optimized_elements": [p.element for p in target],
        "direct_challengers": direct[:15],
        "hard_constraints": {
            "squad_size": 15,
            "positions": POSITION_COUNTS,
            "budget_tenths": budget,
            "max_per_club": MAX_PER_CLUB,
            "legal_xi": True,
            "owned_price_basis": "sell_cost",
            "unowned_price_basis": "now_cost",
        },
        "performance": optimized["performance"] | {
            "beam_size_unchanged": optimized["beam_size"] == 6000,
            "direct_challenger_position_index": True,
            "value_term_consumed": True,
            "search_quality_reduction": False,
        },
    }
