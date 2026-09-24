from __future__ import annotations

"""Execution-only cross-route exact P1.7 batch kernel.

The scalar V12 lineup optimizer remains the mathematical/reference owner.
This module reuses its exact player surfaces, legal-XI templates, resolver
state tables and objective configuration, but evaluates many squads together.
No route is pruned and no P1.1/P1.3/P1.6 mathematics is recomputed here.
"""

import math
import time
from functools import lru_cache
from typing import Callable, Any, Mapping, Sequence

import numpy as np

from src.engines import v12_lineup_optimizer as scalar

POSITIONS = ("GK", "DEF", "MID", "FWD")
FAMILY_BENCH_SCALAR_FALLBACK_LIMIT = 64
FAMILY_CAPTAIN_SCALAR_PAIR_FALLBACK_LIMIT_PER_ROUTE = 64
POS_CODE = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
CODE_POS = {value: key for key, value in POS_CODE.items()}
PAIR_CAP = np.asarray(
    [captain for captain in range(15) for vice in range(15) if vice != captain],
    dtype=np.int64,
)
PAIR_VICE = np.asarray(
    [vice for captain in range(15) for vice in range(15) if vice != captain],
    dtype=np.int64,
)
BENCH_PERMUTATIONS = np.asarray(
    scalar._BENCH_COLUMN_PERMUTATIONS,
    dtype=np.int64,
)
PAIR_MASKS = np.asarray(
    [
        (1 << int(captain)) | (1 << int(vice))
        for captain, vice in zip(PAIR_CAP, PAIR_VICE)
    ],
    dtype=np.uint16,
)
BENCH_PERMUTATION_RANK = np.full(27, 99, dtype=np.int64)
for _rank, _permutation in enumerate(BENCH_PERMUTATIONS):
    _code = (
        int(_permutation[0]) * 9
        + int(_permutation[1]) * 3
        + int(_permutation[2])
    )
    BENCH_PERMUTATION_RANK[_code] = int(_rank)


class LineupBatchError(ValueError):
    pass


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _ordered_gather_sum(values: np.ndarray, legal: np.ndarray) -> np.ndarray:
    """Exact scalar-order starter accumulation for [B,15] values."""
    batch = np.arange(values.shape[0], dtype=np.int64)[:, None]
    total = np.zeros(legal.shape[:2], dtype=np.float64)
    for slot in range(legal.shape[2]):
        total = total + values[batch, legal[:, :, slot]]
    return total


def _lexicographic_first(
    metrics: Sequence[np.ndarray | Callable[[], np.ndarray]],
    *,
    axis: int,
) -> np.ndarray:
    """Index of lexicographic maximum, preserving first-row tie order.

    Later keys may be supplied lazily and are evaluated only while at least
    one row remains tied on all earlier keys.
    """
    if not metrics:
        raise LineupBatchError("lexicographic selection requires metrics")

    first = metrics[0]() if callable(metrics[0]) else metrics[0]
    shape = first.shape
    # Eager callers historically hand us already-materialized ranking keys.
    # Validate every such key up front so the shared finite contract applies
    # to all callers. Lazy keys remain genuinely lazy and are validated only
    # if ranking reaches them.
    for source in metrics:
        if callable(source):
            continue
        if source.shape != shape:
            raise LineupBatchError("lexicographic metric shape drift")
        if not np.all(np.isfinite(source)):
            raise LineupBatchError("lexicographic metric must be finite")
    if not np.all(np.isfinite(first)):
        raise LineupBatchError("lexicographic metric must be finite")
    candidates = first == np.max(first, axis=axis, keepdims=True)

    for source in metrics[1:]:
        if np.all(np.sum(candidates, axis=axis) == 1):
            break
        metric = source() if callable(source) else source
        if metric.shape != shape:
            raise LineupBatchError("lexicographic metric shape drift")
        if not np.all(np.isfinite(metric)):
            raise LineupBatchError("lexicographic metric must be finite")
        best = np.max(
            np.where(candidates, metric, -np.inf),
            axis=axis,
            keepdims=True,
        )
        candidates &= metric == best
    return np.argmax(candidates, axis=axis)


def _position_dnp_distribution(
    starter_mask: np.ndarray,
    p_dnp: np.ndarray,
    position_codes: np.ndarray,
    position_code: int,
    max_count: int,
) -> np.ndarray:
    """Exact row-wise Poisson-binomial DNP counts over [B, XI, player]."""
    selected = starter_mask & (position_codes[:, None, :] == position_code)
    probs = np.where(selected, p_dnp[:, None, :], np.inf)
    probs.sort(axis=2)
    counts = selected.sum(axis=2).astype(np.int64)
    dist = np.zeros(
        (*starter_mask.shape[:2], int(max_count) + 1),
        dtype=np.float64,
    )
    dist[..., 0] = 1.0
    for step in range(int(max_count)):
        p = np.where(step < counts, probs[..., step], 0.0)
        nxt = dist * (1.0 - p[..., None])
        nxt[..., 1:] += dist[..., :-1] * p[..., None]
        dist = nxt
    return dist


def _position_dnp_distribution_slots(
    starter_mask: np.ndarray,
    p_dnp: np.ndarray,
    slot_indices: np.ndarray,
) -> np.ndarray:
    """Exact Poisson-binomial DNP counts using only slots of one position.

    Player probabilities are ordered once per route. Non-selected positional
    slots contribute p=0, so selected probabilities retain the same ascending
    order used by the scalar per-XI sort without sorting 15 values 550 times.
    """
    batch_count, legal_count, _ = starter_mask.shape
    if slot_indices.shape[0] != batch_count:
        raise LineupBatchError("position slot batch drift")
    position_count = int(slot_indices.shape[1])
    batch = np.arange(batch_count, dtype=np.int64)[:, None]
    position_probs = p_dnp[batch, slot_indices]
    order = np.argsort(position_probs, axis=1, kind="stable")
    ordered_slots = np.take_along_axis(slot_indices, order, axis=1)
    ordered_probs = np.take_along_axis(position_probs, order, axis=1)
    gather_slots = np.broadcast_to(
        ordered_slots[:, None, :],
        (batch_count, legal_count, position_count),
    )
    selected = np.take_along_axis(starter_mask, gather_slots, axis=2)
    probs = np.where(selected, ordered_probs[:, None, :], 0.0)
    dist = np.zeros(
        (batch_count, legal_count, position_count + 1),
        dtype=np.float64,
    )
    dist[..., 0] = 1.0
    for step in range(position_count):
        p = probs[..., step]
        nxt = dist * (1.0 - p[..., None])
        nxt[..., 1:] += dist[..., :-1] * p[..., None]
        dist = nxt
    return dist


def _appearance_mask_probabilities(probabilities: np.ndarray) -> np.ndarray:
    """Vector form of scalar appearance masks with identical mask order."""
    p0 = probabilities[..., 0]
    p1 = probabilities[..., 1]
    p2 = probabilities[..., 2]
    q0 = 1.0 - p0
    q1 = 1.0 - p1
    q2 = 1.0 - p2
    return np.stack(
        (
            q0 * q1 * q2,
            p0 * q1 * q2,
            q0 * p1 * q2,
            p0 * p1 * q2,
            q0 * q1 * p2,
            p0 * q1 * p2,
            q0 * p1 * p2,
            p0 * p1 * p2,
        ),
        axis=-1,
    )


def _legal_templates(position_rows: Sequence[Sequence[str]]) -> np.ndarray:
    templates: list[np.ndarray] = []
    expected_count: int | None = None
    for raw in position_rows:
        signature = tuple(str(value) for value in raw)
        legal = scalar._legal_xi_templates(signature)
        if expected_count is None:
            expected_count = len(legal)
        if len(legal) != expected_count:
            raise LineupBatchError(
                "cross-route batch requires a common legal-XI denominator"
            )
        templates.append(np.asarray(legal, dtype=np.int64))
    if not templates:
        return np.empty((0, 0, 11), dtype=np.int64)
    return np.stack(templates, axis=0)


def _formation_codes(
    starter_mask: np.ndarray,
    position_codes: np.ndarray,
) -> np.ndarray:
    counts = {}
    for position, code in POS_CODE.items():
        counts[position] = np.sum(
            starter_mask & (position_codes[:, None, :] == code),
            axis=2,
            dtype=np.int64,
        )
    if np.any(counts["GK"] != 1):
        raise LineupBatchError("batch legal XI lost starting goalkeeper")
    return counts["DEF"] * 100 + counts["MID"] * 10 + counts["FWD"]


def _bench_indices(
    starter_mask: np.ndarray,
    position_codes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized exact complement indices, preserving scalar player order."""
    batch_count, legal_count, player_count = starter_mask.shape
    if player_count != 15:
        raise LineupBatchError("batch P1.7 requires 15 squad slots")

    bench_all = np.argsort(
        starter_mask,
        axis=2,
        kind="stable",
    )[:, :, :4]
    batch_grid = np.broadcast_to(
        np.arange(batch_count, dtype=np.int64)[:, None, None],
        bench_all.shape,
    )
    bench_positions = position_codes[batch_grid, bench_all]
    reserve_mask = bench_positions == POS_CODE["GK"]
    if np.any(np.sum(reserve_mask, axis=2) != 1):
        raise LineupBatchError("legal XI must leave exactly one reserve GK")
    reserve = np.sum(
        np.where(reserve_mask, bench_all, 0),
        axis=2,
        dtype=np.int64,
    )
    outfield = np.sort(
        np.where(~reserve_mask, bench_all, player_count + 1),
        axis=2,
    )[:, :, :3]
    if np.any(outfield > player_count):
        raise LineupBatchError("legal XI must leave three outfield substitutes")

    slot_indices = np.arange(player_count, dtype=np.int64)[None, None, :]
    position_grid = np.broadcast_to(
        position_codes[:, None, :],
        starter_mask.shape,
    )
    starter_gk_mask = starter_mask & (position_grid == POS_CODE["GK"])
    if np.any(np.sum(starter_gk_mask, axis=2) != 1):
        raise LineupBatchError("legal XI must start exactly one goalkeeper")
    starter_gk = np.sum(
        np.where(starter_gk_mask, slot_indices, 0),
        axis=2,
        dtype=np.int64,
    )
    return reserve, starter_gk, outfield


@lru_cache(maxsize=16)
def _structural_plan_cached(
    position_signatures: tuple[tuple[str, ...], ...],
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
    np.ndarray, np.ndarray, np.ndarray, np.ndarray,
]:
    """Reuse GW-invariant exact XI/bench structure for an unchanged route chunk."""
    position_rows = [list(row) for row in position_signatures]
    position_codes = np.asarray(
        [[POS_CODE[position] for position in row] for row in position_rows],
        dtype=np.int8,
    )
    legal = _legal_templates(position_rows)
    batch_count, legal_count, _ = legal.shape
    starter_mask = np.zeros((batch_count, legal_count, 15), dtype=bool)
    route_axis3 = np.arange(batch_count, dtype=np.int64)[:, None, None]
    legal_axis3 = np.arange(legal_count, dtype=np.int64)[None, :, None]
    starter_mask[route_axis3, legal_axis3, legal] = True
    formation_code = _formation_codes(starter_mask, position_codes)
    reserve_gk, starter_gk, outfield_bench = _bench_indices(
        starter_mask,
        position_codes,
    )
    slot_axis = np.arange(15, dtype=np.int64)[None, :]

    def slots_for(code: int, count: int) -> np.ndarray:
        candidates = np.where(position_codes == code, slot_axis, 16)
        slots = np.sort(candidates, axis=1)[:, :count]
        if np.any(slots >= 15):
            raise LineupBatchError("standard position slot count drift")
        return slots.astype(np.int64, copy=False)

    return (
        legal,
        starter_mask,
        formation_code,
        reserve_gk,
        starter_gk,
        outfield_bench,
        slots_for(POS_CODE["DEF"], 5),
        slots_for(POS_CODE["MID"], 5),
        slots_for(POS_CODE["FWD"], 3),
    )


def _bench_kernel(
    *,
    starter_mask: np.ndarray,
    formation_code: np.ndarray,
    position_codes: np.ndarray,
    elements: np.ndarray,
    p_dnp: np.ndarray,
    p_appearance: np.ndarray,
    xpts_mean: np.ndarray,
    conditioned_mean: np.ndarray,
    conditioned_blank: np.ndarray,
    conditioned_ge8: np.ndarray,
    conditioned_ge10: np.ndarray,
    reserve_gk: np.ndarray,
    starter_gk: np.ndarray,
    outfield_bench: np.ndarray,
    def_slots: np.ndarray,
    mid_slots: np.ndarray,
    fwd_slots: np.ndarray,
) -> dict[str, np.ndarray]:
    batch_count, legal_count, _ = starter_mask.shape
    def_dist = _position_dnp_distribution_slots(starter_mask, p_dnp, def_slots)
    mid_dist = _position_dnp_distribution_slots(starter_mask, p_dnp, mid_slots)
    fwd_dist = _position_dnp_distribution_slots(starter_mask, p_dnp, fwd_slots)

    objective = dict((scalar.load_config().get("objective") or {}))
    blank_weight = _f(
        objective.get("bench_blank_probability_weight_points"),
        0.20,
    )
    upside_weight = _f(
        objective.get("bench_ge8_probability_weight_points"),
        0.20,
    )

    utility = np.empty((batch_count, legal_count, 6), dtype=np.float64)
    expected = np.empty_like(utility)
    autosub = np.empty_like(utility)
    blank = np.empty_like(utility)
    ge8 = np.empty_like(utility)
    ge10 = np.empty_like(utility)

    batch = np.arange(batch_count, dtype=np.int64)[:, None]
    gk_expected = (
        p_dnp[batch, starter_gk]
        * xpts_mean[batch, reserve_gk]
    )
    gk_autosub = (
        p_dnp[batch, starter_gk]
        * p_appearance[batch, reserve_gk]
    )

    flat_count = batch_count * legal_count
    flat_formation = formation_code.reshape(flat_count)
    flat_positions = np.broadcast_to(
        position_codes[:, None, :],
        starter_mask.shape,
    ).reshape(flat_count, 15)
    flat_def = def_dist.reshape(flat_count, def_dist.shape[-1])
    flat_mid = mid_dist.reshape(flat_count, mid_dist.shape[-1])
    flat_fwd = fwd_dist.reshape(flat_count, fwd_dist.shape[-1])
    batch_grid = np.broadcast_to(
        np.arange(batch_count, dtype=np.int64)[:, None],
        (batch_count, legal_count),
    )

    for permutation_index in range(6):
        permutation = BENCH_PERMUTATIONS[permutation_index]
        perm_indices = outfield_bench[:, :, permutation]
        selected_probability = np.zeros(
            (batch_count, legal_count, 3),
            dtype=np.float64,
        )
        outfield_autosub = np.zeros(
            (batch_count, legal_count),
            dtype=np.float64,
        )

        flat_perm_indices = perm_indices.reshape(flat_count, 3)
        bench_position_codes = np.take_along_axis(
            flat_positions,
            flat_perm_indices,
            axis=1,
        )
        structural_key = (
            flat_formation.astype(np.int64) * 64
            + bench_position_codes[:, 0].astype(np.int64) * 16
            + bench_position_codes[:, 1].astype(np.int64) * 4
            + bench_position_codes[:, 2].astype(np.int64)
        )
        for key in np.unique(structural_key):
            rows = np.flatnonzero(structural_key == key)
            if rows.size == 0:
                continue
            fcode = int(flat_formation[rows[0]])
            def_count = fcode // 100
            mid_count = (fcode // 10) % 10
            fwd_count = fcode % 10
            bp_codes = bench_position_codes[rows[0]]
            bench_positions = tuple(
                CODE_POS[int(value)] for value in bp_codes
            )
            state_keys = tuple(
                (d, m, f)
                for d in range(def_count + 1)
                for m in range(mid_count + 1)
                for f in range(fwd_count + 1)
            )
            dnp_probability = np.empty(
                (rows.size, len(state_keys)),
                dtype=np.float64,
            )
            for state_index, (d, m, f) in enumerate(state_keys):
                dnp_probability[:, state_index] = (
                    flat_def[rows, d]
                    * flat_mid[rows, m]
                    * flat_fwd[rows, f]
                )
            dnp_probability = np.where(
                dnp_probability > 1e-15,
                dnp_probability,
                0.0,
            )

            row_batch = batch_grid.reshape(flat_count)[rows]
            row_perm = flat_perm_indices[rows]
            appearance = _appearance_mask_probabilities(
                p_appearance[row_batch[:, None], row_perm]
            )
            selected_matrix, _ = scalar._resolver_state_matrix(
                (def_count, mid_count, fwd_count),
                state_keys,
                bench_positions,
            )
            selected_bits = np.asarray(selected_matrix, dtype=np.uint8)

            # Exact probability contraction without materializing the
            # row × DNP-state × appearance-mask cube.  This is the same
            # finite sum as the scalar resolver, evaluated over all routes in
            # the structural group at once.
            resolver_masks = [
                (selected_bits != 0).astype(np.float64),
                *[
                    (
                        (selected_bits & (1 << slot)) != 0
                    ).astype(np.float64)
                    for slot in range(3)
                ],
            ]
            resolver_projection = np.concatenate(
                [mask.T for mask in resolver_masks],
                axis=1,
            )
            conditional_selection = appearance @ resolver_projection
            conditional_selection = conditional_selection.reshape(
                rows.size,
                4,
                len(state_keys),
            )
            resolved_values = np.sum(
                conditional_selection
                * dnp_probability[:, None, :],
                axis=2,
                dtype=np.float64,
            )
            flat_autosub = resolved_values[:, 0]
            flat_selected = resolved_values[:, 1:4]
            outfield_autosub.reshape(flat_count)[rows] = flat_autosub
            selected_probability.reshape(flat_count, 3)[rows, :] = flat_selected

        slot_mean = conditioned_mean[batch_grid[:, :, None], perm_indices]
        slot_blank = conditioned_blank[batch_grid[:, :, None], perm_indices]
        slot_ge8 = conditioned_ge8[batch_grid[:, :, None], perm_indices]
        slot_ge10 = conditioned_ge10[batch_grid[:, :, None], perm_indices]
        outfield_expected = np.sum(
            selected_probability * slot_mean,
            axis=2,
            dtype=np.float64,
        )
        selected_blank = np.sum(
            selected_probability * slot_blank,
            axis=2,
            dtype=np.float64,
        )
        selected_ge8 = np.sum(
            selected_probability * slot_ge8,
            axis=2,
            dtype=np.float64,
        )
        selected_ge10 = np.sum(
            selected_probability * slot_ge10,
            axis=2,
            dtype=np.float64,
        )
        expected[:, :, permutation_index] = outfield_expected + gk_expected
        autosub[:, :, permutation_index] = 1.0 - (
            (1.0 - outfield_autosub) * (1.0 - gk_autosub)
        )
        blank[:, :, permutation_index] = selected_blank
        ge8[:, :, permutation_index] = selected_ge8
        ge10[:, :, permutation_index] = selected_ge10
        utility[:, :, permutation_index] = (
            expected[:, :, permutation_index]
            - blank_weight * selected_blank
            + upside_weight * selected_ge8
        )

    winner = _lexicographic_first(
        (
            python_round_vec(utility, 6),
            python_round_vec(expected, 6),
            -python_round_vec(blank, 9),
            python_round_vec(ge8, 9),
            python_round_vec(ge10, 9),
        ),
        axis=2,
    )
    route_axis = np.arange(batch_count, dtype=np.int64)[:, None]
    legal_axis = np.arange(legal_count, dtype=np.int64)[None, :]
    winning_order_indices = np.empty(
        (batch_count, legal_count, 3),
        dtype=np.int64,
    )
    for permutation_index in range(6):
        mask = winner == permutation_index
        if not np.any(mask):
            continue
        candidate = outfield_bench[:, :, BENCH_PERMUTATIONS[permutation_index]]
        winning_order_indices[mask] = candidate[mask]

    return {
        "order_indices": winning_order_indices,
        "order_elements": elements[
            route_axis[:, :, None],
            winning_order_indices,
        ],
        "reserve_gk_indices": reserve_gk,
        "expected_autosub_value_raw": expected[
            route_axis,
            legal_axis,
            winner,
        ],
        "expected_autosub_value": python_round_vec(
            expected[route_axis, legal_axis, winner],
            6,
        ),
        "autosub_probability": python_round_vec(
            autosub[route_axis, legal_axis, winner],
            9,
        ),
        "selected_blank": python_round_vec(
            blank[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge8": python_round_vec(
            ge8[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge10": python_round_vec(
            ge10[route_axis, legal_axis, winner],
            9,
        ),
        "bench_order_utility": python_round_vec(
            utility[route_axis, legal_axis, winner],
            6,
        ),
    }


def _captain_kernel(
    *,
    starter_mask: np.ndarray,
    legal: np.ndarray,
    xpts_mean: np.ndarray,
    shortfall: np.ndarray,
    excess: np.ndarray,
    p_dnp: np.ndarray,
) -> dict[str, np.ndarray]:
    """Exact C/VC ranking with route-level pair ranks gathered over 11 starters.

    Pair utility ordering is identical to the scalar oracle.  The execution
    change replaces the previous 210 full starter-mask scans per XI with 11
    vectorized rank-row gathers, one for each legal starter slot.
    """
    objective = dict((scalar.load_config().get("objective") or {}))
    downside_weight = _f(objective.get("captain_downside_weight"), 0.15)
    upside_weight = _f(objective.get("captain_upside_weight"), 0.10)
    base = xpts_mean - downside_weight * shortfall + upside_weight * excess
    cap = PAIR_CAP
    vice = PAIR_VICE
    pair_utility = python_round_vec(base[:, cap] + p_dnp[:, cap] * base[:, vice], 6)
    cap_mean = python_round_vec(xpts_mean[:, cap], 6)
    vice_fallback = python_round_vec(p_dnp[:, cap] * xpts_mean[:, vice], 6)
    joint_upside = python_round_vec(excess[:, cap] + p_dnp[:, cap] * excess[:, vice], 6)
    joint_downside = python_round_vec(shortfall[:, cap] + p_dnp[:, cap] * shortfall[:, vice], 6)
    pair_tie = np.broadcast_to(
        np.arange(PAIR_CAP.size, dtype=np.int64)[None, :], pair_utility.shape
    )
    pair_order = np.lexsort(
        (pair_tie, -vice_fallback, joint_downside, -joint_upside, -cap_mean, -pair_utility),
        axis=1,
    )

    batch_count, legal_count, _ = starter_mask.shape
    rank_by_pair = np.empty_like(pair_order, dtype=np.int16)
    rank_by_pair[
        np.arange(batch_count, dtype=np.int64)[:, None],
        pair_order,
    ] = np.arange(PAIR_CAP.size, dtype=np.int16)[None, :]
    sentinel = np.int16(PAIR_CAP.size + 1)
    rank_matrix = np.full((batch_count, 15, 15), sentinel, dtype=np.int16)
    rank_matrix[:, PAIR_CAP, PAIR_VICE] = rank_by_pair
    pair_lookup = np.full((15, 15), -1, dtype=np.int16)
    pair_lookup[PAIR_CAP, PAIR_VICE] = np.arange(PAIR_CAP.size, dtype=np.int16)

    best_rank = np.full((batch_count, legal_count), sentinel, dtype=np.int16)
    winner = np.full((batch_count, legal_count), -1, dtype=np.int16)
    route_axis = np.arange(batch_count, dtype=np.int64)[:, None]
    for starter_slot in range(legal.shape[2]):
        captain_index = legal[:, :, starter_slot]
        rank_rows = rank_matrix[route_axis, captain_index]
        eligible_rank = np.where(starter_mask, rank_rows, sentinel)
        vice_index = np.argmin(eligible_rank, axis=2).astype(np.int64)
        local_rank = np.take_along_axis(
            eligible_rank, vice_index[:, :, None], axis=2
        )[:, :, 0]
        better = local_rank < best_rank
        if np.any(better):
            local_pair = pair_lookup[captain_index, vice_index]
            best_rank[better] = local_rank[better]
            winner[better] = local_pair[better]
    if np.any(winner < 0):
        raise LineupBatchError("captain batch lost a legal pair")
    winner = winner.astype(np.int64, copy=False)

    def gather(values: np.ndarray) -> np.ndarray:
        return np.take_along_axis(values[:, None, :], winner[:, :, None], axis=2)[:, :, 0]

    return {
        "winner_pair_index": winner,
        "pair_order": pair_order,
        "captain_index": PAIR_CAP[winner],
        "vice_index": PAIR_VICE[winner],
        "pair_utility": gather(pair_utility),
        "expected_captain_multiplier_value": gather(cap_mean),
        "expected_vice_takeover_value": gather(vice_fallback),
        "joint_upside": gather(joint_upside),
        "joint_downside": gather(joint_downside),
    }

def _selected_safe_pool_counts(
    *,
    pair_order: np.ndarray,
    selected_starter_mask: np.ndarray,
    selected_pair_index: np.ndarray,
) -> np.ndarray:
    """Exact scalar compatibility count for the selected XI only."""
    counts = np.empty(selected_starter_mask.shape[0], dtype=np.int64)
    for row_index in range(selected_starter_mask.shape[0]):
        pair_index = int(selected_pair_index[row_index])
        seen = {
            int(PAIR_CAP[pair_index]),
            int(PAIR_VICE[pair_index]),
        }
        legal_rows = 0
        for ranked_pair in pair_order[row_index]:
            ranked_pair = int(ranked_pair)
            captain_index = int(PAIR_CAP[ranked_pair])
            vice_index = int(PAIR_VICE[ranked_pair])
            if not (
                selected_starter_mask[row_index, captain_index]
                and selected_starter_mask[row_index, vice_index]
            ):
                continue
            legal_rows += 1
            seen.add(captain_index)
            if len(seen) >= 5 or legal_rows >= 20:
                break
        counts[row_index] = len(seen)
    return counts


def _selected_cameo_blocking_cost_exact(
    *,
    starter_mask: np.ndarray,
    formation_code: np.ndarray,
    position_codes: np.ndarray,
    p_dnp: np.ndarray,
    p_cameo: np.ndarray,
    p_appearance: np.ndarray,
    xpts_mean: np.ndarray,
    conditioned_mean: np.ndarray,
    bench_order_indices: np.ndarray,
    reserve_gk_indices: np.ndarray,
    actual_expected_autosub: np.ndarray,
) -> np.ndarray:
    """Exact scalar cameo-blocking counterfactual for batch winners only."""
    batch_count = starter_mask.shape[0]
    if batch_count == 0:
        return np.empty(0, dtype=np.float64)

    counterfactual_dnp = np.clip(p_dnp + p_cameo, 0.0, 1.0)
    starter_mask_3d = starter_mask[:, None, :]
    def_dist = _position_dnp_distribution(
        starter_mask_3d,
        counterfactual_dnp,
        position_codes,
        POS_CODE["DEF"],
        5,
    )[:, 0, :]
    mid_dist = _position_dnp_distribution(
        starter_mask_3d,
        counterfactual_dnp,
        position_codes,
        POS_CODE["MID"],
        5,
    )[:, 0, :]
    fwd_dist = _position_dnp_distribution(
        starter_mask_3d,
        counterfactual_dnp,
        position_codes,
        POS_CODE["FWD"],
        3,
    )[:, 0, :]

    selected_probability = np.zeros((batch_count, 3), dtype=np.float64)
    bench_positions = np.take_along_axis(
        position_codes,
        bench_order_indices,
        axis=1,
    )
    structural_key = (
        formation_code.astype(np.int64) * 64
        + bench_positions[:, 0].astype(np.int64) * 16
        + bench_positions[:, 1].astype(np.int64) * 4
        + bench_positions[:, 2].astype(np.int64)
    )
    for key in np.unique(structural_key):
        rows = np.flatnonzero(structural_key == key)
        if rows.size == 0:
            continue
        fcode = int(formation_code[rows[0]])
        def_count = fcode // 100
        mid_count = (fcode // 10) % 10
        fwd_count = fcode % 10
        bench_position_tuple = tuple(
            CODE_POS[int(value)] for value in bench_positions[rows[0]]
        )
        state_keys = tuple(
            (d, m, f)
            for d in range(def_count + 1)
            for m in range(mid_count + 1)
            for f in range(fwd_count + 1)
        )
        dnp_probability = np.empty(
            (rows.size, len(state_keys)),
            dtype=np.float64,
        )
        for state_index, (d, m, f) in enumerate(state_keys):
            dnp_probability[:, state_index] = (
                def_dist[rows, d]
                * mid_dist[rows, m]
                * fwd_dist[rows, f]
            )
        dnp_probability = np.where(
            dnp_probability > 1e-15,
            dnp_probability,
            0.0,
        )
        appearance = _appearance_mask_probabilities(
            p_appearance[rows[:, None], bench_order_indices[rows]]
        )
        selected_matrix, _ = scalar._resolver_state_matrix(
            (def_count, mid_count, fwd_count),
            state_keys,
            bench_position_tuple,
        )
        selected_bits = np.asarray(selected_matrix, dtype=np.uint8)
        resolver_projection = np.concatenate(
            [
                (
                    (selected_bits & (1 << slot)) != 0
                ).astype(np.float64).T
                for slot in range(3)
            ],
            axis=1,
        )
        conditional_selection = appearance @ resolver_projection
        conditional_selection = conditional_selection.reshape(
            rows.size,
            3,
            len(state_keys),
        )
        selected_probability[rows, :] = np.sum(
            conditional_selection * dnp_probability[:, None, :],
            axis=2,
            dtype=np.float64,
        )

    batch = np.arange(batch_count, dtype=np.int64)
    slot_mean = conditioned_mean[
        batch[:, None],
        bench_order_indices,
    ]
    outfield_counterfactual = np.sum(
        selected_probability * slot_mean,
        axis=1,
        dtype=np.float64,
    )
    starter_gk_mask = starter_mask & (
        position_codes == POS_CODE["GK"]
    )
    if np.any(np.sum(starter_gk_mask, axis=1) != 1):
        raise LineupBatchError("selected XI lost starting goalkeeper")
    starter_gk_indices = np.argmax(starter_gk_mask, axis=1)
    gk_counterfactual = (
        counterfactual_dnp[batch, starter_gk_indices]
        * xpts_mean[batch, reserve_gk_indices]
    )
    counterfactual = outfield_counterfactual + gk_counterfactual
    return python_round_vec(
        np.maximum(0.0, counterfactual - actual_expected_autosub),
        6,
    )


def _build_surface_catalog(
    elements: Sequence[int],
    *,
    gw: int,
) -> dict[str, Any]:
    """Materialize immutable P1.7 player surfaces once per GW.

    The scalar optimizer remains the surface owner.  This only converts the
    already-primed scalar cache into dense arrays once, so route families can
    gather by integer index instead of repeating nested Python/dict extraction.
    """
    ordered = tuple(int(element) for element in elements)
    rows = [
        scalar._P17_SURFACE_CACHE[(int(element), int(gw))]
        for element in ordered
    ]
    index = {element: idx for idx, element in enumerate(ordered)}

    def direct(field: str) -> np.ndarray:
        return np.fromiter(
            (_f(row.get(field)) for row in rows),
            dtype=np.float64,
            count=len(rows),
        )

    def appearance(field: str) -> np.ndarray:
        return np.fromiter(
            (
                _f((row.get("appearance_conditioned") or {}).get(field))
                for row in rows
            ),
            dtype=np.float64,
            count=len(rows),
        )

    position_rows = np.asarray(
        [str(row.get("position")) for row in rows],
        dtype=object,
    )
    position_codes = np.fromiter(
        (POS_CODE[str(position)] for position in position_rows),
        dtype=np.int8,
        count=len(rows),
    )
    tactical_weight = np.fromiter(
        (
            _f(
                (row.get("tactical_role") or {}).get(
                    "weighted_component_points"
                )
            )
            for row in rows
        ),
        dtype=np.float64,
        count=len(rows),
    )
    tactical_available = np.fromiter(
        (
            1.0
            if (row.get("tactical_role") or {}).get(
                "weighted_component_points"
            )
            is not None
            else 0.0
            for row in rows
        ),
        dtype=np.float64,
        count=len(rows),
    )
    pmf_ready = np.fromiter(
        (
            1.0
            if (row.get("distribution_status") or {}).get("status")
            == "READY"
            else 0.0
            for row in rows
        ),
        dtype=np.float64,
        count=len(rows),
    )
    return {
        "index": index,
        "elements": np.asarray(ordered, dtype=np.int64),
        "position_rows": position_rows,
        "position_codes": position_codes,
        "xpts_mean": direct("xpts_mean"),
        "variance": direct("xpts_variance"),
        "shortfall": direct("expected_shortfall"),
        "excess": direct("expected_excess_ge_8"),
        "p_dnp": direct("p_dnp"),
        "p_cameo": direct("p_cameo"),
        "p_appearance": direct("p_appearance"),
        "conditioned_mean": appearance("expected_points"),
        "conditioned_blank": appearance("p_fpl_blank"),
        "conditioned_ge8": appearance("p_points_ge_8"),
        "conditioned_ge10": appearance("p_points_ge_10"),
        "tactical_weight": tactical_weight,
        "tactical_available": tactical_available,
        "pmf_ready": pmf_ready,
    }


def _surface_arrays(
    squads: Sequence[tuple[int, ...]],
    *,
    gw: int,
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if catalog is None:
        material_elements = sorted(
            {int(element) for squad in squads for element in squad}
        )
        catalog = _build_surface_catalog(material_elements, gw=gw)

    index = catalog["index"]
    gather = np.asarray(
        [
            [int(index[int(element)]) for element in squad]
            for squad in squads
        ],
        dtype=np.int64,
    )
    elements = np.asarray(squads, dtype=np.int64)
    position_rows_array = np.asarray(
        catalog["position_rows"],
        dtype=object,
    )[gather]
    position_rows = position_rows_array.tolist()

    fields = (
        "position_codes",
        "xpts_mean",
        "variance",
        "shortfall",
        "excess",
        "p_dnp",
        "p_cameo",
        "p_appearance",
        "conditioned_mean",
        "conditioned_blank",
        "conditioned_ge8",
        "conditioned_ge10",
        "tactical_weight",
        "tactical_available",
        "pmf_ready",
    )
    out: dict[str, Any] = {
        "position_rows": position_rows,
        "elements": elements,
    }
    for field in fields:
        out[field] = np.asarray(catalog[field])[gather]
    return out


@lru_cache(maxsize=64)
def _family_layout(
    position_signature: tuple[str, ...],
) -> dict[str, Any]:
    """Static exact 550-XI structure for one core14 + candidate slot layout."""
    if len(position_signature) != 15:
        raise LineupBatchError("route-family layout requires 15 positions")
    position_codes = np.asarray(
        [POS_CODE[str(value)] for value in position_signature],
        dtype=np.int8,
    )
    legal = np.asarray(
        scalar._legal_xi_templates(position_signature),
        dtype=np.int64,
    )
    if legal.shape != (550, 11):
        raise LineupBatchError(
            f"standard route-family layout requires 550 legal XI, got {legal.shape}"
        )
    legal_count = legal.shape[0]
    starter_mask = np.zeros((legal_count, 15), dtype=bool)
    starter_mask[
        np.arange(legal_count, dtype=np.int64)[:, None],
        legal,
    ] = True

    def position_count(code: int) -> np.ndarray:
        return np.sum(
            starter_mask & (position_codes[None, :] == code),
            axis=1,
            dtype=np.int64,
        )

    gk_count = position_count(POS_CODE["GK"])
    def_count = position_count(POS_CODE["DEF"])
    mid_count = position_count(POS_CODE["MID"])
    fwd_count = position_count(POS_CODE["FWD"])
    if np.any(gk_count != 1):
        raise LineupBatchError("family layout lost starting goalkeeper")
    formation_code = def_count * 100 + mid_count * 10 + fwd_count

    bench_all = np.argsort(
        starter_mask,
        axis=1,
        kind="stable",
    )[:, :4]
    bench_positions = position_codes[bench_all]
    reserve_mask = bench_positions == POS_CODE["GK"]
    if np.any(np.sum(reserve_mask, axis=1) != 1):
        raise LineupBatchError("family layout lost reserve goalkeeper")
    reserve_gk = np.sum(
        np.where(reserve_mask, bench_all, 0),
        axis=1,
        dtype=np.int64,
    )
    outfield_bench = np.sort(
        np.where(~reserve_mask, bench_all, 16),
        axis=1,
    )[:, :3]
    if np.any(outfield_bench > 14):
        raise LineupBatchError("family layout lost outfield bench")

    slot_indices = np.arange(15, dtype=np.int64)[None, :]
    starter_gk_mask = starter_mask & (
        position_codes[None, :] == POS_CODE["GK"]
    )
    starter_gk = np.sum(
        np.where(starter_gk_mask, slot_indices, 0),
        axis=1,
        dtype=np.int64,
    )
    outfield_permutations = np.stack(
        [
            outfield_bench[:, permutation]
            for permutation in BENCH_PERMUTATIONS
        ],
        axis=1,
    )

    subset_layouts: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for code, max_count in (
        (POS_CODE["DEF"], 5),
        (POS_CODE["MID"], 5),
        (POS_CODE["FWD"], 3),
    ):
        unique: list[tuple[int, ...]] = []
        unique_index: dict[tuple[int, ...], int] = {}
        inverse = np.empty(legal_count, dtype=np.int64)
        for row_index in range(legal_count):
            subset = tuple(
                int(slot)
                for slot in np.flatnonzero(
                    starter_mask[row_index]
                    & (position_codes == code)
                )
            )
            if subset not in unique_index:
                unique_index[subset] = len(unique)
                unique.append(subset)
            inverse[row_index] = unique_index[subset]
        padded = np.full(
            (len(unique), int(max_count)),
            -1,
            dtype=np.int64,
        )
        for row_index, subset in enumerate(unique):
            padded[row_index, : len(subset)] = subset
        subset_layouts[code] = (padded, inverse)

    structural_groups: list[list[dict[str, Any]]] = []
    for permutation_index in range(6):
        perm_indices = outfield_permutations[:, permutation_index, :]
        perm_position_codes = position_codes[perm_indices]
        structural_key = (
            formation_code.astype(np.int64) * 64
            + perm_position_codes[:, 0].astype(np.int64) * 16
            + perm_position_codes[:, 1].astype(np.int64) * 4
            + perm_position_codes[:, 2].astype(np.int64)
        )
        permutation_groups: list[dict[str, Any]] = []
        for key in np.unique(structural_key):
            rows = np.flatnonzero(structural_key == key)
            fcode = int(formation_code[rows[0]])
            d_count = fcode // 100
            m_count = (fcode // 10) % 10
            f_count = fcode % 10
            bench_position_tuple = tuple(
                CODE_POS[int(value)]
                for value in perm_position_codes[rows[0]]
            )
            state_keys = tuple(
                (d, m, f)
                for d in range(d_count + 1)
                for m in range(m_count + 1)
                for f in range(f_count + 1)
            )
            selected_matrix, _ = scalar._resolver_state_matrix(
                (d_count, m_count, f_count),
                state_keys,
                bench_position_tuple,
            )
            selected_bits = np.asarray(
                selected_matrix,
                dtype=np.uint8,
            )
            resolver_masks = [
                (selected_bits != 0).astype(np.float64),
                *[
                    (
                        (selected_bits & (1 << slot)) != 0
                    ).astype(np.float64)
                    for slot in range(3)
                ],
            ]
            resolver_projection = np.concatenate(
                [mask.T for mask in resolver_masks],
                axis=1,
            )
            permutation_groups.append({
                "rows": rows,
                "state_keys": state_keys,
                "resolver_projection": resolver_projection,
            })
        structural_groups.append(permutation_groups)

    xi_bits = np.asarray(
        [
            sum(1 << int(slot) for slot in row)
            for row in legal
        ],
        dtype=np.uint16,
    )
    return {
        "position_signature": position_signature,
        "position_codes": position_codes,
        "legal": legal,
        "starter_mask": starter_mask,
        "formation_code": formation_code,
        "reserve_gk": reserve_gk,
        "starter_gk": starter_gk,
        "outfield_bench": outfield_bench,
        "outfield_permutations": outfield_permutations,
        "subset_layouts": subset_layouts,
        "structural_groups": structural_groups,
        "candidate_started": starter_mask[:, 14],
        "xi_bits": xi_bits,
    }


def _static_position_dnp_distribution(
    p_dnp: np.ndarray,
    subset_layout: tuple[np.ndarray, np.ndarray],
) -> np.ndarray:
    """Exact DNP-count distributions once per unique positional XI subset."""
    subsets, inverse = subset_layout
    if subsets.size == 0:
        return np.ones((len(inverse), 1), dtype=np.float64)
    safe = np.where(subsets >= 0, subsets, 0)
    probabilities = p_dnp[safe]
    probabilities = np.where(
        subsets >= 0,
        probabilities,
        0.0,
    )
    # Scalar P1.7 canonicalizes positional DNP subsets by sorted
    # probability before the Poisson-binomial recurrence. Preserve that
    # operation order exactly; padded zeros are exact no-op steps.
    probabilities.sort(axis=1)
    max_count = subsets.shape[1]
    dist = np.zeros(
        (subsets.shape[0], max_count + 1),
        dtype=np.float64,
    )
    dist[:, 0] = 1.0
    for step in range(max_count):
        probability = probabilities[:, step]
        nxt = dist * (1.0 - probability[:, None])
        nxt[:, 1:] += dist[:, :-1] * probability[:, None]
        dist = nxt
    return dist[inverse]


def _family_selection_endpoint(
    layout: Mapping[str, Any],
    *,
    p_dnp: np.ndarray,
    p_appearance: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact outfield autosub probabilities for one family endpoint.

    Candidate slot 14 is the only variable.  p=0 and p=1 endpoints therefore
    span the exact multilinear resolver for every route in the family.
    """
    legal_count = int(layout["legal"].shape[0])
    def_dist = _static_position_dnp_distribution(
        p_dnp,
        layout["subset_layouts"][POS_CODE["DEF"]],
    )
    mid_dist = _static_position_dnp_distribution(
        p_dnp,
        layout["subset_layouts"][POS_CODE["MID"]],
    )
    fwd_dist = _static_position_dnp_distribution(
        p_dnp,
        layout["subset_layouts"][POS_CODE["FWD"]],
    )
    selected = np.zeros(
        (legal_count, 6, 3),
        dtype=np.float64,
    )
    autosub = np.zeros(
        (legal_count, 6),
        dtype=np.float64,
    )
    outfield_permutations = layout["outfield_permutations"]

    # DNP state probability depends on the XI row and formation state only,
    # not on the six bench permutations. Build each formation-state matrix
    # once per endpoint, preserving the scalar multiplication order
    # (DEF * MID) * FWD bit-for-bit.
    dnp_probability_by_states: dict[
        tuple[tuple[int, int, int], ...],
        np.ndarray,
    ] = {}
    for permutation_groups in layout["structural_groups"]:
        for group in permutation_groups:
            state_keys = group["state_keys"]
            if state_keys in dnp_probability_by_states:
                continue
            state_array = np.asarray(state_keys, dtype=np.int64)
            dnp_probability = (
                def_dist[:, state_array[:, 0]]
                * mid_dist[:, state_array[:, 1]]
                * fwd_dist[:, state_array[:, 2]]
            )
            dnp_probability_by_states[state_keys] = np.where(
                dnp_probability > 1e-15,
                dnp_probability,
                0.0,
            )

    for permutation_index in range(6):
        perm_indices = outfield_permutations[:, permutation_index, :]
        for group in layout["structural_groups"][permutation_index]:
            rows = group["rows"]
            state_keys = group["state_keys"]
            dnp_probability = dnp_probability_by_states[state_keys][rows]
            appearance = _appearance_mask_probabilities(
                p_appearance[perm_indices[rows]]
            )
            conditional = (
                appearance @ group["resolver_projection"]
            ).reshape(
                rows.size,
                4,
                len(state_keys),
            )
            resolved = np.sum(
                conditional * dnp_probability[:, None, :],
                axis=2,
                dtype=np.float64,
            )
            autosub[rows, permutation_index] = resolved[:, 0]
            selected[rows, permutation_index, :] = resolved[:, 1:4]
    return selected, autosub


def _family_metric_coefficients(
    *,
    selected_zero: np.ndarray,
    selected_delta: np.ndarray,
    outfield_permutations: np.ndarray,
    core_metric: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    metric = np.asarray(core_metric, dtype=np.float64).copy()
    metric[14] = 0.0
    values = metric[outfield_permutations]
    candidate_slot = outfield_permutations == 14
    return (
        np.sum(selected_zero * values, axis=2, dtype=np.float64),
        np.sum(selected_delta * values, axis=2, dtype=np.float64),
        np.sum(selected_zero * candidate_slot, axis=2, dtype=np.float64),
        np.sum(selected_delta * candidate_slot, axis=2, dtype=np.float64),
    )


def _bench_permutation_tie_rank(
    elements: np.ndarray,
    outfield_permutations: np.ndarray,
) -> np.ndarray:
    """Scalar itertools.permutations tie order under actual element ordering."""
    sequence = elements[:, outfield_permutations]
    ranks = np.sum(
        sequence[..., :, None] > sequence[..., None, :],
        axis=-1,
        dtype=np.int64,
    )
    code = (
        ranks[..., 0] * 9
        + ranks[..., 1] * 3
        + ranks[..., 2]
    )
    tie = BENCH_PERMUTATION_RANK[code]
    if np.any(tie > 5):
        raise LineupBatchError("bench permutation tie-rank drift")
    return tie


@lru_cache(maxsize=256)
def _family_bench_permutation_tie_rank_cached(
    elements_bytes: bytes,
    route_count: int,
    position_signature: tuple[str, ...],
) -> np.ndarray:
    """Memoize pure family bench tie ranks across the five GW horizon."""
    elements = np.frombuffer(
        elements_bytes,
        dtype=np.int64,
    ).reshape(int(route_count), 15)
    layout = _family_layout(position_signature)
    tie = _bench_permutation_tie_rank(
        elements,
        layout["outfield_permutations"],
    )
    tie.setflags(write=False)
    return tie


_SPLIT = 134217729.0  # 2**27 + 1 (Dekker/Veltkamp split)


def python_round_vec(x: np.ndarray, decimals: int) -> np.ndarray:
    """Vectorized, bit-identical equivalent of Python's round(float, decimals).

    Valid only for finite float64 values with |x| * 10**decimals < 2**52
    and 0 <= decimals <= 11. Fail closed outside that proven domain.
    """
    x = np.asarray(x, dtype=np.float64)
    if not 0 <= int(decimals) <= 11:
        raise LineupBatchError("python_round_vec decimals outside proven domain")
    if not np.all(np.isfinite(x)):
        raise LineupBatchError("python_round_vec requires finite values")
    scale = float(10 ** int(decimals))
    a = np.abs(x)
    if np.any(a * scale >= float(2**52)):
        raise LineupBatchError("python_round_vec magnitude outside proven domain")

    # Error-free product a*scale = hi + lo.  For decimals <= 11 the scale
    # has <= 26 significant bits, so the Dekker split is exact here.
    hi = a * scale
    c = _SPLIT * a
    ah = c - (c - a)
    al = a - ah
    lo = ((ah * scale - hi) + al * scale)
    k = np.floor(hi)
    frac = hi - k
    diff = frac - 0.5
    up = (diff > 0) | ((diff == 0) & (lo > 0))
    tie = (diff == 0) & (lo == 0)
    up = up | (tie & (np.fmod(k, 2.0) == 1.0))
    q = k + up
    return np.copysign(q / scale, x)


def _near_decimal_half(
    values: np.ndarray,
    decimals: int,
    *,
    ulps: float = 64.0,
) -> np.ndarray:
    """Detect values whose decimal rounding key is ULP-close to a half boundary.

    The fast family kernel is allowed only when the rounded ranking key is
    numerically far from the scalar oracle's decision boundary.  Rows near a
    boundary are recomputed through the scalar bench path because merely
    applying Python round() to the vector result would not repair ULP drift
    introduced by a different accumulation order.
    """
    raw = np.asarray(values, dtype=np.float64)
    scale = float(10 ** int(decimals))
    scaled = raw * scale
    fraction = scaled - np.floor(scaled)
    tolerance = float(ulps) * np.abs(np.spacing(scaled))
    return (
        np.isfinite(scaled)
        & (np.abs(fraction - 0.5) <= tolerance)
    )


def _scalar_surface_from_family_arrays(
    arrays: Mapping[str, np.ndarray],
    route_index: int,
    slot: int,
) -> dict[str, Any]:
    """Reconstruct the scalar bench surface for one already-materialized slot."""
    position_code = int(arrays["position_codes"][route_index, slot])
    p_dnp = float(arrays["p_dnp"][route_index, slot])
    p_appearance = float(arrays["p_appearance"][route_index, slot])
    p_cameo = float(arrays["p_cameo"][route_index, slot])
    return {
        "element": int(arrays["elements"][route_index, slot]),
        "position": CODE_POS[position_code],
        "xpts_mean": float(arrays["xpts_mean"][route_index, slot]),
        "expected_shortfall": float(
            arrays["shortfall"][route_index, slot]
        ),
        "expected_excess_ge_8": float(
            arrays["excess"][route_index, slot]
        ),
        "p_dnp": p_dnp,
        "p_appearance": p_appearance,
        "p_cameo": p_cameo,
        "p_late_cameo": 0.0,
        "appearance_conditioned": {
            "expected_points": float(
                arrays["conditioned_mean"][route_index, slot]
            ),
            "p_fpl_blank": float(
                arrays["conditioned_blank"][route_index, slot]
            ),
            "p_points_ge_8": float(
                arrays["conditioned_ge8"][route_index, slot]
            ),
            "p_points_ge_10": float(
                arrays["conditioned_ge10"][route_index, slot]
            ),
        },
    }


def _family_scalar_bench_boundary_fallback(
    *,
    layout: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    route_index: int,
    xi_index: int,
) -> dict[str, Any]:
    """Recompute one boundary-sensitive bench row through the scalar oracle."""
    players = sorted(
        (
            _scalar_surface_from_family_arrays(
                arrays,
                int(route_index),
                slot,
            )
            for slot in range(15)
        ),
        key=lambda row: int(row["element"]),
    )
    starter_elements = {
        int(arrays["elements"][route_index, int(slot)])
        for slot in layout["legal"][xi_index]
    }
    starters = [
        row
        for row in players
        if int(row["element"]) in starter_elements
    ]
    bench = [
        row
        for row in players
        if int(row["element"]) not in starter_elements
    ]
    reserve_gk = next(
        row for row in bench if row["position"] == "GK"
    )
    outfield_bench = [
        row for row in bench if row["position"] != "GK"
    ]
    scalar_winner, _ = scalar.optimize_bench_order(
        starters,
        reserve_gk,
        outfield_bench,
        include_winner_blocking_counterfactual=False,
        publish_alternatives=False,
        include_winner_slots=False,
    )

    winner_order = [
        next(
            row
            for row in outfield_bench
            if int(row["element"]) == int(element)
        )
        for element in scalar_winner["order"]
    ]
    count_states = scalar._dnp_count_distribution(
        [
            row
            for row in starters
            if row["position"] in scalar.OUTFIELD
        ]
    )
    outfield_actual = scalar._expected_outfield_autosub(
        starters,
        winner_order,
        count_states=count_states,
    )
    starter_gk = next(
        row for row in starters if row["position"] == "GK"
    )
    gk_actual = scalar._expected_gk_autosub(
        starter_gk,
        reserve_gk,
    )
    raw_expected = float(
        outfield_actual["expected_points"]
        + gk_actual["expected_points"]
    )

    slot_by_element = {
        int(arrays["elements"][route_index, slot]): slot
        for slot in range(15)
    }
    order_slots = np.asarray(
        [
            slot_by_element[int(element)]
            for element in scalar_winner["order"]
        ],
        dtype=np.int64,
    )
    permutations = np.asarray(
        layout["outfield_permutations"][xi_index],
        dtype=np.int64,
    )
    matches = np.all(
        permutations == order_slots[None, :],
        axis=1,
    )
    if int(np.sum(matches)) != 1:
        raise LineupBatchError(
            "scalar boundary fallback lost bench permutation identity"
        )
    return {
        "permutation_index": int(np.flatnonzero(matches)[0]),
        "expected_autosub_value_raw": raw_expected,
        "expected_autosub_value": float(
            scalar_winner["expected_autosub_value"]
        ),
        "autosub_probability": float(
            scalar_winner["autosub_probability"]
        ),
        "selected_blank": float(
            scalar_winner[
                "expected_selected_blank_probability_mass"
            ]
        ),
        "selected_ge8": float(
            scalar_winner[
                "expected_selected_ge8_probability_mass"
            ]
        ),
        "selected_ge10": float(
            scalar_winner[
                "expected_selected_ge10_probability_mass"
            ]
        ),
        "bench_order_utility": float(
            scalar_winner["bench_order_utility"]
        ),
    }


def _family_bench_kernel(
    *,
    layout: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    scalar_fallback_limit: int | None = None,
) -> dict[str, Any]:
    """Exact affine core14 bench/autosub kernel for all candidates."""
    route_count = int(arrays["elements"].shape[0])

    # Exact structural fast path: with zero DNP probability for every player
    # in the family/GW, no starter can trigger an autosub. Therefore every
    # bench permutation has identical zero autosub metrics and the canonical
    # scalar winner is determined only by the stable bench tie rank.
    if np.all(np.asarray(arrays["p_dnp"], dtype=np.float64) == 0.0):
        legal_count = int(layout["legal"].shape[0])
        element_matrix = np.ascontiguousarray(
            arrays["elements"],
            dtype=np.int64,
        )
        tie_rank = _family_bench_permutation_tie_rank_cached(
            element_matrix.tobytes(),
            route_count,
            tuple(layout["position_signature"]),
        )
        winner = np.argmin(tie_rank, axis=2)
        route_axis = np.arange(
            route_count,
            dtype=np.int64,
        )[:, None]
        legal_axis = np.arange(
            legal_count,
            dtype=np.int64,
        )[None, :]
        winning_order_indices = layout["outfield_permutations"][
            legal_axis,
            winner,
        ]
        zeros = np.zeros(
            (route_count, legal_count),
            dtype=np.float64,
        )
        reserve_gk = np.asarray(
            layout["reserve_gk"],
            dtype=np.int64,
        )
        return {
            "order_indices": winning_order_indices,
            "order_elements": arrays["elements"][
                route_axis[:, :, None],
                winning_order_indices,
            ],
            "reserve_gk_indices": np.broadcast_to(
                reserve_gk[None, :],
                (route_count, legal_count),
            ),
            "expected_autosub_value_raw": zeros.copy(),
            "expected_autosub_value": zeros.copy(),
            "autosub_probability": zeros.copy(),
            "selected_blank": zeros.copy(),
            "selected_ge8": zeros.copy(),
            "selected_ge10": zeros.copy(),
            "bench_order_utility": zeros.copy(),
            "endpoint_evaluations": 0,
            "bench_rows_evaluated": int(
                route_count * legal_count
            ),
            "bench_primary_tie_count": int(
                route_count * legal_count
            ),
            "bench_primary_boundary_count": 0,
            "bench_secondary_boundary_count": 0,
            "bench_published_boundary_count": 0,
            "bench_scalar_fallback_count": 0,
            "bench_scalar_fallback_limit": (
                None
                if scalar_fallback_limit is None
                else int(scalar_fallback_limit)
            ),
            "zero_dnp_fast_path": True,
        }

    p_dnp_zero = np.asarray(arrays["p_dnp"][0], dtype=np.float64).copy()
    p_dnp_one = p_dnp_zero.copy()
    p_appearance_zero = np.asarray(
        arrays["p_appearance"][0],
        dtype=np.float64,
    ).copy()
    p_appearance_one = p_appearance_zero.copy()
    p_dnp_zero[14] = 0.0
    p_dnp_one[14] = 1.0
    p_appearance_zero[14] = 0.0
    p_appearance_one[14] = 1.0

    selected_zero, autosub_zero = _family_selection_endpoint(
        layout,
        p_dnp=p_dnp_zero,
        p_appearance=p_appearance_zero,
    )
    selected_one, autosub_one = _family_selection_endpoint(
        layout,
        p_dnp=p_dnp_one,
        p_appearance=p_appearance_one,
    )
    selected_delta = selected_one - selected_zero
    autosub_delta = autosub_one - autosub_zero

    candidate_started = np.asarray(
        layout["candidate_started"],
        dtype=bool,
    )
    candidate_p_dnp = arrays["p_dnp"][:, 14]
    candidate_p_appearance = arrays["p_appearance"][:, 14]
    p_variable = np.where(
        candidate_started[None, :],
        candidate_p_dnp[:, None],
        candidate_p_appearance[:, None],
    )

    core_metrics = {
        "expected": np.asarray(
            arrays["conditioned_mean"][0],
            dtype=np.float64,
        ),
        "blank": np.asarray(
            arrays["conditioned_blank"][0],
            dtype=np.float64,
        ),
        "ge8": np.asarray(
            arrays["conditioned_ge8"][0],
            dtype=np.float64,
        ),
        "ge10": np.asarray(
            arrays["conditioned_ge10"][0],
            dtype=np.float64,
        ),
    }
    candidate_metrics = {
        "expected": arrays["conditioned_mean"][:, 14],
        "blank": arrays["conditioned_blank"][:, 14],
        "ge8": arrays["conditioned_ge8"][:, 14],
        "ge10": arrays["conditioned_ge10"][:, 14],
    }

    resolved_metrics: dict[str, np.ndarray] = {}
    for key in ("expected", "blank", "ge8", "ge10"):
        base, slope, candidate_base, candidate_slope = (
            _family_metric_coefficients(
                selected_zero=selected_zero,
                selected_delta=selected_delta,
                outfield_permutations=layout[
                    "outfield_permutations"
                ],
                core_metric=core_metrics[key],
            )
        )
        resolved_metrics[key] = (
            base[None, :, :]
            + slope[None, :, :] * p_variable[:, :, None]
            + candidate_metrics[key][:, None, None]
            * (
                candidate_base[None, :, :]
                + candidate_slope[None, :, :]
                * p_variable[:, :, None]
            )
        )

    starter_gk = layout["starter_gk"]
    reserve_gk = layout["reserve_gk"]
    gk_expected = (
        arrays["p_dnp"][:, starter_gk]
        * arrays["xpts_mean"][:, reserve_gk]
    )
    gk_autosub = (
        arrays["p_dnp"][:, starter_gk]
        * arrays["p_appearance"][:, reserve_gk]
    )
    outfield_autosub = (
        autosub_zero[None, :, :]
        + autosub_delta[None, :, :]
        * p_variable[:, :, None]
    )

    expected = (
        resolved_metrics["expected"]
        + gk_expected[:, :, None]
    )
    autosub = 1.0 - (
        (1.0 - outfield_autosub)
        * (1.0 - gk_autosub[:, :, None])
    )
    blank = resolved_metrics["blank"]
    ge8 = resolved_metrics["ge8"]
    ge10 = resolved_metrics["ge10"]

    objective = dict((scalar.load_config().get("objective") or {}))
    utility = (
        expected
        - _f(
            objective.get("bench_blank_probability_weight_points"),
            0.20,
        )
        * blank
        + _f(
            objective.get("bench_ge8_probability_weight_points"),
            0.20,
        )
        * ge8
    )
    # Keep the tie-rank invariant independent from whether the final
    # lexicographic key is needed.  The guard remains authoritative, but the
    # pure rank matrix is computed once per family input and reused across
    # the five GW horizon instead of being rebuilt five times.
    element_matrix = np.ascontiguousarray(
        arrays["elements"],
        dtype=np.int64,
    )
    tie_rank = _family_bench_permutation_tie_rank_cached(
        element_matrix.tobytes(),
        route_count,
        tuple(layout["position_signature"]),
    )
    # The 15 np.round sites below are intentionally retained only in this
    # family-bench kernel. They operate on the largest [route, XI, permutation]
    # tensors. Exactness is guarded by primary_boundary, secondary_boundary and
    # published_boundary, followed by scalar _family_scalar_bench_boundary_fallback.
    # The guard test requires an inline marker on every allowed site.
    utility_key = np.round(utility, 6)  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    winner = _lexicographic_first(
        (
            utility_key,
            lambda: np.round(expected, 6),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
            lambda: -np.round(blank, 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
            lambda: np.round(ge8, 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
            lambda: np.round(ge10, 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
            lambda: -tie_rank.astype(np.float64),
        ),
        axis=2,
    )

    # A different vector accumulation order can move a raw key by a few ULP
    # across Python's decimal half boundary.  Exact ties by themselves are
    # safe: continue the canonical lexicographic ranking in vector form and
    # fall back only when a ranking key for an actually tied contender is
    # boundary-sensitive.  This keeps common zero-autosub / zero-appearance
    # ties O(vector) instead of exploding into scalar route × XI work.
    max_utility_key = np.max(
        utility_key,
        axis=2,
        keepdims=True,
    )
    tied_candidates = utility_key == max_utility_key
    primary_tie = (
        np.sum(
            tied_candidates,
            axis=2,
            dtype=np.int8,
        )
        > 1
    )
    competitive = utility_key >= (
        max_utility_key - 2e-6
    )
    primary_boundary = np.any(
        _near_decimal_half(utility, 6)
        & competitive,
        axis=2,
    )

    secondary_boundary = np.zeros(
        primary_tie.shape,
        dtype=bool,
    )
    candidate_mask = tied_candidates.copy()
    secondary_specs = (
        (expected, np.round(expected, 6), 6),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
        (blank, -np.round(blank, 9), 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
        (ge8, np.round(ge8, 9), 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
        (ge10, np.round(ge10, 9), 9),  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    )
    for raw_metric, ranking_key, decimals in secondary_specs:
        active_tie = (
            np.sum(
                candidate_mask,
                axis=2,
                dtype=np.int8,
            )
            > 1
        )
        if not np.any(active_tie):
            break
        secondary_boundary |= (
            active_tie
            & np.any(
                _near_decimal_half(raw_metric, decimals)
                & candidate_mask,
                axis=2,
            )
        )
        best_secondary = np.max(
            np.where(
                candidate_mask,
                ranking_key,
                -np.inf,
            ),
            axis=2,
            keepdims=True,
        )
        candidate_mask &= ranking_key == best_secondary

    route_axis_for_boundary = np.arange(
        route_count,
        dtype=np.int64,
    )[:, None]
    legal_axis_for_boundary = np.arange(
        layout["legal"].shape[0],
        dtype=np.int64,
    )[None, :]
    selected_expected_raw = expected[
        route_axis_for_boundary,
        legal_axis_for_boundary,
        winner,
    ]
    selected_blank_raw = blank[
        route_axis_for_boundary,
        legal_axis_for_boundary,
        winner,
    ]
    selected_ge8_raw = ge8[
        route_axis_for_boundary,
        legal_axis_for_boundary,
        winner,
    ]
    selected_ge10_raw = ge10[
        route_axis_for_boundary,
        legal_axis_for_boundary,
        winner,
    ]
    published_boundary = (
        _near_decimal_half(selected_expected_raw, 6)
        | _near_decimal_half(selected_blank_raw, 9)
        | _near_decimal_half(selected_ge8_raw, 9)
        | _near_decimal_half(selected_ge10_raw, 9)
    )
    boundary_sensitive = (
        primary_boundary
        | secondary_boundary
        | published_boundary
    )
    scalar_fallback_count = int(np.sum(boundary_sensitive))
    if (
        scalar_fallback_limit is not None
        and scalar_fallback_count > int(scalar_fallback_limit)
    ):
        raise LineupBatchError(
            "route-family bench scalar fallback budget exceeded: "
            f"{scalar_fallback_count} > {int(scalar_fallback_limit)}"
        )
    scalar_fallbacks: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}
    for route_index, xi_index in np.argwhere(
        boundary_sensitive
    ):
        scalar_row = _family_scalar_bench_boundary_fallback(
            layout=layout,
            arrays=arrays,
            route_index=int(route_index),
            xi_index=int(xi_index),
        )
        winner[int(route_index), int(xi_index)] = int(
            scalar_row["permutation_index"]
        )
        scalar_fallbacks[
            (int(route_index), int(xi_index))
        ] = scalar_row

    route_axis = np.arange(route_count, dtype=np.int64)[:, None]
    legal_axis = np.arange(
        layout["legal"].shape[0],
        dtype=np.int64,
    )[None, :]
    winning_order_indices = layout["outfield_permutations"][
        legal_axis,
        winner,
    ]
    expected_raw_out = expected[
        route_axis,
        legal_axis,
        winner,
    ].copy()
    expected_out = np.round(expected_raw_out, 6)  # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    autosub_out = np.round(
        autosub[route_axis, legal_axis, winner],
        9,
    )
    # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    blank_out = np.round(
        blank[route_axis, legal_axis, winner],
        9,
    )
    # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    ge8_out = np.round(
        ge8[route_axis, legal_axis, winner],
        9,
    )
    # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    ge10_out = np.round(
        ge10[route_axis, legal_axis, winner],
        9,
    )
    # P17_NP_ROUND_PROTECTED_BY_FAMILY_BENCH_FALLBACK
    utility_out = np.round(
        utility[route_axis, legal_axis, winner],
        6,
    )
    for (route_index, xi_index), scalar_row in (
        scalar_fallbacks.items()
    ):
        expected_raw_out[route_index, xi_index] = scalar_row[
            "expected_autosub_value_raw"
        ]
        expected_out[route_index, xi_index] = scalar_row[
            "expected_autosub_value"
        ]
        autosub_out[route_index, xi_index] = scalar_row[
            "autosub_probability"
        ]
        blank_out[route_index, xi_index] = scalar_row[
            "selected_blank"
        ]
        ge8_out[route_index, xi_index] = scalar_row[
            "selected_ge8"
        ]
        ge10_out[route_index, xi_index] = scalar_row[
            "selected_ge10"
        ]
        utility_out[route_index, xi_index] = scalar_row[
            "bench_order_utility"
        ]

    return {
        "order_indices": winning_order_indices,
        "order_elements": arrays["elements"][
            route_axis[:, :, None],
            winning_order_indices,
        ],
        "reserve_gk_indices": np.broadcast_to(
            reserve_gk[None, :],
            (route_count, len(reserve_gk)),
        ),
        "expected_autosub_value_raw": expected_raw_out,
        "expected_autosub_value": expected_out,
        "autosub_probability": autosub_out,
        "selected_blank": blank_out,
        "selected_ge8": ge8_out,
        "selected_ge10": ge10_out,
        "bench_order_utility": utility_out,
        "endpoint_evaluations": 2,
        "bench_rows_evaluated": int(
            route_count * layout["legal"].shape[0]
        ),
        "bench_primary_tie_count": int(np.sum(primary_tie)),
        "bench_primary_boundary_count": int(
            np.sum(primary_boundary)
        ),
        "bench_secondary_boundary_count": int(
            np.sum(secondary_boundary)
        ),
        "bench_published_boundary_count": int(
            np.sum(published_boundary)
        ),
        "bench_scalar_fallback_count": scalar_fallback_count,
        "bench_scalar_fallback_limit": (
            None
            if scalar_fallback_limit is None
            else int(scalar_fallback_limit)
        ),
        "zero_dnp_fast_path": False,
    }


def _actual_slot_ranks(elements: np.ndarray) -> np.ndarray:
    order = np.argsort(elements, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[
        np.arange(elements.shape[0], dtype=np.int64)[:, None],
        order,
    ] = np.arange(15, dtype=np.int64)[None, :]
    return ranks


def _family_captain_kernel(
    *,
    layout: Mapping[str, Any],
    elements: np.ndarray,
    xpts_mean: np.ndarray,
    shortfall: np.ndarray,
    excess: np.ndarray,
    p_dnp: np.ndarray,
) -> dict[str, np.ndarray]:
    """Exact C/VC ranking with core14 reuse and candidate-only challengers.

    Within one route family the 14 retained players are identical.  Therefore
    the best eligible core-core pair for each legal XI is invariant across all
    candidate routes.  Only the 28 ordered pairs that involve candidate slot 14
    can challenge that invariant winner.  Full scalar pair ordering is still
    constructed per route, so tie and route-specific utility semantics remain
    exact while avoiding repeated 15-way scans for all 550 XI.
    """
    objective = dict((scalar.load_config().get("objective") or {}))
    downside_weight = _f(
        objective.get("captain_downside_weight"),
        0.15,
    )
    upside_weight = _f(
        objective.get("captain_upside_weight"),
        0.10,
    )
    # Match the scalar oracle's floating-point operation order exactly.
    # Do not factor p_cap_dnp across the vice utility expression: the scalar
    # path multiplies mean/downside/upside independently before combining.
    raw_captain_utility = (
        xpts_mean[:, PAIR_CAP]
        - downside_weight * shortfall[:, PAIR_CAP]
        + upside_weight * excess[:, PAIR_CAP]
    )
    raw_vice_fallback = (
        p_dnp[:, PAIR_CAP] * xpts_mean[:, PAIR_VICE]
    )
    raw_vice_downside = (
        p_dnp[:, PAIR_CAP] * shortfall[:, PAIR_VICE]
    )
    raw_vice_upside = (
        p_dnp[:, PAIR_CAP] * excess[:, PAIR_VICE]
    )
    raw_vice_utility = (
        raw_vice_fallback
        - downside_weight * raw_vice_downside
        + upside_weight * raw_vice_upside
    )
    raw_pair_utility = (
        raw_captain_utility + raw_vice_utility
    )
    raw_cap_mean = xpts_mean[:, PAIR_CAP]
    raw_joint_upside = (
        excess[:, PAIR_CAP] + raw_vice_upside
    )
    raw_joint_downside = (
        shortfall[:, PAIR_CAP] + raw_vice_downside
    )
    # Exact vector equivalent of scalar Python round(value, 6), including
    # decimal-half cases that are common in production captain pairs.
    pair_utility = python_round_vec(raw_pair_utility, 6)
    cap_mean = python_round_vec(raw_cap_mean, 6)
    vice_fallback = python_round_vec(raw_vice_fallback, 6)
    joint_upside = python_round_vec(raw_joint_upside, 6)
    joint_downside = python_round_vec(raw_joint_downside, 6)

    # Captain mean is a direct player-surface value, not an accumulated pair
    # expression.  At its decimal half boundary Python round() alone is the
    # scalar oracle, so correct it once per route/player instead of forcing
    # all 14 ordered pairs for that captain through scalar pair evaluation.
    direct_cap_mean_boundary = _near_decimal_half(
        xpts_mean,
        6,
    )
    for route_index, cap_slot in np.argwhere(
        direct_cap_mean_boundary
    ):
        route_index = int(route_index)
        cap_slot = int(cap_slot)
        corrected = round(
            float(xpts_mean[route_index, cap_slot]),
            6,
        )
        cap_mean[
            route_index,
            PAIR_CAP == cap_slot,
        ] = corrected

    # With vector arithmetic now in scalar operation order, remaining
    # decimal-half risk is Python scalar rounding versus binary vector arithmetic. Correct
    # those rare pair keys individually with scalar rounding; no full pair
    # recomputation is necessary.
    captain_pair_boundary = (
        _near_decimal_half(raw_pair_utility, 6)
        | _near_decimal_half(raw_vice_fallback, 6)
        | _near_decimal_half(raw_joint_upside, 6)
        | _near_decimal_half(raw_joint_downside, 6)
    )
    captain_pair_round_count_by_route = np.sum(
        captain_pair_boundary,
        axis=1,
        dtype=np.int16,
    )
    # Boundary telemetry remains, but python_round_vec already applies the
    # scalar-oracle rounding rule to every element without a Python loop.

    slot_rank = _actual_slot_ranks(elements)
    cap_rank = slot_rank[:, PAIR_CAP]
    vice_rank = slot_rank[:, PAIR_VICE]
    pair_tie = (
        cap_rank * 14
        + np.where(
            vice_rank < cap_rank,
            vice_rank,
            vice_rank - 1,
        )
    )
    pair_order = np.lexsort(
        (
            pair_tie,
            -vice_fallback,
            joint_downside,
            -joint_upside,
            -cap_mean,
            -pair_utility,
        ),
        axis=1,
    )

    route_count = elements.shape[0]
    legal = np.asarray(layout["legal"], dtype=np.int64)
    legal_count = legal.shape[0]
    starter_mask = np.asarray(layout["starter_mask"], dtype=bool)

    rank_by_pair = np.empty_like(pair_order, dtype=np.int16)
    rank_by_pair[
        np.arange(route_count, dtype=np.int64)[:, None],
        pair_order,
    ] = np.arange(PAIR_CAP.size, dtype=np.int16)[None, :]
    sentinel = np.int16(PAIR_CAP.size + 1)

    core_pair_indices = np.flatnonzero(
        (PAIR_CAP < 14) & (PAIR_VICE < 14)
    ).astype(np.int64, copy=False)
    core_local_order = np.lexsort(
        (
            pair_tie[0, core_pair_indices],
            -vice_fallback[0, core_pair_indices],
            joint_downside[0, core_pair_indices],
            -joint_upside[0, core_pair_indices],
            -cap_mean[0, core_pair_indices],
            -pair_utility[0, core_pair_indices],
        )
    )
    ordered_core_pairs = core_pair_indices[core_local_order]
    core_masks = PAIR_MASKS[ordered_core_pairs]
    xi_bits = np.asarray(layout["xi_bits"], dtype=np.uint16)
    core_eligible = (
        (xi_bits[:, None] & core_masks[None, :])
        == core_masks[None, :]
    )
    if np.any(~np.any(core_eligible, axis=1)):
        raise LineupBatchError("route-family XI lost core-core captain pair")
    core_first = np.argmax(core_eligible, axis=1)
    core_best_pair = ordered_core_pairs[core_first]
    core_best_rank = rank_by_pair[:, core_best_pair]

    candidate_pair_indices = np.flatnonzero(
        (PAIR_CAP == 14) | (PAIR_VICE == 14)
    ).astype(np.int64, copy=False)
    candidate_partner = np.where(
        PAIR_CAP[candidate_pair_indices] == 14,
        PAIR_VICE[candidate_pair_indices],
        PAIR_CAP[candidate_pair_indices],
    ).astype(np.int64, copy=False)
    candidate_pair_rank = rank_by_pair[:, candidate_pair_indices]
    candidate_eligible = starter_mask[:, candidate_partner]
    candidate_rank_tensor = np.where(
        candidate_eligible[None, :, :],
        candidate_pair_rank[:, None, :],
        sentinel,
    )
    candidate_local = np.argmin(
        candidate_rank_tensor,
        axis=2,
    ).astype(np.int64)
    candidate_best_rank = np.take_along_axis(
        candidate_rank_tensor,
        candidate_local[:, :, None],
        axis=2,
    )[:, :, 0]
    candidate_best_pair = candidate_pair_indices[candidate_local]

    winner = np.broadcast_to(
        core_best_pair[None, :],
        (route_count, legal_count),
    ).copy()
    candidate_started = starter_mask[:, 14][None, :]
    use_candidate = (
        candidate_started
        & (candidate_best_rank < core_best_rank)
    )
    winner[use_candidate] = candidate_best_pair[use_candidate]
    if np.any(winner < 0):
        raise LineupBatchError("route-family captain lost legal pair")

    def gather(values: np.ndarray) -> np.ndarray:
        return np.take_along_axis(
            values[:, None, :],
            winner[:, :, None],
            axis=2,
        )[:, :, 0]

    return {
        "winner_pair_index": winner,
        "pair_order": pair_order,
        "captain_index": PAIR_CAP[winner],
        "vice_index": PAIR_VICE[winner],
        "pair_utility": gather(pair_utility),
        "expected_captain_multiplier_value": gather(cap_mean),
        "expected_vice_takeover_value": gather(vice_fallback),
        "joint_upside": gather(joint_upside),
        "joint_downside": gather(joint_downside),
        "scalar_boundary_fallback_count": 0,
        "scalar_pair_fallback_count": 0,
        "max_scalar_pair_fallbacks_per_route": 0,
        "scalar_pair_fallback_limit_per_route": int(
            FAMILY_CAPTAIN_SCALAR_PAIR_FALLBACK_LIMIT_PER_ROUTE
        ),
        "scalar_direct_cap_mean_round_count": int(
            np.sum(direct_cap_mean_boundary)
        ),
        "scalar_pair_round_count": int(
            np.sum(captain_pair_round_count_by_route)
        ),
        "max_scalar_pair_rounds_per_route": int(
            np.max(captain_pair_round_count_by_route)
            if captain_pair_round_count_by_route.size
            else 0
        ),
        "scalar_zero_dnp_captain_count": 0,
    }


@lru_cache(maxsize=256)
def _family_legal_tie_rank_for_candidate_position(
    position_signature: tuple[str, ...],
    candidate_actual_rank: int,
) -> tuple[int, ...]:
    """Map canonical family XI rows to scalar legal enumeration order."""
    rank = int(candidate_actual_rank)
    if rank < 0 or rank > 14:
        raise LineupBatchError("candidate actual rank must be within [0,14]")
    actual_order = list(range(14))
    actual_order.insert(rank, 14)
    actual_signature = tuple(
        position_signature[slot]
        for slot in actual_order
    )
    # A legal XI is a set of slots, so its 15-bit mask identifies it uniquely.
    actual_legal = np.asarray(
        scalar._legal_xi_templates(actual_signature), dtype=np.int64
    )
    canonical_to_actual = np.empty(15, dtype=np.int64)
    for actual_slot, canonical_slot in enumerate(actual_order):
        canonical_to_actual[canonical_slot] = actual_slot
    canonical_legal = np.asarray(
        scalar._legal_xi_templates(position_signature), dtype=np.int64
    )
    actual_masks = np.bitwise_or.reduce(
        np.left_shift(1, actual_legal), axis=1
    )
    canonical_masks = np.bitwise_or.reduce(
        np.left_shift(1, canonical_to_actual[canonical_legal]), axis=1
    )
    order = np.argsort(actual_masks, kind="stable")
    sorted_masks = actual_masks[order]
    position = np.searchsorted(sorted_masks, canonical_masks)
    position = np.minimum(position, sorted_masks.size - 1)
    if not np.array_equal(sorted_masks[position], canonical_masks):
        raise LineupBatchError("family legal XI mapping drift")
    return tuple(int(value) for value in order[position])


def _family_route_tie_rank(
    layout: Mapping[str, Any],
    elements: np.ndarray,
) -> np.ndarray:
    slot_rank = _actual_slot_ranks(elements)
    candidate_rank = slot_rank[:, 14]
    out = np.empty(
        (elements.shape[0], layout["legal"].shape[0]),
        dtype=np.int64,
    )
    for rank in np.unique(candidate_rank):
        rows = np.flatnonzero(candidate_rank == rank)
        mapping = np.asarray(
            _family_legal_tie_rank_for_candidate_position(
                tuple(layout["position_signature"]),
                int(rank),
            ),
            dtype=np.int64,
        )
        out[rows, :] = mapping[None, :]
    return out


def _ordered_gather_sum_static(
    values: np.ndarray,
    legal: np.ndarray,
) -> np.ndarray:
    total = np.zeros(
        (values.shape[0], legal.shape[0]),
        dtype=np.float64,
    )
    for slot in range(legal.shape[1]):
        total = total + values[:, legal[:, slot]]
    return total


def _optimize_gw_family(
    core14: Sequence[int],
    candidate_elements: Sequence[int],
    *,
    gw: int,
    surface_catalog: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exact fixed-outgoing family evaluation with core14 structural reuse."""
    if not candidate_elements:
        return [], {
            "route_count": 0,
            "endpoint_evaluations": 0,
        }
    canonical_squads = [
        tuple(int(value) for value in core14)
        + (int(candidate),)
        for candidate in candidate_elements
    ]
    arrays = _surface_arrays(
        canonical_squads,
        gw=gw,
        catalog=surface_catalog,
    )
    signatures = {
        tuple(str(value) for value in row)
        for row in arrays["position_rows"]
    }
    if len(signatures) != 1:
        raise LineupBatchError(
            "one route family must preserve candidate position"
        )
    layout = _family_layout(next(iter(signatures)))
    legal = layout["legal"]
    bench = _family_bench_kernel(
        layout=layout,
        arrays=arrays,
        scalar_fallback_limit=(
            FAMILY_BENCH_SCALAR_FALLBACK_LIMIT
        ),
    )
    captain = _family_captain_kernel(
        layout=layout,
        elements=arrays["elements"],
        xpts_mean=arrays["xpts_mean"],
        shortfall=arrays["shortfall"],
        excess=arrays["excess"],
        p_dnp=arrays["p_dnp"],
    )

    expected_points = _ordered_gather_sum_static(
        arrays["xpts_mean"],
        legal,
    )
    shortfall = _ordered_gather_sum_static(
        arrays["shortfall"],
        legal,
    )
    excess = _ordered_gather_sum_static(
        arrays["excess"],
        legal,
    )
    tactical_sum = _ordered_gather_sum_static(
        arrays["tactical_weight"],
        legal,
    )
    tactical_count = _ordered_gather_sum_static(
        arrays["tactical_available"],
        legal,
    )
    pmf_ready = _ordered_gather_sum_static(
        arrays["pmf_ready"],
        legal,
    )

    objective = dict((scalar.load_config().get("objective") or {}))
    base_utility = (
        expected_points
        - _f(
            objective.get("lineup_downside_weight"),
            0.10,
        )
        * shortfall
        + _f(
            objective.get("lineup_upside_weight"),
            0.05,
        )
        * excess
    )
    route_utility = python_round_vec(
        base_utility
        + bench["bench_order_utility"]
        + captain["pair_utility"],
        6,
    )
    expected_before_captain = python_round_vec(
        expected_points
        + bench["expected_autosub_value"],
        6,
    )
    expected_with_captain = python_round_vec(
        expected_points
        + bench["expected_autosub_value"]
        + captain["expected_captain_multiplier_value"]
        + captain["expected_vice_takeover_value"],
        6,
    )
    downside = python_round_vec(shortfall, 6)
    upside = python_round_vec(excess, 6)
    tactical_mean = np.where(
        tactical_count > 0.0,
        python_round_vec(
            tactical_sum / np.maximum(tactical_count, 1.0),
            6,
        ),
        0.0,
    )
    route_tie_rank = _family_route_tie_rank(
        layout,
        arrays["elements"],
    )
    winner = _lexicographic_first(
        (
            route_utility,
            expected_with_captain,
            -downside,
            upside,
            tactical_mean,
            -route_tie_rank.astype(np.float64),
        ),
        axis=1,
    )

    route_axis = np.arange(
        arrays["elements"].shape[0],
        dtype=np.int64,
    )
    selected_starter_mask = layout["starter_mask"][winner]
    selected_bench_order = bench["order_indices"][
        route_axis,
        winner,
    ]
    selected_reserve_gk = layout["reserve_gk"][winner]
    selected_pair_index = captain["winner_pair_index"][
        route_axis,
        winner,
    ]
    safe_pool_counts = _selected_safe_pool_counts(
        pair_order=captain["pair_order"],
        selected_starter_mask=selected_starter_mask,
        selected_pair_index=selected_pair_index,
    )
    cameo_blocking_cost = _selected_cameo_blocking_cost_exact(
        starter_mask=selected_starter_mask,
        formation_code=layout["formation_code"][winner],
        position_codes=arrays["position_codes"],
        p_dnp=arrays["p_dnp"],
        p_cameo=arrays["p_cameo"],
        p_appearance=arrays["p_appearance"],
        xpts_mean=arrays["xpts_mean"],
        conditioned_mean=arrays["conditioned_mean"],
        bench_order_indices=selected_bench_order,
        reserve_gk_indices=selected_reserve_gk,
        actual_expected_autosub=bench[
            "expected_autosub_value_raw"
        ][route_axis, winner],
    )

    results: list[dict[str, Any]] = []
    for route_index in range(arrays["elements"].shape[0]):
        xi_index = int(winner[route_index])
        starter_slots = legal[xi_index]
        starter_elements = sorted(
            int(arrays["elements"][route_index, slot])
            for slot in starter_slots
        )
        bench_slots = selected_bench_order[route_index]
        bench_elements = [
            int(arrays["elements"][route_index, slot])
            for slot in bench_slots
        ]
        reserve_index = int(selected_reserve_gk[route_index])
        cap_index = int(
            captain["captain_index"][route_index, xi_index]
        )
        vice_index = int(
            captain["vice_index"][route_index, xi_index]
        )
        fcode = int(layout["formation_code"][xi_index])
        ready_count = int(
            round(float(pmf_ready[route_index, xi_index]))
        )
        results.append({
            "status": "READY",
            "gw": int(gw),
            "route_utility": round(
                float(route_utility[route_index, xi_index]),
                6,
            ),
            "expected_fpl_points": round(
                float(
                    expected_before_captain[
                        route_index,
                        xi_index,
                    ]
                ),
                6,
            ),
            "distributional_downside": round(
                float(downside[route_index, xi_index]),
                6,
            ),
            "supportable_upside": round(
                float(upside[route_index, xi_index]),
                6,
            ),
            "expected_autosub_value": round(
                float(
                    bench["expected_autosub_value"][
                        route_index,
                        xi_index,
                    ]
                ),
                6,
            ),
            "cameo_blocking_cost": round(
                float(cameo_blocking_cost[route_index]),
                6,
            ),
            "cameo_blocking_cost_status": (
                "EXACT_WINNER_ONLY_COUNTERFACTUAL"
            ),
            "formation": (
                f"{fcode // 100}-"
                f"{(fcode // 10) % 10}-"
                f"{fcode % 10}"
            ),
            "starting_xi": starter_elements,
            "bench_gk": int(
                arrays["elements"][
                    route_index,
                    reserve_index,
                ]
            ),
            "bench_order": bench_elements,
            "captain": int(
                arrays["elements"][
                    route_index,
                    cap_index,
                ]
            ),
            "vice_captain": int(
                arrays["elements"][
                    route_index,
                    vice_index,
                ]
            ),
            "captain_safe_pool_count": int(
                safe_pool_counts[route_index]
            ),
            "confidence": (
                "HIGH"
                if ready_count == 11
                else "MEDIUM"
                if ready_count >= 8
                else "LOW"
            ),
            "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
            "p1_7_model_evidence_output_fingerprint": None,
            "materialization_status": (
                "EXACT_CORE14_AFFINE_ROUTE_FAMILY_BATCH"
            ),
            "governance": {
                "p1_7_consumed_read_only": True,
                "p1_1_math_mutated": False,
                "p1_3_math_mutated": False,
                "p1_6_math_mutated": False,
                "p1_7_math_mutated": False,
                "all_550_legal_xi_ranked_exactly": True,
                "six_bench_permutations_exact": True,
                "captain_vice_exact": True,
                "cameo_blocking_exact": True,
                "captain_safe_pool_exact": True,
                "core14_reused": True,
                "candidate_affine_resolver_exact": True,
                "route_pruning": False,
                "approximation": False,
                "detail_materialization_deferred": True,
            },
        })
    return results, {
        "route_count": len(results),
        "endpoint_evaluations": 2,
        "legal_xi_per_route": 550,
        "bench_permutations": 6,
        "core14_reused": True,
        "candidate_affine_resolver_exact": True,
        "bench_rows_evaluated": int(
            bench["bench_rows_evaluated"]
        ),
        "bench_primary_tie_count": int(
            bench["bench_primary_tie_count"]
        ),
        "bench_primary_boundary_count": int(
            bench["bench_primary_boundary_count"]
        ),
        "bench_secondary_boundary_count": int(
            bench["bench_secondary_boundary_count"]
        ),
        "bench_published_boundary_count": int(
            bench["bench_published_boundary_count"]
        ),
        "bench_scalar_fallback_count": int(
            bench["bench_scalar_fallback_count"]
        ),
        "bench_scalar_fallback_limit": int(
            FAMILY_BENCH_SCALAR_FALLBACK_LIMIT
        ),
        "bench_zero_dnp_fast_path": bool(
            bench["zero_dnp_fast_path"]
        ),
        "captain_scalar_boundary_fallback_count": int(
            captain["scalar_boundary_fallback_count"]
        ),
        "captain_scalar_pair_fallback_count": int(
            captain["scalar_pair_fallback_count"]
        ),
        "captain_max_scalar_pair_fallbacks_per_route": int(
            captain["max_scalar_pair_fallbacks_per_route"]
        ),
        "captain_scalar_pair_fallback_limit_per_route": int(
            captain["scalar_pair_fallback_limit_per_route"]
        ),
        "captain_scalar_direct_cap_mean_round_count": int(
            captain["scalar_direct_cap_mean_round_count"]
        ),
        "captain_scalar_zero_dnp_captain_count": int(
            captain["scalar_zero_dnp_captain_count"]
        ),
        "captain_scalar_pair_round_count": int(
            captain["scalar_pair_round_count"]
        ),
        "captain_max_scalar_pair_rounds_per_route": int(
            captain["max_scalar_pair_rounds_per_route"]
        ),
    }


def _one_replacement_family_plan(
    normalized: Sequence[tuple[int, ...]],
    pmap: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Infer direct one-transfer route families from the supplied HOLD squad."""
    if not normalized:
        return {
            "supported": False,
            "reference": None,
            "families": [],
            "fallback_indices": [],
        }
    reference = tuple(normalized[0])
    reference_set = set(reference)
    families: dict[int, list[tuple[int, int]]] = {}
    fallback: list[int] = []
    hold_indices: list[int] = []
    for index, squad in enumerate(normalized):
        if tuple(squad) == reference:
            hold_indices.append(index)
            continue
        squad_set = set(squad)
        outgoing = reference_set - squad_set
        incoming = squad_set - reference_set
        if len(outgoing) != 1 or len(incoming) != 1:
            fallback.append(index)
            continue
        out_element = int(next(iter(outgoing)))
        in_element = int(next(iter(incoming)))
        out_row = pmap.get(out_element)
        in_row = pmap.get(in_element)
        if (
            out_row is None
            or in_row is None
            or str(out_row.get("position"))
            != str(in_row.get("position"))
        ):
            fallback.append(index)
            continue
        families.setdefault(out_element, []).append(
            (index, in_element)
        )
    return {
        "supported": not fallback and bool(hold_indices),
        "reference": reference,
        "hold_indices": hold_indices,
        "families": [
            {
                "outgoing": outgoing,
                "core14": tuple(
                    element
                    for element in reference
                    if element != outgoing
                ),
                "members": members,
            }
            for outgoing, members in families.items()
        ],
        "fallback_indices": fallback,
    }


def _optimize_gw_chunk(
    squads: Sequence[tuple[int, ...]],
    *,
    gw: int,
    surface_catalog: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not squads:
        return []
    arrays = _surface_arrays(
        squads,
        gw=gw,
        catalog=surface_catalog,
    )
    position_signatures = tuple(tuple(row) for row in arrays["position_rows"])
    (
        legal,
        starter_mask,
        formation_code,
        reserve_gk,
        starter_gk,
        outfield_bench,
        def_slots,
        mid_slots,
        fwd_slots,
    ) = _structural_plan_cached(position_signatures)
    if legal.shape[1] != 550:
        raise LineupBatchError(
            f"standard FPL route must preserve 550 legal XI, got {legal.shape[1]}"
        )
    batch_count, legal_count, _ = legal.shape

    bench = _bench_kernel(
        starter_mask=starter_mask,
        formation_code=formation_code,
        position_codes=arrays["position_codes"],
        elements=arrays["elements"],
        p_dnp=arrays["p_dnp"],
        p_appearance=arrays["p_appearance"],
        xpts_mean=arrays["xpts_mean"],
        conditioned_mean=arrays["conditioned_mean"],
        conditioned_blank=arrays["conditioned_blank"],
        conditioned_ge8=arrays["conditioned_ge8"],
        conditioned_ge10=arrays["conditioned_ge10"],
        reserve_gk=reserve_gk,
        starter_gk=starter_gk,
        outfield_bench=outfield_bench,
        def_slots=def_slots,
        mid_slots=mid_slots,
        fwd_slots=fwd_slots,
    )
    captain = _captain_kernel(
        starter_mask=starter_mask,
        legal=legal,
        xpts_mean=arrays["xpts_mean"],
        shortfall=arrays["shortfall"],
        excess=arrays["excess"],
        p_dnp=arrays["p_dnp"],
    )

    expected_points = _ordered_gather_sum(arrays["xpts_mean"], legal)
    shortfall = _ordered_gather_sum(arrays["shortfall"], legal)
    excess = _ordered_gather_sum(arrays["excess"], legal)
    tactical_sum = _ordered_gather_sum(arrays["tactical_weight"], legal)
    tactical_count = _ordered_gather_sum(arrays["tactical_available"], legal)
    pmf_ready = _ordered_gather_sum(arrays["pmf_ready"], legal)

    objective = dict((scalar.load_config().get("objective") or {}))
    base_utility = (
        expected_points
        - _f(objective.get("lineup_downside_weight"), 0.10) * shortfall
        + _f(objective.get("lineup_upside_weight"), 0.05) * excess
    )
    route_utility = python_round_vec(
        base_utility + bench["bench_order_utility"] + captain["pair_utility"],
        6,
    )
    expected_before_captain = python_round_vec(
        expected_points + bench["expected_autosub_value"],
        6,
    )
    expected_with_captain = python_round_vec(
        expected_points
        + bench["expected_autosub_value"]
        + captain["expected_captain_multiplier_value"]
        + captain["expected_vice_takeover_value"],
        6,
    )
    downside = python_round_vec(shortfall, 6)
    upside = python_round_vec(excess, 6)
    tactical_mean = np.where(
        tactical_count > 0.0,
        python_round_vec(tactical_sum / np.maximum(tactical_count, 1.0), 6),
        0.0,
    )
    winner = _lexicographic_first(
        (
            route_utility,
            expected_with_captain,
            -downside,
            upside,
            tactical_mean,
        ),
        axis=1,
    )

    batch_axis = np.arange(batch_count, dtype=np.int64)
    selected_starter_mask = starter_mask[batch_axis, winner]
    selected_bench_order = bench["order_indices"][batch_axis, winner]
    selected_reserve_gk = bench["reserve_gk_indices"][batch_axis, winner]
    selected_pair_index = captain["winner_pair_index"][batch_axis, winner]
    safe_pool_counts = _selected_safe_pool_counts(
        pair_order=captain["pair_order"],
        selected_starter_mask=selected_starter_mask,
        selected_pair_index=selected_pair_index,
    )
    cameo_blocking_cost = _selected_cameo_blocking_cost_exact(
        starter_mask=selected_starter_mask,
        formation_code=formation_code[batch_axis, winner],
        position_codes=arrays["position_codes"],
        p_dnp=arrays["p_dnp"],
        p_cameo=arrays["p_cameo"],
        p_appearance=arrays["p_appearance"],
        xpts_mean=arrays["xpts_mean"],
        conditioned_mean=arrays["conditioned_mean"],
        bench_order_indices=selected_bench_order,
        reserve_gk_indices=selected_reserve_gk,
        actual_expected_autosub=bench["expected_autosub_value_raw"][
            batch_axis,
            winner,
        ],
    )

    results: list[dict[str, Any]] = []
    for batch_index in range(batch_count):
        xi_index = int(winner[batch_index])
        xi_slots = legal[batch_index, xi_index]
        starter_elements = sorted(
            int(arrays["elements"][batch_index, slot]) for slot in xi_slots
        )
        bench_slots = bench["order_indices"][batch_index, xi_index]
        bench_elements = [
            int(arrays["elements"][batch_index, slot]) for slot in bench_slots
        ]
        reserve_index = int(bench["reserve_gk_indices"][batch_index, xi_index])
        cap_index = int(captain["captain_index"][batch_index, xi_index])
        vice_index = int(captain["vice_index"][batch_index, xi_index])
        fcode = int(formation_code[batch_index, xi_index])
        ready_count = int(round(float(pmf_ready[batch_index, xi_index])))
        results.append(
            {
                "status": "READY",
                "gw": int(gw),
                "route_utility": round(float(route_utility[batch_index, xi_index]), 6),
                "expected_fpl_points": round(
                    float(expected_before_captain[batch_index, xi_index]), 6
                ),
                "distributional_downside": round(
                    float(downside[batch_index, xi_index]), 6
                ),
                "supportable_upside": round(
                    float(upside[batch_index, xi_index]), 6
                ),
                "expected_autosub_value": round(
                    float(bench["expected_autosub_value"][batch_index, xi_index]), 6
                ),
                "cameo_blocking_cost": round(
                    float(cameo_blocking_cost[batch_index]), 6
                ),
                "cameo_blocking_cost_status": "EXACT_WINNER_ONLY_COUNTERFACTUAL",
                "formation": f"{fcode // 100}-{(fcode // 10) % 10}-{fcode % 10}",
                "starting_xi": starter_elements,
                "bench_gk": int(arrays["elements"][batch_index, reserve_index]),
                "bench_order": bench_elements,
                "captain": int(arrays["elements"][batch_index, cap_index]),
                "vice_captain": int(arrays["elements"][batch_index, vice_index]),
                "captain_safe_pool_count": int(safe_pool_counts[batch_index]),
                "confidence": (
                    "HIGH" if ready_count == 11 else "MEDIUM" if ready_count >= 8 else "LOW"
                ),
                "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
                "p1_7_model_evidence_output_fingerprint": None,
                "materialization_status": "EXACT_COMPACT_CROSS_ROUTE_BATCH",
                "governance": {
                    "p1_7_consumed_read_only": True,
                    "p1_1_math_mutated": False,
                    "p1_3_math_mutated": False,
                    "p1_6_math_mutated": False,
                    "p1_7_math_mutated": False,
                    "all_550_legal_xi_ranked_exactly": True,
                    "six_bench_permutations_exact": True,
                    "captain_vice_exact": True,
                    "cameo_blocking_exact": True,
                    "captain_safe_pool_exact": True,
                    "detail_materialization_deferred": True,
                },
            }
        )
    return results


def optimize_lineup_horizons_exact_batch(
    projections: Mapping[str, Any],
    squads: Sequence[Sequence[int]],
    *,
    planning_gw: int,
    generated_at: str,
    batch_size: int = 96,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate many exact 15-player squads across the 5-GW P1.2B horizon."""
    started = time.perf_counter()
    normalized = [tuple(int(value) for value in squad) for squad in squads]
    if not normalized:
        return [], {
            "execution_kernel": "CROSS_ROUTE_NUMPY_EXACT_P1_7",
            "squad_count": 0,
            "elapsed_seconds": 0.0,
        }
    for squad in normalized:
        if len(squad) != 15 or len(set(squad)) != 15:
            raise LineupBatchError("batch P1.7 requires exact unique OUR15")

    pmap = {
        int(row.get("element") or -1): row
        for row in projections.get("players") or []
    }
    elements = sorted({element for squad in normalized for element in squad})
    missing = [element for element in elements if element not in pmap]
    if missing:
        raise LineupBatchError(
            f"batch P1.7 missing projection elements: {missing[:20]}"
        )
    gws = tuple(range(int(planning_gw), int(planning_gw) + 5))
    scalar.prime_player_surface_cache(
        projections,
        planning_gws=gws,
        material_elements=elements,
    )
    surface_catalogs = {
        int(gw): _build_surface_catalog(elements, gw=int(gw))
        for gw in gws
    }

    per_squad: list[list[dict[str, Any]]] = [
        [{} for _ in range(5)] for _ in normalized
    ]
    chunks = 0
    gw_elapsed: list[float] = []
    bench_rows_evaluated = 0
    bench_primary_tie_count = 0
    bench_primary_boundary_count = 0
    bench_secondary_boundary_count = 0
    bench_published_boundary_count = 0
    bench_scalar_fallback_count = 0
    bench_zero_dnp_fast_path_family_gw_count = 0
    captain_scalar_boundary_fallback_count = 0
    captain_scalar_pair_fallback_count = 0
    captain_max_scalar_pair_fallbacks_per_route = 0
    captain_scalar_direct_cap_mean_round_count = 0
    captain_scalar_zero_dnp_captain_count = 0
    captain_scalar_pair_round_count = 0
    captain_max_scalar_pair_rounds_per_route = 0
    batch_size = max(1, int(batch_size))
    for offset, gw in enumerate(gws):
        valid_indices: list[int] = []
        for index, squad in enumerate(normalized):
            missing_gw = [
                element
                for element in squad
                if not any(
                    int(row.get("gw") or -1) == int(gw)
                    for row in pmap[element].get("xpts_by_gw") or []
                )
            ]
            if missing_gw:
                per_squad[index][offset] = {
                    "status": "UNAVAILABLE",
                    "reason": "MISSING_HORIZON_PROJECTION",
                    "missing_elements": missing_gw,
                    "gw": int(gw),
                }
            else:
                valid_indices.append(index)

        gw_started = time.perf_counter()
        valid_set = set(valid_indices)
        family_plan = _one_replacement_family_plan(
            normalized,
            pmap,
        )
        family_used = (
            family_plan["supported"]
            and len(normalized) >= 64
        )
        if family_used:
            reference = tuple(family_plan["reference"])
            for source_index in family_plan["hold_indices"]:
                if source_index not in valid_set:
                    continue
                hold_result = _optimize_gw_chunk(
                    [reference],
                    gw=gw,
                    surface_catalog=surface_catalogs[int(gw)],
                )
                per_squad[source_index][offset] = hold_result[0]
                chunks += 1
            for family in family_plan["families"]:
                members = [
                    (source_index, incoming)
                    for source_index, incoming in family["members"]
                    if source_index in valid_set
                ]
                if not members:
                    continue
                family_results, _family_proof = _optimize_gw_family(
                    family["core14"],
                    [incoming for _, incoming in members],
                    gw=gw,
                    surface_catalog=surface_catalogs[int(gw)],
                )
                bench_rows_evaluated += int(
                    _family_proof["bench_rows_evaluated"]
                )
                bench_primary_tie_count += int(
                    _family_proof["bench_primary_tie_count"]
                )
                bench_primary_boundary_count += int(
                    _family_proof[
                        "bench_primary_boundary_count"
                    ]
                )
                bench_secondary_boundary_count += int(
                    _family_proof[
                        "bench_secondary_boundary_count"
                    ]
                )
                bench_published_boundary_count += int(
                    _family_proof[
                        "bench_published_boundary_count"
                    ]
                )
                bench_scalar_fallback_count += int(
                    _family_proof[
                        "bench_scalar_fallback_count"
                    ]
                )
                bench_zero_dnp_fast_path_family_gw_count += int(
                    bool(
                        _family_proof[
                            "bench_zero_dnp_fast_path"
                        ]
                    )
                )
                captain_scalar_boundary_fallback_count += int(
                    _family_proof[
                        "captain_scalar_boundary_fallback_count"
                    ]
                )
                captain_scalar_pair_fallback_count += int(
                    _family_proof[
                        "captain_scalar_pair_fallback_count"
                    ]
                )
                captain_max_scalar_pair_fallbacks_per_route = max(
                    captain_max_scalar_pair_fallbacks_per_route,
                    int(
                        _family_proof[
                            "captain_max_scalar_pair_fallbacks_per_route"
                        ]
                    ),
                )
                captain_scalar_direct_cap_mean_round_count += int(
                    _family_proof[
                        "captain_scalar_direct_cap_mean_round_count"
                    ]
                )
                captain_scalar_zero_dnp_captain_count += int(
                    _family_proof[
                        "captain_scalar_zero_dnp_captain_count"
                    ]
                )
                captain_scalar_pair_round_count += int(
                    _family_proof[
                        "captain_scalar_pair_round_count"
                    ]
                )
                captain_max_scalar_pair_rounds_per_route = max(
                    captain_max_scalar_pair_rounds_per_route,
                    int(
                        _family_proof[
                            "captain_max_scalar_pair_rounds_per_route"
                        ]
                    ),
                )
                if len(family_results) != len(members):
                    raise LineupBatchError(
                        "route-family batch lost squad identity"
                    )
                for (source_index, _), result in zip(
                    members,
                    family_results,
                ):
                    per_squad[source_index][offset] = result
                chunks += 1
        else:
            for start in range(0, len(valid_indices), batch_size):
                chunk_indices = valid_indices[
                    start : start + batch_size
                ]
                chunk_squads = [
                    normalized[index]
                    for index in chunk_indices
                ]
                chunk_results = _optimize_gw_chunk(
                    chunk_squads,
                    gw=gw,
                    surface_catalog=surface_catalogs[int(gw)],
                )
                if len(chunk_results) != len(chunk_indices):
                    raise LineupBatchError(
                        "cross-route batch lost squad identity"
                    )
                for source_index, result in zip(
                    chunk_indices,
                    chunk_results,
                ):
                    per_squad[source_index][offset] = result
                chunks += 1
        gw_elapsed.append(time.perf_counter() - gw_started)

    outputs: list[dict[str, Any]] = []
    for gw_rows in per_squad:
        out: dict[str, Any] = {"per_gw": gw_rows}
        for horizon in (1, 2, 3, 5):
            subset = gw_rows[:horizon]
            if any(row.get("status") != "READY" for row in subset):
                out[str(horizon)] = {
                    "status": "UNAVAILABLE",
                    "reason": "INCOMPLETE_P1_7_HORIZON",
                    "missing_gws": [
                        row.get("gw")
                        for row in subset
                        if row.get("status") != "READY"
                    ],
                }
                continue
            out[str(horizon)] = {
                "status": "READY",
                "gross_route_utility": round(
                    sum(_f(row.get("route_utility")) for row in subset), 6
                ),
                "expected_fpl_points": round(
                    sum(_f(row.get("expected_fpl_points")) for row in subset), 6
                ),
                "distributional_downside": round(
                    sum(_f(row.get("distributional_downside")) for row in subset), 6
                ),
                "supportable_upside": round(
                    sum(_f(row.get("supportable_upside")) for row in subset), 6
                ),
                "expected_autosub_value": round(
                    sum(_f(row.get("expected_autosub_value")) for row in subset), 6
                ),
                "cameo_blocking_cost": round(
                    sum(
                        _f(row.get("cameo_blocking_cost"))
                        for row in subset
                    ),
                    6,
                ),
                "cameo_blocking_cost_status": "EXACT_WINNER_ONLY_COUNTERFACTUAL",
            }
        outputs.append(out)

    elapsed = time.perf_counter() - started
    final_family_plan = _one_replacement_family_plan(
        normalized,
        pmap,
    )
    family_kernel_used = (
        final_family_plan["supported"]
        and len(normalized) >= 64
    )
    proof = {
        "execution_kernel": (
            "ROUTE_FAMILY_CORE14_AFFINE_EXACT_P1_7"
            if family_kernel_used
            else "CROSS_ROUTE_NUMPY_EXACT_P1_7"
        ),
        "route_family_count": (
            len(final_family_plan["families"])
            if family_kernel_used
            else 0
        ),
        "route_family_core_reuse": bool(family_kernel_used),
        "candidate_affine_resolver_exact": bool(family_kernel_used),
        "elapsed_seconds": round(elapsed, 6),
        "squad_count": len(normalized),
        "gw_count": 5,
        "batch_size": batch_size,
        "chunk_count": chunks,
        "material_element_count": len(elements),
        "player_surface_count": len(elements) * 5,
        "legal_xi_per_squad": 550,
        "bench_permutations": 6,
        "captain_vice_pairs_per_squad": int(PAIR_CAP.size),
        "gw_elapsed_seconds": [round(value, 6) for value in gw_elapsed],
        "route_pruning": False,
        "approximation": False,
        "p1_1_math_mutated": False,
        "p1_3_math_mutated": False,
        "p1_6_math_mutated": False,
        "p1_7_math_mutated": False,
        "scalar_oracle_preserved": True,
        "detailed_non_ranking_materialization_deferred": True,
        "bench_rows_evaluated": int(bench_rows_evaluated),
        "bench_primary_tie_count": int(
            bench_primary_tie_count
        ),
        "bench_primary_tie_rate": round(
            (
                bench_primary_tie_count
                / bench_rows_evaluated
            )
            if bench_rows_evaluated
            else 0.0,
            9,
        ),
        "bench_primary_boundary_count": int(
            bench_primary_boundary_count
        ),
        "bench_secondary_boundary_count": int(
            bench_secondary_boundary_count
        ),
        "bench_published_boundary_count": int(
            bench_published_boundary_count
        ),
        "bench_scalar_fallback_count": int(
            bench_scalar_fallback_count
        ),
        "bench_scalar_fallback_rate": round(
            (
                bench_scalar_fallback_count
                / bench_rows_evaluated
            )
            if bench_rows_evaluated
            else 0.0,
            9,
        ),
        "bench_scalar_fallback_limit_per_family_gw": int(
            FAMILY_BENCH_SCALAR_FALLBACK_LIMIT
        ),
        "bench_zero_dnp_fast_path_family_gw_count": int(
            bench_zero_dnp_fast_path_family_gw_count
        ),
        "captain_scalar_boundary_fallback_count": int(
            captain_scalar_boundary_fallback_count
        ),
        "captain_scalar_pair_fallback_count": int(
            captain_scalar_pair_fallback_count
        ),
        "captain_max_scalar_pair_fallbacks_per_route": int(
            captain_max_scalar_pair_fallbacks_per_route
        ),
        "captain_scalar_pair_fallback_limit_per_route": int(
            FAMILY_CAPTAIN_SCALAR_PAIR_FALLBACK_LIMIT_PER_ROUTE
        ),
        "captain_scalar_direct_cap_mean_round_count": int(
            captain_scalar_direct_cap_mean_round_count
        ),
        "captain_scalar_zero_dnp_captain_count": int(
            captain_scalar_zero_dnp_captain_count
        ),
        "captain_scalar_pair_round_count": int(
            captain_scalar_pair_round_count
        ),
        "captain_max_scalar_pair_rounds_per_route": int(
            captain_max_scalar_pair_rounds_per_route
        ),
    }
    return outputs, proof
