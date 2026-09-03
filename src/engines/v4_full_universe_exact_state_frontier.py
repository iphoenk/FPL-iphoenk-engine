from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from math import comb
from typing import Any, Callable, Iterator

from src.engines.v4_optimizer_primitives import gw_value
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS, Candidate


CONTRACT = "V4_FULL_UNIVERSE_EXACT_INDEXED_STREAMING_DP_V5"
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
            tuple(
                sorted(
                    (float(gw_value(player, gw_index)) for player in players if player.position == position),
                    reverse=True,
                )
            )
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
        projection_uncertainty=sum(
            _risk_value(risk_by_element, player, "projection_uncertainty") for player in ordered
        ),
        xmins_uncertainty=sum(_risk_value(risk_by_element, player, "xmins_uncertainty") for player in ordered),
        tactical_uncertainty=sum(
            _risk_value(risk_by_element, player, "tactical_uncertainty") for player in ordered
        ),
        roster_change_uncertainty=sum(
            _risk_value(risk_by_element, player, "roster_change_uncertainty") for player in ordered
        ),
        price_risk=sum(_risk_value(risk_by_element, player, "price_risk") for player in ordered),
        tactical_role_confidence=sum(
            _risk_value(risk_by_element, player, "tactical_role_confidence") for player in ordered
        ),
        opponent_matchup_confidence=sum(
            _risk_value(risk_by_element, player, "opponent_matchup_confidence") for player in ordered
        ),
        gw_values=_gw_shape(ordered),
    )


def _empty_state() -> IncomingState:
    empty_gw = tuple(tuple(tuple() for _ in range(5)) for _ in _POSITIONS)
    return IncomingState(
        players=tuple(),
        club_signature=0,
        cost=0,
        x3=0.0,
        x5=0.0,
        x10=0.0,
        x15=0.0,
        projection_uncertainty=0.0,
        xmins_uncertainty=0.0,
        tactical_uncertainty=0.0,
        roster_change_uncertainty=0.0,
        price_risk=0.0,
        tactical_role_confidence=0.0,
        opponent_matchup_confidence=0.0,
        gw_values=empty_gw,
    )


def _merge_same_position(left: IncomingState, right: IncomingState, position: str) -> IncomingState:
    pos_index = _POSITION_ORDER[position]
    players = tuple(sorted(left.players + right.players, key=lambda row: row.element))
    gw_values = list(left.gw_values)
    gw_values[pos_index] = tuple(
        tuple(
            sorted(
                left.gw_values[pos_index][gw_index] + right.gw_values[pos_index][gw_index],
                reverse=True,
            )
        )
        for gw_index in range(5)
    )
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


def _merge_disjoint_position(left: IncomingState, right: IncomingState, position: str) -> IncomingState:
    pos_index = _POSITION_ORDER[position]
    players = left.players + right.players
    gw_values = list(left.gw_values)
    gw_values[pos_index] = right.gw_values[pos_index]
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
    for left_pos, right_pos in zip(left.gw_values, right.gw_values):
        for left_values, right_values in zip(left_pos, right_pos):
            if len(left_values) != len(right_values):
                return False
            if any(left_value < right_value for left_value, right_value in zip(left_values, right_values)):
                return False
    return True


def _guaranteed_rank_strict(left: IncomingState, right: IncomingState) -> bool:
    return (
        left.x5 > right.x5 + _TWO_DP_ROUND_ERROR
        or left.x15 > right.x15 + _TWO_DP_ROUND_ERROR
        or left.cost < right.cost
    )


def _guaranteed_frontier_strict(
    left: IncomingState,
    right: IncomingState,
    frontier_epsilon: float,
) -> bool:
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


def rank_dominates(
    left: IncomingState,
    right: IncomingState,
    *,
    frontier_epsilon: float = 0.0,
) -> bool:
    del frontier_epsilon
    # Scalar checks are necessary conditions and deliberately run before the
    # expensive position x GW componentwise proof.
    if left.cost > right.cost or left.x5 < right.x5 or left.x15 < right.x15:
        return False
    if (
        left.projection_uncertainty > right.projection_uncertainty
        or left.xmins_uncertainty > right.xmins_uncertainty
        or left.tactical_uncertainty > right.tactical_uncertainty
        or left.roster_change_uncertainty > right.roster_change_uncertainty
    ):
        return False
    if not _guaranteed_rank_strict(left, right):
        return False
    return _gw_no_worse(left, right)


def frontier_dominates(
    left: IncomingState,
    right: IncomingState,
    *,
    frontier_epsilon: float,
) -> bool:
    if frontier_epsilon < 0:
        raise ValueError("frontier_epsilon must be non-negative")
    # Allocation-free scalar proof on the insertion hot path.
    if (
        left.cost > right.cost
        or left.projection_uncertainty > right.projection_uncertainty
        or left.xmins_uncertainty > right.xmins_uncertainty
        or left.tactical_uncertainty > right.tactical_uncertainty
        or left.roster_change_uncertainty > right.roster_change_uncertainty
        or left.price_risk > right.price_risk
    ):
        return False
    if (
        left.x3 < right.x3
        or left.x5 < right.x5
        or left.x10 < right.x10
        or left.x15 < right.x15
        or left.tactical_role_confidence < right.tactical_role_confidence
        or left.opponent_matchup_confidence < right.opponent_matchup_confidence
    ):
        return False
    return _guaranteed_frontier_strict(left, right, frontier_epsilon)


def dominates(
    left: IncomingState,
    right: IncomingState,
    *,
    frontier_epsilon: float,
) -> bool:
    return rank_dominates(left, right) and frontier_dominates(
        left,
        right,
        frontier_epsilon=frontier_epsilon,
    )


def _x5_sort_key(state: IncomingState) -> float:
    return -state.x5


def _supports_x5_index(relation: Callable[..., bool]) -> bool:
    return relation is rank_dominates or relation is frontier_dominates or relation is dominates


def _metric_add(metrics: dict[str, int] | None, key: str, value: int = 1) -> None:
    if metrics is not None:
        metrics[key] = int(metrics.get(key) or 0) + int(value)


def _front_insert(
    layer: list[IncomingState],
    candidate: IncomingState,
    *,
    frontier_epsilon: float,
    relation: Callable[..., bool],
    metrics: dict[str, int] | None = None,
) -> tuple[bool, list[IncomingState]]:
    """Insert into an exact Pareto layer ordered by descending x5.

    All production relations require left.x5 >= right.x5 before dominance is
    possible. The bisect index only skips mathematically impossible pairs; it
    never removes a candidate or imposes a frontier-size bound.
    """
    _metric_add(metrics, "frontier_insert_calls")
    if not layer:
        layer.append(candidate)
        return True, []

    if not _supports_x5_index(relation):
        # Unknown relations fail safe to the old exhaustive pair scan.
        for incumbent in layer:
            _metric_add(metrics, "dominance_full_checks")
            if relation(incumbent, candidate, frontier_epsilon=frontier_epsilon):
                _metric_add(metrics, "frontier_insert_rejected")
                return False, []
        displaced = []
        for incumbent in layer:
            _metric_add(metrics, "dominance_full_checks")
            if relation(candidate, incumbent, frontier_epsilon=frontier_epsilon):
                displaced.append(incumbent)
        if displaced:
            displaced_ids = {id(row) for row in displaced}
            layer[:] = [row for row in layer if id(row) not in displaced_ids]
            _metric_add(metrics, "frontier_states_displaced", len(displaced))
        layer.append(candidate)
        return True, displaced

    candidate_key = -candidate.x5
    layer_size = len(layer)
    dominator_end = bisect_right(layer, candidate_key, key=_x5_sort_key)
    displaced_start = bisect_left(layer, candidate_key, key=_x5_sort_key)
    _metric_add(
        metrics,
        "dominance_pairs_skipped_by_x5_index",
        max(0, 2 * layer_size - dominator_end - (layer_size - displaced_start)),
    )

    for index in range(dominator_end):
        incumbent = layer[index]
        _metric_add(metrics, "dominance_full_checks")
        if relation(incumbent, candidate, frontier_epsilon=frontier_epsilon):
            _metric_add(metrics, "frontier_insert_rejected")
            return False, []

    displaced: list[IncomingState] = []
    for index in range(displaced_start, layer_size):
        incumbent = layer[index]
        _metric_add(metrics, "dominance_full_checks")
        if relation(candidate, incumbent, frontier_epsilon=frontier_epsilon):
            displaced.append(incumbent)

    if displaced:
        displaced_ids = {id(row) for row in displaced}
        layer[displaced_start:] = [
            row for row in layer[displaced_start:] if id(row) not in displaced_ids
        ]
        _metric_add(metrics, "frontier_states_displaced", len(displaced))

    insert_at = bisect_right(layer, candidate_key, key=_x5_sort_key)
    layer.insert(insert_at, candidate)
    return True, displaced


def _skyband_insert(
    layers: list[list[IncomingState]],
    candidate: IncomingState,
    *,
    top_keep: int,
    frontier_epsilon: float,
    relation: Callable[..., bool],
    metrics: dict[str, int] | None = None,
) -> None:
    pending = [candidate]
    for layer_index in range(top_keep):
        layer = layers[layer_index]
        next_pending: list[IncomingState] = []
        for row in pending:
            inserted, displaced = _front_insert(
                layer,
                row,
                frontier_epsilon=frontier_epsilon,
                relation=relation,
                metrics=metrics,
            )
            if inserted:
                next_pending.extend(displaced)
            else:
                next_pending.append(row)
        pending = next_pending
        if not pending:
            break


def _state_key(state: IncomingState) -> tuple[int, ...]:
    return tuple(player.element for player in state.players)


def _flatten_rank(
    buckets: dict[int, list[list[IncomingState]]],
) -> tuple[IncomingState, ...]:
    return tuple(
        row
        for signature in sorted(buckets)
        for layer in buckets[signature]
        for row in sorted(layer, key=_state_key)
    )


def _flatten_frontier(
    buckets: dict[int, list[IncomingState]],
) -> tuple[IncomingState, ...]:
    return tuple(
        row
        for signature in sorted(buckets)
        for row in sorted(buckets[signature], key=_state_key)
    )


def _union_states(*groups: tuple[IncomingState, ...]) -> tuple[IncomingState, ...]:
    unique: dict[tuple[int, ...], IncomingState] = {}
    for rows in groups:
        for row in rows:
            unique[_state_key(row)] = row
    return tuple(unique[key] for key in sorted(unique))


def _need_key(need: Counter) -> tuple[tuple[str, int], ...]:
    rows = tuple(
        (position, int(need[position]))
        for position in sorted(need, key=lambda pos: (_POSITION_ORDER.get(pos, 99), pos))
        if int(need[position]) > 0
    )
    total = sum(count for _position, count in rows)
    if total < 1 or total > 3:
        raise RuntimeError(
            f"exact indexed streaming DP supports governed package sizes 1..3, got {total}"
        )
    return rows


class ExactIncomingFrontierIndex:
    """Exact streaming rank/frontier DP with indexed frontier insertion."""

    def __init__(
        self,
        pools: dict[str, list[Candidate]],
        risk_by_element: dict[int, dict],
        *,
        frontier_epsilon: float,
        top_keep: int,
    ):
        if frontier_epsilon < 0:
            raise ValueError("frontier_epsilon must be non-negative")
        if top_keep < 1:
            raise ValueError("top_keep must be positive")
        self.pools = {
            position: tuple(
                sorted(
                    pools.get(position, []),
                    key=lambda row: (-row.x5, -row.x15, row.cost, row.element),
                )
            )
            for position in _POSITIONS
        }
        self.risk_by_element = risk_by_element
        self.frontier_epsilon = float(frontier_epsilon)
        self.top_keep = int(top_keep)
        self._single_state = {
            player.element: _state((player,), risk_by_element)
            for position in _POSITIONS
            for player in self.pools[position]
        }
        self._group_cache: dict[
            tuple[str, int],
            tuple[tuple[IncomingState, ...], tuple[IncomingState, ...]],
        ] = {}
        self._need_cache: dict[
            tuple[tuple[str, int], ...],
            tuple[tuple[IncomingState, ...], tuple[IncomingState, ...]],
        ] = {}
        self.stats: dict[str, int] = {
            "group_raw_combinations_theoretical": 0,
            "group_rank_transitions_considered": 0,
            "group_frontier_transitions_considered": 0,
            "group_rank_states_retained": 0,
            "group_frontier_states_retained": 0,
            "rank_merge_states_considered": 0,
            "frontier_merge_states_considered": 0,
            "rank_merge_states_retained": 0,
            "frontier_merge_states_retained": 0,
            "need_raw_combinations_theoretical": 0,
            "need_union_states_retained": 0,
            "full_union_states_retained": 0,
            "legal_state_filter_considered": 0,
            "legal_state_filter_retained": 0,
            "legal_state_rejected_budget": 0,
            "legal_state_rejected_club_limit": 0,
            "frontier_insert_calls": 0,
            "frontier_insert_rejected": 0,
            "frontier_states_displaced": 0,
            "dominance_full_checks": 0,
            "dominance_pairs_skipped_by_x5_index": 0,
        }

    def _new_rank_layers(self) -> list[list[IncomingState]]:
        return [[] for _ in range(self.top_keep)]

    def _rank_sources(
        self,
        buckets: dict[int, list[list[IncomingState]]],
    ) -> tuple[IncomingState, ...]:
        return _flatten_rank(buckets)

    def _frontier_sources(
        self,
        buckets: dict[int, list[IncomingState]],
    ) -> tuple[IncomingState, ...]:
        return _flatten_frontier(buckets)

    def _group_survivors(
        self,
        position: str,
        count: int,
    ) -> tuple[tuple[IncomingState, ...], tuple[IncomingState, ...]]:
        key = (position, int(count))
        cached = self._group_cache.get(key)
        if cached is not None:
            return cached
        pool = self.pools.get(position, tuple())
        if position not in self.pools or count < 1 or count > 3:
            raise RuntimeError(f"invalid exact state group {key}")
        if len(pool) < count:
            cached = (tuple(), tuple())
            self._group_cache[key] = cached
            return cached

        self.stats["group_raw_combinations_theoretical"] += comb(len(pool), count)
        rank_dp: list[dict[int, list[list[IncomingState]]]] = [
            dict() for _ in range(count + 1)
        ]
        frontier_dp: list[dict[int, list[IncomingState]]] = [
            dict() for _ in range(count + 1)
        ]
        rank_dp[0][0] = self._new_rank_layers()
        _skyband_insert(
            rank_dp[0][0],
            _empty_state(),
            top_keep=self.top_keep,
            frontier_epsilon=self.frontier_epsilon,
            relation=rank_dominates,
            metrics=self.stats,
        )
        frontier_dp[0][0] = [_empty_state()]

        for processed, player in enumerate(pool):
            singleton = self._single_state[player.element]
            max_pick = min(count, processed + 1)
            for pick in range(max_pick, 0, -1):
                rank_sources = self._rank_sources(rank_dp[pick - 1])
                for prefix in rank_sources:
                    self.stats["group_rank_transitions_considered"] += 1
                    merged = (
                        singleton
                        if pick == 1 and not prefix.players
                        else _merge_same_position(prefix, singleton, position)
                    )
                    _skyband_insert(
                        rank_dp[pick].setdefault(
                            merged.club_signature,
                            self._new_rank_layers(),
                        ),
                        merged,
                        top_keep=self.top_keep,
                        frontier_epsilon=self.frontier_epsilon,
                        relation=rank_dominates,
                        metrics=self.stats,
                    )

                frontier_sources = self._frontier_sources(frontier_dp[pick - 1])
                for prefix in frontier_sources:
                    self.stats["group_frontier_transitions_considered"] += 1
                    merged = (
                        singleton
                        if pick == 1 and not prefix.players
                        else _merge_same_position(prefix, singleton, position)
                    )
                    _front_insert(
                        frontier_dp[pick].setdefault(merged.club_signature, []),
                        merged,
                        frontier_epsilon=self.frontier_epsilon,
                        relation=frontier_dominates,
                        metrics=self.stats,
                    )

        rank_rows = _flatten_rank(rank_dp[count])
        frontier_rows = _flatten_frontier(frontier_dp[count])
        self.stats["group_rank_states_retained"] += len(rank_rows)
        self.stats["group_frontier_states_retained"] += len(frontier_rows)
        cached = (rank_rows, frontier_rows)
        self._group_cache[key] = cached
        return cached

    def _states_for_need(
        self,
        need: Counter,
    ) -> tuple[tuple[IncomingState, ...], tuple[IncomingState, ...]]:
        key = _need_key(need)
        cached = self._need_cache.get(key)
        if cached is not None:
            return cached

        raw_need = 1
        for position, count in key:
            raw_need *= comb(len(self.pools.get(position, tuple())), count)
        self.stats["need_raw_combinations_theoretical"] += raw_need

        rank_states = (_empty_state(),)
        frontier_states = (_empty_state(),)
        for position, count in key:
            group_rank, group_frontier = self._group_survivors(position, count)

            rank_buckets: dict[int, list[list[IncomingState]]] = {}
            for left in rank_states:
                for right in group_rank:
                    self.stats["rank_merge_states_considered"] += 1
                    merged = (
                        right
                        if not left.players
                        else _merge_disjoint_position(left, right, position)
                    )
                    _skyband_insert(
                        rank_buckets.setdefault(
                            merged.club_signature,
                            self._new_rank_layers(),
                        ),
                        merged,
                        top_keep=self.top_keep,
                        frontier_epsilon=self.frontier_epsilon,
                        relation=rank_dominates,
                        metrics=self.stats,
                    )
            rank_states = _flatten_rank(rank_buckets)
            self.stats["rank_merge_states_retained"] += len(rank_states)

            frontier_buckets: dict[int, list[IncomingState]] = {}
            for left in frontier_states:
                for right in group_frontier:
                    self.stats["frontier_merge_states_considered"] += 1
                    merged = (
                        right
                        if not left.players
                        else _merge_disjoint_position(left, right, position)
                    )
                    _front_insert(
                        frontier_buckets.setdefault(merged.club_signature, []),
                        merged,
                        frontier_epsilon=self.frontier_epsilon,
                        relation=frontier_dominates,
                        metrics=self.stats,
                    )
            frontier_states = _flatten_frontier(frontier_buckets)
            self.stats["frontier_merge_states_retained"] += len(frontier_states)

            if not rank_states and not frontier_states:
                break

        union_count = len(_union_states(rank_states, frontier_states))
        self.stats["need_union_states_retained"] += union_count
        cached = (rank_states, frontier_states)
        self._need_cache[key] = cached
        return cached

    def iter_legal(
        self,
        need: Counter,
        keep: tuple[Candidate, ...],
        budget: int,
        diagnostics: dict[str, Any],
    ) -> Iterator[tuple[Candidate, ...]]:
        rank_states, frontier_states = self._states_for_need(need)
        states = _union_states(rank_states, frontier_states)
        self.stats["full_union_states_retained"] += len(states)
        keep_cost = sum(player.cost for player in keep)
        keep_signature = _signature(tuple(keep))

        diagnostics.setdefault("exact_state_compression", {})
        local = diagnostics["exact_state_compression"]
        local.setdefault("contract", CONTRACT)
        local.setdefault("canonical_top_n_best_and_frontier_exact", True)
        local.setdefault("pareto_skyband_depth", self.top_keep)
        local.setdefault("rank_pareto_skyband_depth", self.top_keep)
        local.setdefault("frontier_pareto_depth", 1)
        local.setdefault("same_position_raw_combination_materialization", False)
        local.setdefault("streaming_prefix_dp", True)
        local.setdefault("x5_indexed_frontier_insertion", True)
        local.setdefault("x5_index_is_necessary_condition_only", True)
        local.setdefault("scalar_rank_prefilter_before_gw_shape", True)
        local.setdefault("future_suffix_excludes_processed_players", True)
        local.setdefault(
            "rank_and_frontier_dp_independent_until_full_package",
            True,
        )
        local.setdefault("survivor_union_only_after_full_need_pattern", True)
        local.setdefault("same_signature_partial_dominance_only", True)
        local.setdefault("cross_signature_partial_pruning", False)
        local.setdefault("package_id_exact_ties_preserved", True)
        local.setdefault(
            "strictness_survives_canonical_rounding_and_frontier_epsilon",
            True,
        )
        local.setdefault("rank_best_xi_componentwise_gw_proof", True)
        local.setdefault("frontier_does_not_require_best_xi_gw_shape", True)
        local.setdefault(
            "club_capacity_equivalence_preserved_before_final_legality",
            True,
        )
        local.setdefault("need_pattern_cache_reused_across_outgoing_sets", True)
        local["frontier_epsilon"] = self.frontier_epsilon
        local["calls"] = int(local.get("calls") or 0) + 1
        local["cached_rank_states"] = len(rank_states)
        local["cached_frontier_states"] = len(frontier_states)
        local["cached_union_states"] = len(states)

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
        transition_work = int(
            self.stats["group_rank_transitions_considered"]
            + self.stats["group_frontier_transitions_considered"]
            + self.stats["rank_merge_states_considered"]
            + self.stats["frontier_merge_states_considered"]
        )
        theoretical_need = int(self.stats["need_raw_combinations_theoretical"])
        union_need = int(self.stats["need_union_states_retained"])
        return {
            "schema_version": 5,
            "contract": CONTRACT,
            "canonical_top_n_best_and_frontier_exact": True,
            "pareto_skyband_depth": self.top_keep,
            "rank_pareto_skyband_depth": self.top_keep,
            "frontier_pareto_depth": 1,
            "same_position_raw_combination_materialization": False,
            "streaming_prefix_dp": True,
            "x5_indexed_frontier_insertion": True,
            "x5_index_is_necessary_condition_only": True,
            "scalar_rank_prefilter_before_gw_shape": True,
            "heuristic": False,
            "beam_cutoff": False,
            "candidate_cutoff": False,
            "future_suffix_excludes_processed_players": True,
            "rank_and_frontier_dp_independent_until_full_package": True,
            "survivor_union_only_after_full_need_pattern": True,
            "same_signature_partial_dominance_only": True,
            "cross_signature_partial_pruning": False,
            "club_capacity_future_equivalence_required": True,
            "rank_componentwise_position_gw_dominance_required": True,
            "frontier_best_xi_gw_shape_not_required": True,
            "rank_uses_only_canonical_rank_dimensions": True,
            "frontier_uses_only_canonical_frontier_dimensions": True,
            "strictness_survives_canonical_rounding_and_frontier_epsilon": True,
            "frontier_epsilon": self.frontier_epsilon,
            "exact_ties_preserved_for_package_id_ranking": True,
            "need_pattern_cache_reused_across_outgoing_sets": True,
            "group_cache_entries": len(self._group_cache),
            "need_cache_entries": len(self._need_cache),
            "raw_state_work_observed": transition_work,
            "raw_same_position_combinations_avoided": int(
                self.stats["group_raw_combinations_theoretical"]
            ),
            "exact_states_pruned": max(0, theoretical_need - union_need),
            "dominance_pairs_skipped_by_x5_index": int(
                self.stats["dominance_pairs_skipped_by_x5_index"]
            ),
            "stats": dict(self.stats),
        }
