from __future__ import annotations

from collections import Counter
from itertools import combinations
from time import perf_counter

from src.engines import v4_full_universe_package_search as facade
from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import POSITION_COUNTS, build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, read_json


def main() -> None:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    understat = read_json(DATA / "understat_tactical_v4.json", {})
    prices = read_json(DATA / "prices.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    candidates = build_candidates(predictions, universe)
    interactions = build_tactical_interactions(predictions, universe, understat)
    reconciled, affordability = reconcile_owned_costs(candidates, locked)
    budget = int(affordability["available_budget_tenths"])
    owned_ids = {int(row["element"]) for row in locked.get("players") or []}
    by_id = {p.element: p for p in reconciled}
    current = tuple(by_id[element] for element in sorted(owned_ids))
    external, proofs = facade.safe_prune_incoming_players(
        reconciled,
        owned_ids,
        interactions=interactions,
        prices=prices,
        predictions=predictions,
        universe=universe,
    )
    pools = {pos: [] for pos in POSITION_COUNTS}
    for player in external:
        pools[player.position].append(player)
    diagnostics = {
        "search_nodes": 0,
        "incoming_combinations_considered": 0,
        "packages_rejected_by_budget": 0,
        "packages_rejected_by_budget_bound": 0,
        "packages_rejected_by_club_limit": 0,
    }
    counts = {}
    started = perf_counter()
    for k in (1, 2, 3):
        count = 0
        by_shape = Counter()
        for outs in combinations(current, k):
            out_ids = {p.element for p in outs}
            keep = tuple(p for p in current if p.element not in out_ids)
            need = Counter(p.position for p in outs)
            shape = "+".join(f"{pos}{need[pos]}" for pos in sorted(need))
            local = 0
            for _ in core._incoming_combinations(pools, need, keep, budget, diagnostics):
                local += 1
            count += local
            by_shape[shape] += local
        counts[str(k)] = {"packages": count, "by_shape": dict(by_shape)}
    print({
        "elapsed_s": round(perf_counter() - started, 3),
        "eligible_external": len(external),
        "safe_pruned": len(proofs),
        "pool_sizes": {k: len(v) for k, v in pools.items()},
        "counts": counts,
        "total": sum(v["packages"] for v in counts.values()),
        "diagnostics": diagnostics,
    }, flush=True)


if __name__ == "__main__":
    main()
