from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_wc_optimizer import POSITION_COUNTS, Candidate

_FORMATIONS = ((3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,2,3),(5,3,2),(5,4,1))
_POSITIONS = ("GK", "DEF", "MID", "FWD")


@dataclass(frozen=True)
class BatchContext:
    outs: tuple[Candidate, ...]
    keep: tuple[Candidate, ...]
    baseline_metrics: dict
    locked: dict
    policy: dict
    risk_by_element: dict[int, dict]


def _gw(player: Candidate, index: int) -> float:
    return float(player.gw_xpts[index]) if index < len(player.gw_xpts) else 0.0


def _round_array(values: np.ndarray, digits: int) -> np.ndarray:
    """Apply CPython ``round`` elementwise so batch publication matches scalar semantics."""
    return np.fromiter(
        (round(float(value), digits) for value in values),
        dtype=np.float64,
        count=len(values),
    )


def _risk_matrix(rows: Sequence[tuple[Candidate, ...]], risk_by_element: dict[int, dict]) -> dict[str, np.ndarray]:
    keys = (
        "projection_uncertainty", "xmins_uncertainty", "tactical_uncertainty",
        "roster_change_uncertainty", "price_risk", "tactical_role_confidence",
        "opponent_matchup_confidence",
    )
    out: dict[str, np.ndarray] = {}
    for key in keys:
        default = 0.2 if key == "price_risk" else 0.0
        out[key] = np.asarray([
            sum(float((risk_by_element[p.element] or {}).get(key, default) or 0.0) for p in incoming) / max(1, len(incoming))
            for incoming in rows
        ], dtype=np.float64)
    return out


def _outgoing_risk(outs: tuple[Candidate, ...], risk_by_element: dict[int, dict]) -> dict[str, float]:
    keys = (
        "projection_uncertainty", "xmins_uncertainty", "tactical_uncertainty",
        "roster_change_uncertainty", "price_risk", "tactical_role_confidence",
        "opponent_matchup_confidence",
    )
    result = {}
    for key in keys:
        default = 0.2 if key == "price_risk" else 0.0
        result[key] = sum(float((risk_by_element[p.element] or {}).get(key, default) or 0.0) for p in outs) / max(1, len(outs))
    return result


def _best_xi_and_utility(keep: tuple[Candidate, ...], incoming_rows: Sequence[tuple[Candidate, ...]]) -> tuple[np.ndarray, np.ndarray]:
    batch = len(incoming_rows)
    xi5 = np.zeros(batch, dtype=np.float64)
    utility5 = np.zeros(batch, dtype=np.float64)
    keep_by_pos = {pos: tuple(p for p in keep if p.position == pos) for pos in _POSITIONS}

    for gw_index in range(5):
        position_prefix: dict[str, np.ndarray] = {}
        total = np.zeros(batch, dtype=np.float64)
        for pos in _POSITIONS:
            fixed = np.asarray([_gw(p, gw_index) for p in keep_by_pos[pos]], dtype=np.float64)
            add_count = POSITION_COUNTS[pos] - len(keep_by_pos[pos])
            if add_count:
                additions = np.asarray([
                    [_gw(p, gw_index) for p in incoming if p.position == pos]
                    for incoming in incoming_rows
                ], dtype=np.float64)
                if additions.ndim == 1:
                    additions = additions.reshape(batch, add_count)
                values = np.concatenate((np.broadcast_to(fixed, (batch, len(fixed))), additions), axis=1)
            else:
                values = np.broadcast_to(fixed, (batch, len(fixed))).copy()
            values.sort(axis=1)
            values = values[:, ::-1]
            position_prefix[pos] = np.concatenate((np.zeros((batch, 1), dtype=np.float64), np.cumsum(values, axis=1)), axis=1)
            total += values.sum(axis=1)

        gk = position_prefix["GK"][:, 1]
        candidates = []
        for defenders, mids, forwards in _FORMATIONS:
            candidates.append(
                gk
                + position_prefix["DEF"][:, defenders]
                + position_prefix["MID"][:, mids]
                + position_prefix["FWD"][:, forwards]
            )
        xi = np.max(np.stack(candidates, axis=1), axis=1)
        xi5 += xi
        utility5 += xi + 0.12 * (total - xi)
    return xi5, utility5


def evaluate_batch(context: BatchContext, incoming_rows: Sequence[tuple[Candidate, ...]]) -> list[dict]:
    """Exact numeric batch evaluation for legal incoming tuples.

    This changes execution topology only. Scalar V4 semantics remain authoritative:
    target horizon, XI and utility metrics are rounded at the same boundary as the
    canonical scalar kernel before package deltas are calculated. Published survivors
    are still scalar-rehydrated before authority is granted.
    """
    if not incoming_rows:
        return []
    k = len(context.outs)
    if any(len(row) != k for row in incoming_rows):
        raise ValueError("incoming batch replacement count differs from outgoing set")

    outs = context.outs
    baseline = context.baseline_metrics
    incoming_cost = np.asarray([sum(p.cost for p in row) for row in incoming_rows], dtype=np.float64)
    outgoing_cost = float(sum(p.cost for p in outs))

    keep_h = {
        key: float(sum(getattr(p, key) for p in context.keep))
        for key in ("x3", "x5", "x10", "x15")
    }
    incoming_h = {
        key: np.asarray([sum(getattr(p, key) for p in row) for row in incoming_rows], dtype=np.float64)
        for key in ("x3", "x5", "x10", "x15")
    }
    target_h = {
        key: _round_array(incoming_h[key] + keep_h[key], 2)
        for key in incoming_h
    }
    baseline_h = {
        "x3": float(baseline.get("squad_xpts_3") or 0.0),
        "x5": float(baseline.get("squad_xpts_5") or 0.0),
        "x10": float(baseline.get("squad_xpts_10") or 0.0),
        "x15": float(baseline.get("squad_xpts_15") or 0.0),
    }
    delta = {key: target_h[key] - baseline_h[key] for key in target_h}

    hit = float(core._hit_cost(k, context.locked, context.policy))
    incoming_risk = _risk_matrix(incoming_rows, context.risk_by_element)
    outgoing_risk = _outgoing_risk(outs, context.risk_by_element)
    risk = {
        key: _round_array(np.maximum(0.0, incoming_risk[key] - outgoing_risk[key]), 4)
        for key in ("projection_uncertainty", "xmins_uncertainty", "tactical_uncertainty", "roster_change_uncertainty")
    }
    risk["price_risk"] = _round_array(incoming_risk["price_risk"], 4)
    risk["tactical_role_confidence"] = _round_array(incoming_risk["tactical_role_confidence"], 4)
    risk["opponent_matchup_confidence"] = _round_array(incoming_risk["opponent_matchup_confidence"], 4)
    risk_penalty = (
        0.35 * risk["projection_uncertainty"]
        + 0.30 * risk["xmins_uncertainty"]
        + 0.25 * risk["tactical_uncertainty"]
        + 0.20 * risk["roster_change_uncertainty"]
    )

    xi5_raw, utility5_raw = _best_xi_and_utility(context.keep, incoming_rows)
    xi5 = _round_array(xi5_raw, 2)
    utility5 = _round_array(utility5_raw, 2)
    dxi = xi5 - float(baseline.get("best_xi_xpts_5") or 0.0)
    du = utility5 - float(baseline.get("bench_adjusted_utility_5") or 0.0)
    adjusted_xi = dxi - hit - risk_penalty
    adjusted_utility = du - hit - risk_penalty
    current_itb = int(context.locked.get("itb_tenths") or 0)
    target_itb = current_itb + outgoing_cost - incoming_cost
    target_cost = float(baseline.get("cost") or 0.0) + incoming_cost - outgoing_cost
    flexibility = np.minimum(1.0, 0.55 * np.minimum(1.0, np.maximum(0.0, target_itb) / 20.0) + 0.45)

    rows: list[dict] = []
    for index, incoming in enumerate(incoming_rows):
        values = {
            "package_id": core._package_id(outs, incoming),
            "replacements": k,
            "_out_ids": tuple(p.element for p in outs),
            "_in_ids": tuple(p.element for p in incoming),
            "target_cost": int(round(target_cost[index])),
            "target_itb": int(round(target_itb[index])),
            "delta_cost": int(round(incoming_cost[index] - outgoing_cost)),
            "hit_cost": int(hit),
            "gross_xpts_3": round(float(delta["x3"][index]), 3),
            "gross_xpts_5": round(float(delta["x5"][index]), 3),
            "gross_xpts_10": round(float(delta["x10"][index]), 3),
            "gross_xpts_15": round(float(delta["x15"][index]), 3),
            "net_xpts_3": round(float(delta["x3"][index] - hit), 3),
            "net_xpts_5": round(float(delta["x5"][index] - hit), 3),
            "net_xpts_10": round(float(delta["x10"][index] - hit), 3),
            "net_xpts_15": round(float(delta["x15"][index] - hit), 3),
            "delta_squad_xpts_3": round(float(delta["x3"][index]), 3),
            "delta_squad_xpts_5": round(float(delta["x5"][index]), 3),
            "delta_squad_xpts_10": round(float(delta["x10"][index]), 3),
            "delta_squad_xpts_15": round(float(delta["x15"][index]), 3),
            "delta_best_xi_xpts_5": round(float(dxi[index]), 3),
            "delta_bench_adjusted_utility_5": round(float(du[index]), 3),
            "risk_penalty": round(float(risk_penalty[index]), 4),
            "adjusted_best_xi_gain_5": round(float(adjusted_xi[index]), 3),
            "adjusted_utility_gain_5": round(float(adjusted_utility[index]), 3),
            "projection_uncertainty": float(risk["projection_uncertainty"][index]),
            "xmins_uncertainty": float(risk["xmins_uncertainty"][index]),
            "tactical_uncertainty": float(risk["tactical_uncertainty"][index]),
            "roster_change_uncertainty": float(risk["roster_change_uncertainty"][index]),
            "price_risk": float(risk["price_risk"][index]),
            "tactical_role_confidence": float(risk["tactical_role_confidence"][index]),
            "opponent_matchup_confidence": float(risk["opponent_matchup_confidence"][index]),
            "structural_flexibility": round(float(flexibility[index]), 4),
            "classification": core.reference.package_class(float(adjusted_xi[index]), float(adjusted_utility[index]), k),
            "batch_execution_only": True,
        }
        rows.append(values)
    return rows


def scalar_rehydrate(context: BatchContext, incoming: tuple[Candidate, ...], row: dict) -> dict:
    profile = core._keep_profile(context.keep)
    chosen = core._chosen_profile(incoming)
    metrics = core._metrics_from_profiles(profile, chosen)
    target = context.keep + incoming
    return core._evaluate_package(
        context.outs,
        incoming,
        target,
        metrics,
        context.baseline_metrics,
        context.locked,
        context.policy,
        {},
        {},
        context.risk_by_element,
    )


def assert_scalar_equivalent(context: BatchContext, incoming_rows: Sequence[tuple[Candidate, ...]], batch_rows: Sequence[dict]) -> None:
    if len(incoming_rows) != len(batch_rows):
        raise AssertionError("batch/scalar row count mismatch")
    numeric = (
        "target_cost", "target_itb", "delta_cost", "hit_cost",
        "gross_xpts_3", "gross_xpts_5", "gross_xpts_10", "gross_xpts_15",
        "net_xpts_3", "net_xpts_5", "net_xpts_10", "net_xpts_15",
        "delta_best_xi_xpts_5", "delta_bench_adjusted_utility_5", "risk_penalty",
        "adjusted_best_xi_gain_5", "adjusted_utility_gain_5", "projection_uncertainty",
        "xmins_uncertainty", "tactical_uncertainty", "roster_change_uncertainty",
        "price_risk", "tactical_role_confidence", "opponent_matchup_confidence",
        "structural_flexibility",
    )
    for incoming, batch in zip(incoming_rows, batch_rows):
        scalar = scalar_rehydrate(context, incoming, batch)
        for key in numeric:
            if batch.get(key) != scalar.get(key):
                raise AssertionError(f"batch/scalar mismatch {batch['package_id']} {key}: {batch.get(key)} != {scalar.get(key)}")
        if batch.get("classification") != scalar.get("classification"):
            raise AssertionError(f"batch/scalar classification mismatch {batch['package_id']}")
