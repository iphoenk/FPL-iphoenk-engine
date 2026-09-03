from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterator

from src.engines.v4_optimizer_primitives import gw_value
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, Candidate


CONTRACT = "V4_FULL_UNIVERSE_EXACT_STATE_FRONTIER_V1"
_POSITIONS = tuple(POSITION_COUNTS)
_POSITION_ORDER = {position: index for index, position in enumerate(_POSITIONS)}
_TWO_DP_ROUND_ERROR = 0.010000000001
_FOUR_DP_ROUND_ERROR = 0.000100000001


@dataclass(frozen=True)
class IncomingState:
    players: tuple[Candidate, ...]
    club_signature: int
    cost: int
    x3: float
    x5: float
    x10: float
    x15: float
    projection_uncertainty: float
    xmins_uncertainty: float
    tactical_uncertainty: float
    roster_change_uncertainty: float
    price_risk: float
    tactical_role_confidence: float
    opponent_matchup_confidence: float
    gw_values: tuple[tuple[tuple[float, ...], ...], ...]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _player_signature(player: Candidate) -> int:
    if player.team_id < 1 or player.team_id > 20:
        raise RuntimeError(f"invalid FPL team id for exact state compression: {player.team_id}")
    return 1 << ((player.team_id - 1) * 2)


def _signature(players: tuple[Candidate, ...]) -> int:
    value = 0
    for player in players:
        value += _player_signature(player)
    return value


def _club_count(signature: int, team_id: int) -> int:
    return (signature >> ((team_id - 1) * 2)) & 0b11


def _legal_with_keep(keep_signature: int, incoming_signature: int) -> bool:
    return all(
        _club_count(keep_signature, team_id) + _club_count(incoming_signature, team_id) <= MAX_PER_CLUB
        for team_id in range(1, 21)
    )


def _risk_value(risk_by_element: dict[int, dict], player: Candidate, key: str) -> float:
    default = 0.2 if key == "price_risk" else 0.0
    return _f((risk_by_element.get(player.element) or {}).get(key), default)


def _gw_shape(players: tuple[Candidate, ...]) -> tuple[tuple[tuple[float, ...], ...], ...]:
    return tuple(
        tuple(
            tuple(sorted((float(gw_value(player, gw_index)) for player in players if player.position == position), reverse=True))
            for gw_index in range(5)
        )
        for position in _POSITIONS
    )


def _state(players: tuple[Candidate, ...], risk_by_element: dict[int, dict]) -> IncomingState:
    ordered = tuple(sorted(players, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
    return IncomingState(
        players=ordered,
        club_signature=_signature(ordered),
        cost=sum(player.cost for player in ordered),
        x3=sum(float(player.x3) for player in ordered),
        x5=sum(float(player.x5) for player in ordered),
        x10=sum(float(player.x10) for player in ordered),
        x15=sum(float(player.x15) for player in ordered),
        projection_uncertainty=sum(_risk_value(risk_by_element, player, "projection_uncertainty") for player in ordered),
        xmins_uncertainty=sum(_risk_value(risk_by_element, player, "xmins_uncertainty") for player in ordered),
        tactical_uncertainty=sum(_risk_value(risk_by_element, player, "tactical_uncertainty") for player in ordered),
        roster_change_uncertainty=sum(_risk_value(risk_by_element, player, "roster_change_uncertainty") for player in ordered),
        price_risk=sum(_risk_value(risk_by_element, player, "price_risk") for player in ordered),
        tactical_role_confidence=sum(_risk_value(risk_by_element, player, "tactical_role_confidence") for player in ordered),
        opponent_matchup_confidence=sum(_risk_value(risk_by_element, player, "opponent_matchup_confidence") for player in ordered),
        gw_values=_gw_shape(ordered),
    )


def _empty_state() -> IncomingState:
    empty_gw = tuple(tuple(tuple() for _ in range(5)) for _ in _POSITIONS)
    return IncomingState(
        players=tuple(), club_signature=0, cost=0,
        x3=0.0, x5=0.0, x10=0.0, x15=0.0,
        projection_uncertainty=0.0, xmins_uncertainty=0.0,
        tactical_uncertainty=0.0, roster_change_uncertainty=0.0,
        price_risk=0.0, tactical_role_confidence=0.0,
        opponent_matchup_confidence=0.0, gw_values=empty_gw,
    )


def _merge(left: IncomingState, right: IncomingState) -> IncomingState:
    players = tuple(sorted(left.players + right.players, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))
    gw_values = []
    for pos_index, _position in enumerate(_POSITIONS):
        per_gw = []
        for gw_index in range(5):
            per_gw.append(tuple(sorted(left.gw_values[pos_index][gw_index] + right.gw_values[pos_index][gw_index], reverse=True)))
        gw_values.append(tuple(per_gw))
    return IncomingState(
        players=players,
        club_signature=left.club_signature + right.club_signature,
        cost=left.cost + right.cost,
        x3=left.x3 + right.x3,
        x5=left.x5 + right.x5,
        x10=left.x10 + right.x10,
        x15=left.x15 + right.x15,
        projection_uncertainty=left.projection_uncertainty + right.projection_uncertainty,
        xmins_uncertainty=left.xmins_uncertainty + right.xmins_uncertainty,
        tactical_uncertainty=left.tactical_uncertainty + right.tactical_uncertainty,
        roster_change_uncertainty=left.roster_change_uncertainty + right.roster_change_uncertainty,
        price_risk=left.price_risk + right.price_risk,
        tactical_role_confidence=left.tactical_role_confidence + right.tactical_role_confidence,
        opponent_matchup_confidence=left.opponent_matchup_confidence + right.opponent_matchup_confidence,
        gw_values=tuple(gw_values),
    )


def _gw_no_worse(left: IncomingState, right: IncomingState) -> bool:
    for pos_index, _position in enumerate(_POSITIONS):
        for gw_index in range(5):
            left_values = left.gw_values[pos_index][gw_index]
            right_values = right.gw_values[pos_index][gw_index]
            if len(left_values) != len(right_values):
                return False
            if any(left_value < right_value for left_value, right_value in zip(left_values, right_values)):
                return False
    return True


def _guaranteed_rank_strict(left: IncomingState, right: IncomingState) -> bool:
    # Rank has no dominance epsilon. A raw horizon gap larger than the total 2dp
    # rounding error guarantees a positive published gap. Lower integer cost is an
    # exact later rank tie-breaker if all earlier dimensions remain equal.
    return (
        left.x5 > right.x5 + _TWO_DP_ROUND_ERROR
        or left.x15 > right.x15 + _TWO_DP_ROUND_ERROR
        or left.cost < right.cost
    )


def _guaranteed_frontier_strict(left: IncomingState, right: IncomingState, frontier_epsilon: float) -> bool:
    # Frontier strictness requires a published gap strictly greater than epsilon.
    # Horizon totals are rounded to 2dp. Direct risk/confidence averages are rounded
    # to 4dp; uncertainty deltas are not used for strictness because max(0, delta)
    # can flatten a raw improvement to an equal zero after outgoing subtraction.
    k = max(1, len(left.players))
    horizon_gap = float(frontier_epsilon) + _TWO_DP_ROUND_ERROR
    sum_gap = (float(frontier_epsilon) + _FOUR_DP_ROUND_ERROR) * k
    return (
        left.x3 > right.x3 + horizon_gap
        or left.x5 > right.x5 + horizon_gap
        or left.x10 > right.x10 + horizon_gap
        or left.x15 > right.x15 + horizon_gap
        or left.price_risk + sum_gap < right.price_risk
        or left.tactical_role_confidence > right.tactical_role_confidence + sum_gap
        or left.opponent_matchup_confidence > right.opponent_matchup_confidence + sum_gap
    )


def dominates(left: IncomingState, right: IncomingState, *, frontier_epsilon: float) -> bool:
    """Conservative proof that one state cannot affect canonical best/frontier.

    Compression is only applied inside identical incoming club signatures. Every
    future keep therefore sees identical club-slot feasibility. The left state is
    required to be no worse on every monotone input to XI, utility, horizon, risk
    and confidence, plus a strict improvement that provably survives canonical
    rounding and the governed frontier epsilon. Tiny/equal float ties are retained
    so package-id tie ordering cannot be changed by compression.
    """
    if frontier_epsilon < 0:
        raise ValueError("frontier_epsilon must be non-negative")
    if not _gw_no_worse(left, right):
        return False
    minimize_pairs = (
        (left.cost, right.cost),
        (left.projection_uncertainty, right.projection_uncertainty),
        (left.xmins_uncertainty, right.xmins_uncertainty),
        (left.tactical_uncertainty, right.tactical_uncertainty),
        (left.roster_change_uncertainty, right.roster_change_uncertainty),
        (left.price_risk, right.price_risk),
    )
    maximize_pairs = (
        (left.x3, right.x3),
        (left.x5, right.x5),
        (left.x10, right.x10),
        (left.x15, right.x15),
        (left.tactical_role_confidence, right.tactical_role_confidence),
        (left.opponent_matchup_confidence, right.opponent_matchup_confidence),
    )
    if any(a > b for a, b in minimize_pairs):
        return False
    if any(a < b for a, b in maximize_pairs):
        return False
    return _guaranteed_rank_strict(left, right) and _guaranteed_frontier_strict(left, right, frontier_epsilon)


def _insert_exact(frontier: list[IncomingState], candidate: IncomingState, *, frontier_epsilon: float) -> tuple[bool, int]:
    for incumbent in frontier:
        if dominates(incumbent, candidate, frontier_epsilon=frontier_epsilon):
            return False, 1
    retained = [
        incumbent for incumbent in frontier
        if not dominates(candidate, incumbent, frontier_epsilon=frontier_epsilon)
    ]
    removed = len(frontier) - len(retained)
    retained.append(candidate)
    frontier[:] = retained
    return True, removed


def _need_key(need: Counter) -> tuple[tuple[str, int], ...]:
    rows = tuple(
        (position, int(need[position]))
        for position in sorted(need, key=lambda pos: (_POSITION_ORDER.get(pos, 99), pos))
        if int(need[position]) > 0
    )
    total = sum(count for _position, count in rows)
    if total < 1 or total > 3:
        raise RuntimeError(f"exact state frontier supports governed package sizes 1..3, got {total}")
    return rows


class ExactIncomingFrontierIndex:
    """Reusable exact incoming-state index for all outgoing sets in one search."""

    def __init__(
        self,
        pools: dict[str, list[Candidate]],
        risk_by_element: dict[int, dict],
        *,
        frontier_epsilon: float,
    ):
        if frontier_epsilon < 0:
            raise ValueError("frontier_epsilon must be non-negative")
        self.pools = {
            position: tuple(sorted(pools.get(position, []), key=lambda row: row.element))
            for position in _POSITIONS
        }
        self.risk_by_element = risk_by_element
        self.frontier_epsilon = float(frontier_epsilon)
        self._group_cache: dict[tuple[str, int], tuple[IncomingState, ...]] = {}
        self._need_cache: dict[tuple[tuple[str, int], ...], tuple[IncomingState, ...]] = {}
        self.stats = {
            "group_raw_combinations": 0,
            "group_states_retained": 0,
            "group_states_pruned_exact": 0,
            "merge_states_considered": 0,
            "merge_states_retained": 0,
            "merge_states_pruned_exact": 0,
            "legal_state_filter_considered": 0,
            "legal_state_filter_retained": 0,
            "legal_state_rejected_budget": 0,
            "legal_state_rejected_club_limit": 0,
        }

    def _group_frontier(self, position: str, count: int) -> tuple[IncomingState, ...]:
        key = (position, int(count))
        cached = self._group_cache.get(key)
        if cached is not None:
            return cached
        if position not in self.pools or count < 1 or count > 3:
            raise RuntimeError(f"invalid exact state group {key}")
        buckets: dict[int, list[IncomingState]] = {}
        for combo in combinations(self.pools[position], count):
            self.stats["group_raw_combinations"] += 1
            state = _state(tuple(combo), self.risk_by_element)
            bucket = buckets.setdefault(state.club_signature, [])
            inserted, removed = _insert_exact(bucket, state, frontier_epsilon=self.frontier_epsilon)
            if inserted:
                self.stats["group_states_retained"] += 1
            self.stats["group_states_pruned_exact"] += removed + (0 if inserted else 1)
        rows = tuple(
            state
            for signature in sorted(buckets)
            for state in sorted(buckets[signature], key=lambda row: tuple(player.element for player in row.players))
        )
        self._group_cache[key] = rows
        return rows

    def _states_for_need(self, need: Counter) -> tuple[IncomingState, ...]:
        key = _need_key(need)
        cached = self._need_cache.get(key)
        if cached is not None:
            return cached
        states = (_empty_state(),)
        for position, count in key:
            group_states = self._group_frontier(position, count)
            buckets: dict[int, list[IncomingState]] = {}
            for left in states:
                for right in group_states:
                    self.stats["merge_states_considered"] += 1
                    merged = _merge(left, right)
                    bucket = buckets.setdefault(merged.club_signature, [])
                    inserted, removed = _insert_exact(bucket, merged, frontier_epsilon=self.frontier_epsilon)
                    if inserted:
                        self.stats["merge_states_retained"] += 1
                    self.stats["merge_states_pruned_exact"] += removed + (0 if inserted else 1)
            states = tuple(
                state
                for signature in sorted(buckets)
                for state in sorted(buckets[signature], key=lambda row: tuple(player.element for player in row.players))
            )
            if not states:
                break
        self._need_cache[key] = states
        return states

    def iter_legal(
        self,
        need: Counter,
        keep: tuple[Candidate, ...],
        budget: int,
        diagnostics: dict[str, Any],
    ) -> Iterator[tuple[Candidate, ...]]:
        states = self._states_for_need(need)
        keep_cost = sum(player.cost for player in keep)
        keep_signature = _signature(tuple(keep))
        diagnostics.setdefault("exact_state_compression", {})
        local = diagnostics["exact_state_compression"]
        local.setdefault("contract", CONTRACT)
        local.setdefault("canonical_best_and_frontier_exact", True)
        local.setdefault("non_frontier_top_n_diagnostic_completeness", False)
        local.setdefault("same_signature_partial_dominance_only", True)
        local.setdefault("cross_signature_partial_pruning", False)
        local.setdefault("package_id_exact_ties_preserved", True)
        local.setdefault("strictness_survives_canonical_rounding_and_frontier_epsilon", True)
        local.setdefault("best_xi_componentwise_gw_proof", True)
        local.setdefault("club_capacity_equivalence_preserved_before_final_legality", True)
        local.setdefault("need_pattern_cache_reused_across_outgoing_sets", True)
        local["frontier_epsilon"] = self.frontier_epsilon
        local["calls"] = int(local.get("calls") or 0) + 1
        local["cached_need_states"] = len(states)

        for state in states:
            self.stats["legal_state_filter_considered"] += 1
            diagnostics["incoming_combinations_considered"] += 1
            if keep_cost + state.cost > budget:
                self.stats["legal_state_rejected_budget"] += 1
                diagnostics["packages_rejected_by_budget"] += 1
                continue
            if not _legal_with_keep(keep_signature, state.club_signature):
                self.stats["legal_state_rejected_club_limit"] += 1
                diagnostics["packages_rejected_by_club_limit"] += 1
                continue
            self.stats["legal_state_filter_retained"] += 1
            yield state.players

    def proof_summary(self) -> dict[str, Any]:
        raw = int(self.stats["group_raw_combinations"] + self.stats["merge_states_considered"])
        pruned = int(self.stats["group_states_pruned_exact"] + self.stats["merge_states_pruned_exact"])
        return {
            "schema_version": 1,
            "contract": CONTRACT,
            "canonical_best_and_frontier_exact": True,
            "non_frontier_top_n_diagnostic_completeness": False,
            "heuristic": False,
            "beam_cutoff": False,
            "candidate_cutoff": False,
            "same_signature_partial_dominance_only": True,
            "cross_signature_partial_pruning": False,
            "club_capacity_future_equivalence_required": True,
            "componentwise_position_gw_dominance_required": True,
            "cost_and_all_frontier_risk_confidence_dimensions_required": True,
            "strictness_survives_canonical_rounding_and_frontier_epsilon": True,
            "frontier_epsilon": self.frontier_epsilon,
            "exact_ties_preserved_for_package_id_ranking": True,
            "need_pattern_cache_reused_across_outgoing_sets": True,
            "group_cache_entries": len(self._group_cache),
            "need_cache_entries": len(self._need_cache),
            "raw_state_work_observed": raw,
            "exact_states_pruned": pruned,
            "stats": dict(self.stats),
        }
