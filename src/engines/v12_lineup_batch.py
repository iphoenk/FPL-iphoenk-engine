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
from typing import Any, Mapping, Sequence

import numpy as np

from src.engines import v12_lineup_optimizer as scalar

POSITIONS = ("GK", "DEF", "MID", "FWD")
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
    metrics: Sequence[np.ndarray],
    *,
    axis: int,
) -> np.ndarray:
    """Index of lexicographic maximum, preserving first-row tie order."""
    if not metrics:
        raise LineupBatchError("lexicographic selection requires metrics")
    shape = metrics[0].shape
    candidates = np.ones(shape, dtype=bool)
    for metric in metrics:
        if metric.shape != shape:
            raise LineupBatchError("lexicographic metric shape drift")
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
            np.round(utility, 6),
            np.round(expected, 6),
            -np.round(blank, 9),
            np.round(ge8, 9),
            np.round(ge10, 9),
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
        "expected_autosub_value": np.round(
            expected[route_axis, legal_axis, winner],
            6,
        ),
        "autosub_probability": np.round(
            autosub[route_axis, legal_axis, winner],
            9,
        ),
        "selected_blank": np.round(
            blank[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge8": np.round(
            ge8[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge10": np.round(
            ge10[route_axis, legal_axis, winner],
            9,
        ),
        "bench_order_utility": np.round(
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
    pair_utility = np.round(base[:, cap] + p_dnp[:, cap] * base[:, vice], 6)
    cap_mean = np.round(xpts_mean[:, cap], 6)
    vice_fallback = np.round(p_dnp[:, cap] * xpts_mean[:, vice], 6)
    joint_upside = np.round(excess[:, cap] + p_dnp[:, cap] * excess[:, vice], 6)
    joint_downside = np.round(shortfall[:, cap] + p_dnp[:, cap] * shortfall[:, vice], 6)
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
    return np.round(
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

    DNP state probabilities depend on legal-XI row and formation state only,
    not on bench permutation.  Build them once per formation and reuse them
    across all six bench permutations while preserving scalar multiplication
    order exactly as (DEF * MID) * FWD.
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
    formation_code = np.asarray(layout["formation_code"], dtype=np.int64)

    dnp_probability_by_formation: dict[
        int,
        tuple[tuple[tuple[int, int, int], ...], np.ndarray],
    ] = {}
    for raw_code in np.unique(formation_code):
        code = int(raw_code)
        rows = np.flatnonzero(formation_code == code)
        d_count = code // 100
        m_count = (code // 10) % 10
        f_count = code % 10
        state_keys = tuple(
            (d, m, f)
            for d in range(d_count + 1)
            for m in range(m_count + 1)
            for f in range(f_count + 1)
        )
        state_index = np.asarray(state_keys, dtype=np.int64)
        dnp_probability = (
            def_dist[rows[:, None], state_index[None, :, 0]]
            * mid_dist[rows[:, None], state_index[None, :, 1]]
        ) * fwd_dist[rows[:, None], state_index[None, :, 2]]
        dnp_probability = np.where(
            dnp_probability > 1e-15,
            dnp_probability,
            0.0,
        )
        full = np.empty(
            (legal_count, len(state_keys)),
            dtype=np.float64,
        )
        full[rows, :] = dnp_probability
        dnp_probability_by_formation[code] = (state_keys, full)

    for permutation_index in range(6):
        perm_indices = outfield_permutations[:, permutation_index, :]
        for group in layout["structural_groups"][permutation_index]:
            rows = group["rows"]
            code = int(formation_code[int(rows[0])])
            state_keys, cached_probability = (
                dnp_probability_by_formation[code]
            )
            if tuple(group["state_keys"]) != state_keys:
                raise LineupBatchError(
                    "route-family DNP state-key drift"
                )
            dnp_probability = cached_probability[rows]
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


def _family_bench_kernel(
    *,
    layout: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Exact affine core14 bench/autosub kernel for all candidates."""
    route_count = int(arrays["elements"].shape[0])
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
    tie_rank = _bench_permutation_tie_rank(
        arrays["elements"],
        layout["outfield_permutations"],
    )
    winner = _lexicographic_first(
        (
            np.round(utility, 6),
            np.round(expected, 6),
            -np.round(blank, 9),
            np.round(ge8, 9),
            np.round(ge10, 9),
            -tie_rank.astype(np.float64),
        ),
        axis=2,
    )
    route_axis = np.arange(route_count, dtype=np.int64)[:, None]
    legal_axis = np.arange(
        layout["legal"].shape[0],
        dtype=np.int64,
    )[None, :]
    winning_order_indices = layout["outfield_permutations"][
        legal_axis,
        winner,
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
        "expected_autosub_value_raw": expected[
            route_axis,
            legal_axis,
            winner,
        ],
        "expected_autosub_value": np.round(
            expected[route_axis, legal_axis, winner],
            6,
        ),
        "autosub_probability": np.round(
            autosub[route_axis, legal_axis, winner],
            9,
        ),
        "selected_blank": np.round(
            blank[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge8": np.round(
            ge8[route_axis, legal_axis, winner],
            9,
        ),
        "selected_ge10": np.round(
            ge10[route_axis, legal_axis, winner],
            9,
        ),
        "bench_order_utility": np.round(
            utility[route_axis, legal_axis, winner],
            6,
        ),
        "endpoint_evaluations": 2,
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
    base = (
        xpts_mean
        - downside_weight * shortfall
        + upside_weight * excess
    )
    pair_utility = np.round(
        base[:, PAIR_CAP]
        + p_dnp[:, PAIR_CAP] * base[:, PAIR_VICE],
        6,
    )
    cap_mean = np.round(xpts_mean[:, PAIR_CAP], 6)
    vice_fallback = np.round(
        p_dnp[:, PAIR_CAP] * xpts_mean[:, PAIR_VICE],
        6,
    )
    joint_upside = np.round(
        excess[:, PAIR_CAP]
        + p_dnp[:, PAIR_CAP] * excess[:, PAIR_VICE],
        6,
    )
    joint_downside = np.round(
        shortfall[:, PAIR_CAP]
        + p_dnp[:, PAIR_CAP] * shortfall[:, PAIR_VICE],
        6,
    )

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
    actual_legal = scalar._legal_xi_templates(actual_signature)
    actual_rank_by_combination = {
        tuple(int(value) for value in combination): index
        for index, combination in enumerate(actual_legal)
    }
    canonical_to_actual = np.empty(15, dtype=np.int64)
    for actual_slot, canonical_slot in enumerate(actual_order):
        canonical_to_actual[canonical_slot] = actual_slot
    canonical_legal = scalar._legal_xi_templates(position_signature)
    result: list[int] = []
    for row in canonical_legal:
        actual_combination = tuple(
            sorted(
                int(canonical_to_actual[int(slot)])
                for slot in row
            )
        )
        if actual_combination not in actual_rank_by_combination:
            raise LineupBatchError("family legal XI mapping drift")
        result.append(
            int(actual_rank_by_combination[actual_combination])
        )
    return tuple(result)


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
    route_utility = np.round(
        base_utility
        + bench["bench_order_utility"]
        + captain["pair_utility"],
        6,
    )
    expected_before_captain = np.round(
        expected_points
        + bench["expected_autosub_value"],
        6,
    )
    expected_with_captain = np.round(
        expected_points
        + bench["expected_autosub_value"]
        + captain["expected_captain_multiplier_value"]
        + captain["expected_vice_takeover_value"],
        6,
    )
    downside = np.round(shortfall, 6)
    upside = np.round(excess, 6)
    tactical_mean = np.where(
        tactical_count > 0.0,
        np.round(
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
    route_utility = np.round(
        base_utility + bench["bench_order_utility"] + captain["pair_utility"],
        6,
    )
    expected_before_captain = np.round(
        expected_points + bench["expected_autosub_value"],
        6,
    )
    expected_with_captain = np.round(
        expected_points
        + bench["expected_autosub_value"]
        + captain["expected_captain_multiplier_value"]
        + captain["expected_vice_takeover_value"],
        6,
    )
    downside = np.round(shortfall, 6)
    upside = np.round(excess, 6)
    tactical_mean = np.where(
        tactical_count > 0.0,
        np.round(tactical_sum / np.maximum(tactical_count, 1.0), 6),
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
    }
    return outputs, proof
