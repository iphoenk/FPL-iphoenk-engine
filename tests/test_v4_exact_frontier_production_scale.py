from __future__ import annotations

from collections import Counter
from time import perf_counter

from src.engines.v4_full_universe_exact_state_frontier import ExactIncomingFrontierIndex
from src.engines.v4_wc_optimizer import Candidate


def _candidate(element: int, position: str) -> Candidate:
    team = 1 + ((element * 7) % 20)
    base = 1.25 + ((element * 37) % 240) / 80.0
    gw = tuple(
        max(0.05, base + (((element * (index + 11)) % 29) - 14) * 0.035)
        for index in range(5)
    )
    return Candidate(
        element=element,
        name=f"P{element}",
        position=position,
        team_id=team,
        team=f"T{team}",
        cost=40 + ((element * 13) % 86),
        x3=sum(gw[:3]),
        x5=sum(gw),
        x10=sum(gw) * 1.92 + ((element * 17) % 19) / 25.0,
        x15=sum(gw) * 2.81 + ((element * 23) % 31) / 30.0,
        uncertainty=0.05 + ((element * 11) % 35) / 100.0,
        objective=base + ((element * 5) % 17) / 50.0,
        gw_xpts=gw,
    )


def _pool() -> dict[str, list[Candidate]]:
    counts = (("GK", 60), ("DEF", 170), ("MID", 170), ("FWD", 100))
    result = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    element = 1000
    for position, count in counts:
        for _ in range(count):
            result[position].append(_candidate(element, position))
            element += 1
    return result


def _risks(pools: dict[str, list[Candidate]]) -> dict[int, dict]:
    return {
        player.element: {
            "projection_uncertainty": 0.03 + ((player.element * 3) % 41) / 100.0,
            "xmins_uncertainty": 0.02 + ((player.element * 5) % 37) / 100.0,
            "tactical_uncertainty": 0.02 + ((player.element * 7) % 31) / 100.0,
            "roster_change_uncertainty": ((player.element * 11) % 23) / 100.0,
            "price_risk": 0.02 + ((player.element * 13) % 43) / 100.0,
            "tactical_role_confidence": 0.45 + ((player.element * 17) % 50) / 100.0,
            "opponent_matchup_confidence": 0.40 + ((player.element * 19) % 55) / 100.0,
        }
        for rows in pools.values()
        for player in rows
    }


def _diagnostics() -> dict:
    return {
        "incoming_combinations_considered": 0,
        "packages_rejected_by_budget": 0,
        "packages_rejected_by_club_limit": 0,
    }


def test_production_scale_indexed_frontier_regression_hundreds_of_candidates():
    pools = _pool()
    assert sum(len(rows) for rows in pools.values()) == 500
    assert len({player.team_id for rows in pools.values() for player in rows}) == 20

    index = ExactIncomingFrontierIndex(
        pools,
        _risks(pools),
        frontier_epsilon=0.01,
        top_keep=12,
    )

    started = perf_counter()
    k2 = list(index.iter_legal(Counter({"MID": 2}), tuple(), 10_000, _diagnostics()))
    k3 = list(index.iter_legal(Counter({"DEF": 1, "MID": 1, "FWD": 1}), tuple(), 10_000, _diagnostics()))
    elapsed = perf_counter() - started

    assert k2
    assert k3
    proof = index.proof_summary()
    assert proof["canonical_top_n_best_and_frontier_exact"] is True
    assert proof["heuristic"] is False
    assert proof["candidate_cutoff"] is False
    assert proof["beam_cutoff"] is False
    assert proof["x5_indexed_frontier_insertion"] is True
    assert proof["x5_index_is_necessary_condition_only"] is True
    assert proof["scalar_rank_prefilter_before_gw_shape"] is True
    assert proof["dominance_pairs_skipped_by_x5_index"] > 0
    # This is intentionally generous for shared CI runners. The pre-fix real
    # k<=2 path exceeded 280s, so a 25s regression bound still catches the
    # structural O(N x F) failure without turning normal runner jitter red.
    assert elapsed < 25.0
