from __future__ import annotations

from collections import Counter

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_exact_state_frontier import ExactIncomingFrontierIndex
from src.engines.v4_wc_optimizer import Candidate


def _candidate(
    element: int,
    position: str,
    team: int,
    cost: int,
    base: float,
    *,
    x5_offset: float = 0.0,
) -> Candidate:
    gw = tuple(base + index * 0.07 for index in range(5))
    x5 = sum(gw) + x5_offset
    return Candidate(
        element=element,
        name=f"P{element}",
        position=position,
        team_id=team,
        team=f"T{team}",
        cost=cost,
        x3=base * 3.0,
        x5=x5,
        x10=base * 10.0,
        x15=base * 15.0,
        uncertainty=0.1,
        objective=base,
        gw_xpts=gw,
    )


def _squad() -> tuple[Candidate, ...]:
    rows: list[Candidate] = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _index in range(count):
            rows.append(
                _candidate(
                    element,
                    position,
                    1 + ((element - 1) % 10),
                    40 + element,
                    1.0 + element * 0.04,
                )
            )
            element += 1
    return tuple(rows)


def _risk(players) -> dict[int, dict]:
    return {
        player.element: {
            "projection_uncertainty": 0.10,
            "xmins_uncertainty": 0.10,
            "tactical_uncertainty": 0.10,
            "roster_change_uncertainty": 0.02,
            "price_risk": 0.12,
            "tactical_role_confidence": 0.75,
            "opponent_matchup_confidence": 0.72,
        }
        for player in players
    }


def _rows_for(
    incoming_rows,
    *,
    current: tuple[Candidate, ...],
    outs: tuple[Candidate, ...],
    locked: dict,
    risk_by_element: dict[int, dict],
):
    out_ids = {player.element for player in outs}
    keep = tuple(player for player in current if player.element not in out_ids)
    baseline_profile = core._keep_profile(current)
    keep_profile = core._keep_profile_from_baseline(baseline_profile, outs)
    baseline = core.reference._fast_metrics(current, include_detail=False)
    policy = core._policy()
    rows = []
    for incoming in incoming_rows:
        incoming = tuple(sorted(incoming, key=lambda row: (row.position, row.element)))
        metrics = core._metrics_from_profiles(keep_profile, core._chosen_profile(incoming))
        rows.append(
            core._evaluate_package(
                tuple(sorted(outs, key=lambda row: (row.position, row.element))),
                incoming,
                keep + incoming,
                metrics,
                baseline,
                locked,
                policy,
                {},
                {},
                risk_by_element,
            )
        )
    return rows


def _frontier_ids(rows: list[dict]) -> list[str]:
    epsilon = float((core._policy().get("search") or {}).get("frontier_epsilon") or 0.01)
    frontier: list[dict] = []
    for row in rows:
        core._frontier_insert(frontier, core._compact_for_frontier(row), epsilon)
    frontier.sort(key=core._rank, reverse=True)
    return [str(row["package_id"]) for row in frontier]


def test_exact_state_frontier_preserves_best_and_efficient_frontier_for_small_k1_k2_k3_oracle():
    current = _squad()
    external = {
        "GK": [
            _candidate(101, "GK", 11, 44, 2.3),
            _candidate(102, "GK", 12, 45, 2.1),
        ],
        "DEF": [
            _candidate(111, "DEF", 11, 45, 3.3),
            _candidate(112, "DEF", 12, 48, 2.5),
            _candidate(113, "DEF", 13, 47, 2.8),
        ],
        "MID": [
            _candidate(121, "MID", 12, 56, 4.1),
            _candidate(122, "MID", 11, 59, 3.0),
            _candidate(123, "MID", 13, 57, 3.4),
        ],
        "FWD": [
            _candidate(131, "FWD", 14, 62, 4.3),
            _candidate(132, "FWD", 15, 64, 3.8),
        ],
    }
    all_players = current + tuple(player for rows in external.values() for player in rows)
    risks = _risk(all_players)
    epsilon = float((core._policy().get("search") or {}).get("frontier_epsilon") or 0.01)
    index = ExactIncomingFrontierIndex(external, risks, frontier_epsilon=epsilon, top_keep=1)
    locked = {"itb_tenths": 80, "free_transfers": 1, "wildcard_active": False, "free_hit_active": False}
    budget = sum(player.cost for player in current) + locked["itb_tenths"]

    cases = (
        (current[2],),
        (current[2], current[7]),
        (current[2], current[7], current[12]),
    )
    for outs in cases:
        out_ids = {player.element for player in outs}
        keep = tuple(player for player in current if player.element not in out_ids)
        need = Counter(player.position for player in outs)
        raw_diagnostics = {
            "search_nodes": 0,
            "incoming_combinations_considered": 0,
            "packages_rejected_by_budget": 0,
            "packages_rejected_by_budget_bound": 0,
            "packages_rejected_by_club_limit": 0,
        }
        raw = list(core._incoming_combinations(external, need, keep, budget, raw_diagnostics))
        compressed_diagnostics = {
            "incoming_combinations_considered": 0,
            "packages_rejected_by_budget": 0,
            "packages_rejected_by_club_limit": 0,
        }
        compressed = list(index.iter_legal(need, keep, budget, compressed_diagnostics))
        raw_rows = _rows_for(raw, current=current, outs=outs, locked=locked, risk_by_element=risks)
        compressed_rows = _rows_for(compressed, current=current, outs=outs, locked=locked, risk_by_element=risks)

        assert max(raw_rows, key=core._rank)["package_id"] == max(compressed_rows, key=core._rank)["package_id"]
        assert _frontier_ids(raw_rows) == _frontier_ids(compressed_rows)

    proof = index.proof_summary()
    assert proof["canonical_top_n_best_and_frontier_exact"] is True
    assert proof["pareto_skyband_depth"] == 1
    assert proof["heuristic"] is False
    assert proof["cross_signature_partial_pruning"] is False
    assert proof["strictness_survives_canonical_rounding_and_frontier_epsilon"] is True
    assert proof["exact_states_pruned"] > 0


def test_pareto_skyband_preserves_exact_top_two_rank_order():
    current = _squad()
    outs = (current[7],)
    pool = [
        _candidate(201, "MID", 11, 45, 5.0),
        _candidate(202, "MID", 11, 46, 4.5),
        _candidate(203, "MID", 11, 47, 4.0),
        _candidate(204, "MID", 11, 48, 3.5),
    ]
    pools = {"GK": [], "DEF": [], "MID": pool, "FWD": []}
    risks = _risk(current + tuple(pool))
    index = ExactIncomingFrontierIndex(pools, risks, frontier_epsilon=0.01, top_keep=2)
    keep = tuple(player for player in current if player.element != outs[0].element)
    budget = sum(player.cost for player in current) + 100
    diagnostics = {"incoming_combinations_considered": 0, "packages_rejected_by_budget": 0, "packages_rejected_by_club_limit": 0}
    compressed = list(index.iter_legal(Counter({"MID": 1}), keep, budget, diagnostics))
    raw_diag = {"search_nodes": 0, "incoming_combinations_considered": 0, "packages_rejected_by_budget": 0, "packages_rejected_by_budget_bound": 0, "packages_rejected_by_club_limit": 0}
    raw = list(core._incoming_combinations(pools, Counter({"MID": 1}), keep, budget, raw_diag))
    locked = {"itb_tenths": 100, "free_transfers": 1, "wildcard_active": False, "free_hit_active": False}
    raw_rows = sorted(_rows_for(raw, current=current, outs=outs, locked=locked, risk_by_element=risks), key=core._rank, reverse=True)
    compressed_rows = sorted(_rows_for(compressed, current=current, outs=outs, locked=locked, risk_by_element=risks), key=core._rank, reverse=True)
    assert [row["package_id"] for row in compressed_rows[:2]] == [row["package_id"] for row in raw_rows[:2]]
    assert len(compressed_rows) == 2
    assert index.proof_summary()["exact_states_pruned"] > 0


def test_different_club_signature_is_not_pruned_before_keep_legality_is_known():
    keep = (
        _candidate(1, "GK", 1, 45, 1.0),
        _candidate(2, "DEF", 1, 45, 1.0),
        _candidate(3, "MID", 1, 45, 1.0),
    )
    stronger_illegal = _candidate(301, "FWD", 1, 50, 5.0)
    weaker_legal = _candidate(302, "FWD", 2, 55, 3.0)
    pools = {"GK": [], "DEF": [], "MID": [], "FWD": [stronger_illegal, weaker_legal]}
    risks = _risk(keep + (stronger_illegal, weaker_legal))
    index = ExactIncomingFrontierIndex(pools, risks, frontier_epsilon=0.01, top_keep=1)
    diagnostics = {"incoming_combinations_considered": 0, "packages_rejected_by_budget": 0, "packages_rejected_by_club_limit": 0}
    rows = list(index.iter_legal(Counter({"FWD": 1}), keep, 1000, diagnostics))
    assert [tuple(player.element for player in row) for row in rows] == [(302,)]
    assert diagnostics["packages_rejected_by_club_limit"] == 1


def test_rounding_boundary_and_exact_ties_are_not_compressed():
    right = _candidate(401, "MID", 11, 50, 3.0)
    left = _candidate(402, "MID", 11, 50, 3.0, x5_offset=0.015)
    tie = _candidate(403, "MID", 11, 50, 3.0)
    pools = {"GK": [], "DEF": [], "MID": [right, left, tie], "FWD": []}
    risks = _risk((right, left, tie))
    index = ExactIncomingFrontierIndex(pools, risks, frontier_epsilon=0.01, top_keep=1)
    diagnostics = {"incoming_combinations_considered": 0, "packages_rejected_by_budget": 0, "packages_rejected_by_club_limit": 0}
    rows = list(index.iter_legal(Counter({"MID": 1}), tuple(), 1000, diagnostics))
    assert {row[0].element for row in rows} == {401, 402, 403}
