from __future__ import annotations

"""Execution-only cross-route exact P1.7 batch kernel.

The scalar V12 lineup optimizer remains the mathematical/reference owner.
This module reuses its exact player surfaces, legal-XI templates, resolver
state tables and objective configuration, but evaluates many squads together.
No route is pruned and no P1.1/P1.3/P1.6 mathematics is recomputed here.
"""

import math
import time
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
) -> dict[str, np.ndarray]:
    batch_count, legal_count, _ = starter_mask.shape
    reserve_gk, starter_gk, outfield_bench = _bench_indices(
        starter_mask,
        position_codes,
    )
    def_dist = _position_dnp_distribution(
        starter_mask,
        p_dnp,
        position_codes,
        POS_CODE["DEF"],
        5,
    )
    mid_dist = _position_dnp_distribution(
        starter_mask,
        p_dnp,
        position_codes,
        POS_CODE["MID"],
        5,
    )
    fwd_dist = _position_dnp_distribution(
        starter_mask,
        p_dnp,
        position_codes,
        POS_CODE["FWD"],
        3,
    )

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
    xpts_mean: np.ndarray,
    shortfall: np.ndarray,
    excess: np.ndarray,
    p_dnp: np.ndarray,
) -> dict[str, np.ndarray]:
    objective = dict((scalar.load_config().get("objective") or {}))
    downside_weight = _f(objective.get("captain_downside_weight"), 0.15)
    upside_weight = _f(objective.get("captain_upside_weight"), 0.10)
    base = (
        xpts_mean
        - downside_weight * shortfall
        + upside_weight * excess
    )
    cap = PAIR_CAP
    vice = PAIR_VICE
    pair_utility = np.round(
        base[:, cap]
        + p_dnp[:, cap] * base[:, vice],
        6,
    )
    cap_mean = np.round(xpts_mean[:, cap], 6)
    vice_fallback = np.round(
        p_dnp[:, cap] * xpts_mean[:, vice],
        6,
    )
    joint_upside = np.round(
        excess[:, cap] + p_dnp[:, cap] * excess[:, vice],
        6,
    )
    joint_downside = np.round(
        shortfall[:, cap] + p_dnp[:, cap] * shortfall[:, vice],
        6,
    )
    pair_tie = np.broadcast_to(
        np.arange(PAIR_CAP.size, dtype=np.int64)[None, :],
        pair_utility.shape,
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

    batch_count, legal_count, _ = starter_mask.shape
    winner = np.full((batch_count, legal_count), -1, dtype=np.int64)
    unresolved = np.ones((batch_count, legal_count), dtype=bool)
    route_axis = np.arange(batch_count, dtype=np.int64)[:, None]
    legal_axis = np.arange(legal_count, dtype=np.int64)[None, :]
    for rank in range(pair_order.shape[1]):
        pair_index = pair_order[:, rank]
        cap_index = PAIR_CAP[pair_index]
        vice_index = PAIR_VICE[pair_index]
        eligible = (
            unresolved
            & starter_mask[
                route_axis,
                legal_axis,
                cap_index[:, None],
            ]
            & starter_mask[
                route_axis,
                legal_axis,
                vice_index[:, None],
            ]
        )
        if np.any(eligible):
            winner[eligible] = np.broadcast_to(
                pair_index[:, None],
                winner.shape,
            )[eligible]
            unresolved &= ~eligible
        if not np.any(unresolved):
            break
    if np.any(winner < 0):
        raise LineupBatchError("captain batch lost a legal pair")

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


def _surface_arrays(
    squads: Sequence[tuple[int, ...]],
    *,
    gw: int,
) -> dict[str, Any]:
    surfaces = [
        [scalar._P17_SURFACE_CACHE[(int(element), int(gw))] for element in squad]
        for squad in squads
    ]
    position_rows = [
        [str(row.get("position")) for row in squad_rows]
        for squad_rows in surfaces
    ]
    position_codes = np.asarray(
        [[POS_CODE[position] for position in row] for row in position_rows],
        dtype=np.int8,
    )
    elements = np.asarray(squads, dtype=np.int64)

    def direct(field: str) -> np.ndarray:
        return np.asarray(
            [[_f(row.get(field)) for row in squad_rows] for squad_rows in surfaces],
            dtype=np.float64,
        )

    def appearance(field: str) -> np.ndarray:
        return np.asarray(
            [
                [
                    _f((row.get("appearance_conditioned") or {}).get(field))
                    for row in squad_rows
                ]
                for squad_rows in surfaces
            ],
            dtype=np.float64,
        )

    tactical_weight = np.asarray(
        [
            [
                _f((row.get("tactical_role") or {}).get("weighted_component_points"))
                for row in squad_rows
            ]
            for squad_rows in surfaces
        ],
        dtype=np.float64,
    )
    tactical_available = np.asarray(
        [
            [
                1.0
                if (row.get("tactical_role") or {}).get("weighted_component_points")
                is not None
                else 0.0
                for row in squad_rows
            ]
            for squad_rows in surfaces
        ],
        dtype=np.float64,
    )
    pmf_ready = np.asarray(
        [
            [
                1.0
                if (row.get("distribution_status") or {}).get("status") == "READY"
                else 0.0
                for row in squad_rows
            ]
            for squad_rows in surfaces
        ],
        dtype=np.float64,
    )
    return {
        "position_rows": position_rows,
        "position_codes": position_codes,
        "elements": elements,
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


def _optimize_gw_chunk(
    squads: Sequence[tuple[int, ...]],
    *,
    gw: int,
) -> list[dict[str, Any]]:
    if not squads:
        return []
    arrays = _surface_arrays(squads, gw=gw)
    legal = _legal_templates(arrays["position_rows"])
    if legal.shape[1] != 550:
        raise LineupBatchError(
            f"standard FPL route must preserve 550 legal XI, got {legal.shape[1]}"
        )
    batch_count, legal_count, _ = legal.shape
    starter_mask = np.zeros((batch_count, legal_count, 15), dtype=bool)
    route_axis3 = np.arange(batch_count, dtype=np.int64)[:, None, None]
    legal_axis3 = np.arange(legal_count, dtype=np.int64)[None, :, None]
    starter_mask[route_axis3, legal_axis3, legal] = True
    formation_code = _formation_codes(starter_mask, arrays["position_codes"])

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
    )
    captain = _captain_kernel(
        starter_mask=starter_mask,
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
        for start in range(0, len(valid_indices), batch_size):
            chunk_indices = valid_indices[start : start + batch_size]
            chunk_squads = [normalized[index] for index in chunk_indices]
            chunk_results = _optimize_gw_chunk(chunk_squads, gw=gw)
            if len(chunk_results) != len(chunk_indices):
                raise LineupBatchError("cross-route batch lost squad identity")
            for source_index, result in zip(chunk_indices, chunk_results):
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
    proof = {
        "execution_kernel": "CROSS_ROUTE_NUMPY_EXACT_P1_7",
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
