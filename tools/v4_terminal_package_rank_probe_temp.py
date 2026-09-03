from collections import Counter
from time import perf_counter

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_exact_state_frontier import (
    ExactIncomingFrontierIndex,
    _empty_state,
    _flatten_rank,
    _merge_disjoint_position,
    _skyband_insert,
    rank_dominates,
)
from src.engines.v4_wc_optimizer import Candidate, MAX_PER_CLUB
from tests.test_v4_exact_frontier_production_scale import _candidate, _pool


def risk(player: Candidate) -> dict:
    return {
        "projection_uncertainty": 0.03 + ((player.element * 3) % 41) / 100.0,
        "xmins_uncertainty": 0.02 + ((player.element * 5) % 37) / 100.0,
        "tactical_uncertainty": 0.02 + ((player.element * 7) % 31) / 100.0,
        "roster_change_uncertainty": ((player.element * 11) % 23) / 100.0,
        "price_risk": 0.02 + ((player.element * 13) % 43) / 100.0,
        "tactical_role_confidence": 0.45 + ((player.element * 17) % 50) / 100.0,
        "opponent_matchup_confidence": 0.40 + ((player.element * 19) % 55) / 100.0,
        "evidence_state": "AVAILABLE",
    }


def current_squad() -> tuple[Candidate, ...]:
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            rows.append(_candidate(element, position))
            element += 1
    return tuple(rows)


def prefix_rank_states(index, keep, positions):
    keep_signature = index._signature(tuple(keep)) if hasattr(index, "_signature") else None
    # Probe source exposes module-level signature only, so import it lazily.
    from src.engines.v4_full_universe_exact_state_frontier import _signature

    keep_signature = _signature(tuple(keep))
    rank_states = (_empty_state(),)
    capacity_cache = {}
    total_picks = len(positions) + 1
    picked_before = 0
    for position in positions:
        pool = index.pools[position]
        remaining_before = total_picks - picked_before
        remaining_after = total_picks - picked_before - 1
        base = {}
        for row in rank_states:
            bucket = index._capacity_key(keep_signature, row.club_signature, remaining_before, capacity_cache)
            if bucket is None:
                continue
            _skyband_insert(
                base.setdefault(bucket, index._new_rank_layers()),
                row,
                top_keep=index.top_keep,
                frontier_epsilon=index.frontier_epsilon,
                relation=rank_dominates,
                metrics=index.stats,
            )
        sources = _flatten_rank(base)
        pending = {}
        for player in pool:
            singleton = index._single_state[player.element]
            for prefix in sources:
                merged = singleton if not prefix.players else _merge_disjoint_position(prefix, singleton, position)
                bucket = index._capacity_key(keep_signature, merged.club_signature, remaining_after, capacity_cache)
                if bucket is not None:
                    pending.setdefault(bucket, []).append(merged)
        rank_states = tuple(
            row
            for bucket in sorted(pending)
            for layer in index._monotone_rank_layers(pending[bucket])
            for row in layer
        )
        picked_before += 1
        print("RANK_PREFIX_STAGE", position, len(rank_states), flush=True)
    return rank_states


def main():
    pools = _pool()
    current = current_squad()
    all_players = list(current) + [player for rows in pools.values() for player in rows]
    risks = {player.element: risk(player) for player in all_players}
    index = ExactIncomingFrontierIndex(pools, risks, frontier_epsilon=0.01, top_keep=12)

    defs = [p for p in current if p.position == "DEF"]
    mids = [p for p in current if p.position == "MID"]
    fwds = [p for p in current if p.position == "FWD"]
    outs = tuple(sorted((defs[0], mids[0], fwds[0]), key=lambda row: (row.position, row.element)))
    out_ids = {p.element for p in outs}
    keep = tuple(p for p in current if p.element not in out_ids)
    locked = {"itb_tenths": 1000, "free_transfers": 1, "wildcard_active": False, "free_hit_active": False}
    budget = sum(p.cost for p in current) + locked["itb_tenths"]

    baseline_profile = core._keep_profile(current)
    keep_profile = core._keep_profile_from_baseline(baseline_profile, outs)
    baseline = core.reference._fast_metrics(current, include_detail=False)
    policy = core._policy()
    hit = core._hit_cost(3, locked, policy)

    started = perf_counter()
    prefixes = prefix_rank_states(index, keep, ("DEF", "MID"))
    prefix_elapsed = perf_counter() - started

    fwd_pool = pools["FWD"]
    max_gw = tuple(max(player.gw_xpts[gw] for player in fwd_pool) for gw in range(5))
    fake = Candidate(
        element=999999,
        name="OPTIMISTIC_FWD",
        position="FWD",
        team_id=20,
        team="BOUND",
        cost=0,
        x3=sum(max_gw[:3]),
        x5=sum(max_gw),
        x10=sum(max_gw) * 2,
        x15=sum(max_gw) * 3,
        uncertainty=0.0,
        objective=max(max_gw),
        gw_xpts=max_gw,
    )

    bounded = []
    for prefix in prefixes:
        optimistic = tuple(prefix.players) + (fake,)
        metrics = core._metrics_from_profiles(keep_profile, core._chosen_profile(optimistic), include_horizons=False)
        upper = round(float(metrics["bench_adjusted_utility_5"]) - float(baseline["bench_adjusted_utility_5"]) - hit, 3)
        bounded.append((upper, prefix))
    bounded.sort(key=lambda item: item[0], reverse=True)

    keep_clubs = Counter(p.team_id for p in keep)
    top = []
    evaluated_prefixes = 0
    evaluated_packages = 0
    pruned_prefixes = 0
    eval_started = perf_counter()
    for upper, prefix in bounded:
        if len(top) >= 12:
            kth = float(top[-1]["adjusted_utility_gain_5"])
            if upper < kth:
                pruned_prefixes = len(bounded) - evaluated_prefixes
                break
        prefix_players = tuple(prefix.players)
        prefix_ids = {p.element for p in prefix_players}
        prefix_clubs = keep_clubs.copy()
        prefix_clubs.update(p.team_id for p in prefix_players)
        prefix_cost = sum(p.cost for p in prefix_players)
        evaluated_prefixes += 1
        for fwd in fwd_pool:
            if fwd.element in prefix_ids:
                continue
            if prefix_clubs[fwd.team_id] >= MAX_PER_CLUB:
                continue
            incoming = tuple(sorted(prefix_players + (fwd,), key=lambda row: (row.position, row.element)))
            if sum(p.cost for p in keep) + prefix_cost + fwd.cost > budget:
                continue
            metrics = core._metrics_from_profiles(keep_profile, core._chosen_profile(incoming))
            row = core._evaluate_package(
                outs,
                incoming,
                keep + incoming,
                metrics,
                baseline,
                locked,
                policy,
                {},
                {},
                risks,
            )
            core._retain_top(top, row, 12)
            evaluated_packages += 1

    elapsed = perf_counter() - started
    print(
        "TERMINAL_PACKAGE_RANK_PROBE",
        {
            "prefix_count": len(prefixes),
            "prefix_elapsed": round(prefix_elapsed, 3),
            "evaluated_prefixes": evaluated_prefixes,
            "pruned_prefixes": pruned_prefixes,
            "evaluated_packages": evaluated_packages,
            "rank_eval_elapsed": round(perf_counter() - eval_started, 3),
            "total_elapsed": round(elapsed, 3),
            "best": top[0]["package_id"] if top else None,
            "kth_adjusted_utility": top[-1]["adjusted_utility_gain_5"] if len(top) >= 12 else None,
            "next_upper": bounded[evaluated_prefixes][0] if evaluated_prefixes < len(bounded) else None,
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
