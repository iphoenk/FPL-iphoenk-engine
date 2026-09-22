from __future__ import annotations

"""P1.7 V12-native distributional XI / bench / captain / vice owner.

This module consumes P1.1 state probabilities, P1.3B point distributions and
P1.6 tactical-role output read-only. It never owns transfer packages, Monte
Carlo, mini-league logic, V6 acquisition, or upstream model mathematics.
"""

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import itertools
import json
import math
import numpy as np
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    validate_methodology_weights,
)
from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    build_model_run_binding,
    fingerprint,
    freeze_prediction,
    settle_frozen_record,
)
from src.rules import LINEUP_RULES, RULESET_ID

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_lineup_optimizer.json"
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
MODEL_OWNER = "V12_LINEUP_OPTIMIZER"
POSITIONS = ("GK", "DEF", "MID", "FWD")
OUTFIELD = ("DEF", "MID", "FWD")
LEGAL_FORMATIONS = frozenset(LINEUP_RULES.get("legal_formations") or [])


class LineupOptimizerError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if cfg.get("contract") != "V12_DISTRIBUTIONAL_LINEUP_OPTIMIZER_V1":
        raise LineupOptimizerError("P1.7 config contract drift")
    if cfg.get("model_owner") != MODEL_OWNER:
        raise LineupOptimizerError("P1.7 model owner drift")
    validate_methodology_weights(CANONICAL_WEIGHTS, authority=CANONICAL_AUTHORITY)
    if _f((cfg.get("tactical") or {}).get("canonical_weight"), -1.0) != 0.25:
        raise LineupOptimizerError("P1.6 tactical weight must remain exactly 0.25")
    return cfg


def _formation_from_counts(counts: Mapping[str, int]) -> str | None:
    if int(counts.get("GK", 0)) != 1:
        return None
    formation = f"{int(counts.get('DEF', 0))}-{int(counts.get('MID', 0))}-{int(counts.get('FWD', 0))}"
    return formation if formation in LEGAL_FORMATIONS else None


def _formation(rows: Sequence[Mapping[str, Any]]) -> str | None:
    counts = {position: sum(1 for row in rows if row.get("position") == position) for position in POSITIONS}
    return _formation_from_counts(counts)


def enumerate_legal_xi(players: Sequence[Mapping[str, Any]]) -> list[tuple[int, ...]]:
    rows = [dict(row) for row in players]
    if len(rows) != 15:
        raise LineupOptimizerError("P1.7 requires OUR15 exactly")
    required_size = int(LINEUP_RULES.get("starting_xi_size") or 11)
    required_gk = int(LINEUP_RULES.get("starting_goalkeepers") or 1)
    legal: list[tuple[int, ...]] = []
    for combo in itertools.combinations(range(len(rows)), required_size):
        selected = [rows[index] for index in combo]
        if sum(1 for row in selected if row.get("position") == "GK") != required_gk:
            continue
        if _formation(selected):
            legal.append(tuple(combo))
    return legal


def _gw_row(projection: Mapping[str, Any], planning_gw: int) -> dict[str, Any]:
    for row in projection.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(planning_gw):
            return dict(row)
    return {"gw": int(planning_gw), "mean": 0.0, "std": 0.0, "fixtures": []}


def _state_probabilities(projection: Mapping[str, Any]) -> dict[str, float]:
    xmins = dict(projection.get("xmins") or {})
    dist = dict(xmins.get("xmins_distribution") or {})
    states = {
        str(row.get("state") or ""): _f(row.get("probability"))
        for row in dist.get("states") or []
        if isinstance(row, Mapping)
    }
    if {"START", "REGULAR_CAMEO", "LATE_CAMEO", "ZERO_MINUTES"} <= set(states):
        start = max(0.0, states["START"])
        regular = max(0.0, states["REGULAR_CAMEO"])
        late = max(0.0, states["LATE_CAMEO"])
        dnp = max(0.0, states["ZERO_MINUTES"])
    else:
        start = max(0.0, _f(xmins.get("start_probability")))
        cameo_total = max(0.0, _f(xmins.get("cameo_probability")))
        late = max(0.0, min(cameo_total, _f(xmins.get("late_cameo_probability"))))
        regular = max(0.0, cameo_total - late)
        dnp = max(0.0, _f(xmins.get("dnp_probability")))
    total = start + regular + late + dnp
    if total <= 0.0:
        start, regular, late, dnp, total = 0.0, 0.0, 0.0, 1.0, 1.0
    start, regular, late, dnp = (value / total for value in (start, regular, late, dnp))
    return {
        "START": start,
        "REGULAR_CAMEO": regular,
        "LATE_CAMEO": late,
        "DNP": dnp,
        "APPEAR": start + regular + late,
    }


def _point_distribution(gw_row: Mapping[str, Any]) -> tuple[dict[int, float] | None, dict[str, Any]]:
    payload = gw_row.get("point_distribution")
    if not isinstance(payload, Mapping) or not payload.get("probabilities"):
        fixtures = [row for row in gw_row.get("fixtures") or [] if isinstance(row, Mapping)]
        if len(fixtures) == 1:
            payload = fixtures[0].get("point_distribution")
    if not isinstance(payload, Mapping) or not payload.get("probabilities"):
        return None, {
            "status": "PARTIAL_MOMENTS_ONLY",
            "reason": "P1.3B_EXACT_GW_POINT_PMF_UNAVAILABLE",
            "tails_fabricated": False,
        }
    probabilities: dict[int, float] = {}
    for key, value in dict(payload.get("probabilities") or {}).items():
        probability = max(0.0, _f(value))
        if probability > 0.0:
            probabilities[int(key)] = probability
    mass = sum(probabilities.values())
    if mass <= 0.0:
        return None, {
            "status": "PARTIAL_MOMENTS_ONLY",
            "reason": "P1.3B_PMF_ZERO_MASS",
            "tails_fabricated": False,
        }
    probabilities = {points: probability / mass for points, probability in probabilities.items()}
    return probabilities, {
        "status": "READY",
        "distribution_completeness": payload.get("distribution_completeness"),
        "bonus_incorporation": payload.get("bonus_incorporation"),
        "source_model": payload.get("model"),
        "sum_probability": sum(probabilities.values()),
        "tails_fabricated": False,
    }


def _pmf_metric(pmf: Mapping[int, float] | None, *, threshold: float, mode: str) -> float | None:
    if pmf is None:
        return None
    if mode == "shortfall":
        return sum(max(0.0, threshold - points) * probability for points, probability in pmf.items())
    if mode == "excess":
        return sum(max(0.0, points - threshold) * probability for points, probability in pmf.items())
    if mode == "le":
        return sum(probability for points, probability in pmf.items() if points <= threshold)
    if mode == "ge":
        return sum(probability for points, probability in pmf.items() if points >= threshold)
    raise LineupOptimizerError(f"unknown PMF metric mode: {mode}")


def _tactical_surface(projection: Mapping[str, Any]) -> dict[str, Any]:
    tactical = dict(projection.get("tactical_role_component") or {})
    canonical = dict(tactical.get("canonical_component") or {})
    weight = canonical.get("weight")
    if weight is not None and not math.isclose(_f(weight), 0.25, rel_tol=0.0, abs_tol=1e-12):
        raise LineupOptimizerError("P1.6 tactical component weight drift")
    score = tactical.get("canonical_tactical_role_score")
    if score is None:
        score = tactical.get("tactical_role_score")
    return {
        "status": "AVAILABLE" if score is not None else "UNAVAILABLE",
        "score": None if score is None else round(_f(score), 6),
        "canonical_weight": 0.25,
        "weighted_component_points": canonical.get("weighted_component_points"),
        "confidence": tactical.get("confidence"),
        "source_owner": "V12_TACTICAL_ROLE",
        "formula_recomputed": False,
    }


def build_player_surface(projection: Mapping[str, Any], planning_gw: int) -> dict[str, Any]:
    cfg = load_config()
    objective = dict(cfg.get("objective") or {})
    gw_row = _gw_row(projection, planning_gw)
    states = _state_probabilities(projection)
    pmf, pmf_status = _point_distribution(gw_row)
    mean = _f(gw_row.get("mean"))
    variance = max(0.0, _f(gw_row.get("points_variance"), _f(gw_row.get("std")) ** 2))
    std = math.sqrt(variance)
    downside_threshold = _f(objective.get("downside_shortfall_threshold"), 2.0)
    upside_threshold = _f(objective.get("upside_excess_threshold"), 8.0)
    shortfall = _pmf_metric(pmf, threshold=downside_threshold, mode="shortfall")
    excess = _pmf_metric(pmf, threshold=upside_threshold, mode="excess")
    p_blank = _pmf_metric(pmf, threshold=downside_threshold, mode="le")
    p_ge8 = _pmf_metric(pmf, threshold=8.0, mode="ge")
    p_ge10 = _pmf_metric(pmf, threshold=10.0, mode="ge")
    downside_weight = _f(objective.get("lineup_downside_weight"), 0.10)
    upside_weight = _f(objective.get("lineup_upside_weight"), 0.05)
    distributional_utility = mean
    if shortfall is not None:
        distributional_utility -= downside_weight * shortfall
    if excess is not None:
        distributional_utility += upside_weight * excess
    p_appear = states["APPEAR"]
    conditional_mean = mean / p_appear if p_appear > 1e-12 else 0.0
    second = variance + mean * mean
    conditional_variance = (
        max(0.0, second / p_appear - conditional_mean * conditional_mean)
        if p_appear > 1e-12
        else 0.0
    )
    conditional_blank = (
        max(0.0, min(1.0, (_f(p_blank) - states["DNP"]) / p_appear))
        if p_blank is not None and p_appear > 1e-12
        else None
    )
    conditional_ge8 = (
        max(0.0, min(1.0, _f(p_ge8) / p_appear))
        if p_ge8 is not None and p_appear > 1e-12
        else None
    )
    conditional_ge10 = (
        max(0.0, min(1.0, _f(p_ge10) / p_appear))
        if p_ge10 is not None and p_appear > 1e-12
        else None
    )
    tactical = _tactical_surface(projection)
    xmins = dict(projection.get("xmins") or {})
    return {
        "element": int(projection.get("element") or 0),
        "name": projection.get("name"),
        "position": projection.get("position"),
        "team_id": int(projection.get("team_id") or -1),
        "xpts_mean": round(mean, 6),
        "xpts_variance": round(variance, 6),
        "xpts_std": round(std, 6),
        "distributional_utility": round(distributional_utility, 6),
        "selection_score": round(distributional_utility, 6),
        "selection_score_semantics": "P1_7_DISTRIBUTIONAL_UTILITY_COMPATIBILITY_ALIAS",
        "expected_shortfall": None if shortfall is None else round(shortfall, 6),
        "expected_excess_ge_8": None if excess is None else round(excess, 6),
        "p_fpl_blank": None if p_blank is None else round(p_blank, 9),
        "p_points_ge_8": None if p_ge8 is None else round(p_ge8, 9),
        "p_points_ge_10": None if p_ge10 is None else round(p_ge10, 9),
        "point_distribution": (
            None
            if pmf is None
            else {str(points): round(probability, 12) for points, probability in sorted(pmf.items())}
        ),
        "distribution_status": pmf_status,
        "states": {
            "START": round(states["START"], 9),
            "REGULAR_CAMEO": round(states["REGULAR_CAMEO"], 9),
            "LATE_CAMEO": round(states["LATE_CAMEO"], 9),
            "DNP": round(states["DNP"], 9),
            "CAMEO_BLOCKED_AUTOSUB": round(states["REGULAR_CAMEO"] + states["LATE_CAMEO"], 9),
        },
        "p_start": round(states["START"], 9),
        "p_cameo": round(states["REGULAR_CAMEO"] + states["LATE_CAMEO"], 9),
        "p_late_cameo": round(states["LATE_CAMEO"], 9),
        "p_dnp": round(states["DNP"], 9),
        "p_appearance": round(p_appear, 9),
        "xmins": round(_f(xmins.get("expected_minutes"), _f((xmins.get("xmins_distribution") or {}).get("mean"))), 6),
        "xmins_std": round(_f((xmins.get("xmins_distribution") or {}).get("std")), 6),
        "confidence": projection.get("projection_confidence") or xmins.get("confidence"),
        "appearance_conditioned": {
            "expected_points": round(conditional_mean, 6),
            "variance": round(conditional_variance, 6),
            "p_fpl_blank": None if conditional_blank is None else round(conditional_blank, 9),
            "p_points_ge_8": None if conditional_ge8 is None else round(conditional_ge8, 9),
            "p_points_ge_10": None if conditional_ge10 is None else round(conditional_ge10, 9),
            "derivation": "EXACT_FROM_UNCONDITIONAL_PMF_AND_DNP_ZERO_STATE_WHERE_SUPPORTED",
        },
        "tactical_role": tactical,
        "governance": {
            "p1_1_consumed_read_only": True,
            "p1_3_consumed_read_only": True,
            "p1_6_consumed_read_only": True,
            "per_state_point_pmf_rematerialized": False,
            "tails_fabricated": False,
            "transfer_economics_consumed": False,
            "duplicate_player_surface_payload": False,
        },
    }


@lru_cache(maxsize=4096)
def _poisson_binomial_count_probabilities(
    probabilities: tuple[float, ...],
) -> tuple[float, ...]:
    """Exact Poisson-binomial count probabilities for one position group."""
    dist = [1.0]
    for raw_probability in probabilities:
        p = max(0.0, min(1.0, float(raw_probability)))
        nxt = [0.0] * (len(dist) + 1)
        for count, probability in enumerate(dist):
            nxt[count] += probability * (1.0 - p)
            nxt[count + 1] += probability * p
        dist = nxt
    return tuple(dist)


def _dnp_count_distribution(
    starters: Sequence[Mapping[str, Any]],
    *,
    cameo_as_dnp: bool = False,
    late_cameo_as_dnp: bool = False,
) -> list[tuple[tuple[int, int, int], float]]:
    """Exact position-count DNP distribution with reusable subset caches."""
    grouped: dict[str, list[float]] = {position: [] for position in OUTFIELD}
    for row in starters:
        position = str(row.get("position"))
        if position not in grouped:
            continue
        p = _f(row.get("p_dnp"))
        if cameo_as_dnp:
            p += _f(row.get("p_cameo"))
        elif late_cameo_as_dnp:
            p += _f(row.get("p_late_cameo"))
        grouped[position].append(max(0.0, min(1.0, p)))

    # Count probabilities are exchangeable within a position; sorting makes
    # equivalent positional subsets share the cache without changing exact math.
    per_position = {
        position: _poisson_binomial_count_probabilities(
            tuple(sorted(grouped[position]))
        )
        for position in OUTFIELD
    }
    out: list[tuple[tuple[int, int, int], float]] = []
    for def_count, def_probability in enumerate(per_position["DEF"]):
        for mid_count, mid_probability in enumerate(per_position["MID"]):
            for fwd_count, fwd_probability in enumerate(per_position["FWD"]):
                probability = def_probability * mid_probability * fwd_probability
                if probability > 1e-15:
                    out.append(((def_count, mid_count, fwd_count), probability))
    return out


@lru_cache(maxsize=4096)
def _appearance_mask_probabilities(
    probabilities: tuple[float, float, float],
) -> tuple[float, ...]:
    """Exact probability of each three-player bench appearance mask."""
    p0, p1, p2 = (
        max(0.0, min(1.0, float(probability)))
        for probability in probabilities
    )
    q0, q1, q2 = 1.0 - p0, 1.0 - p1, 1.0 - p2
    return (
        q0 * q1 * q2,
        p0 * q1 * q2,
        q0 * p1 * q2,
        p0 * p1 * q2,
        q0 * q1 * p2,
        p0 * q1 * p2,
        q0 * p1 * p2,
        p0 * p1 * p2,
    )


@lru_cache(maxsize=4096)
def _resolve_outfield_pattern(
    start_counts: tuple[int, int, int],
    dnp_counts: tuple[int, int, int],
    bench_positions: tuple[str, str, str],
    appearance_mask: int,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[tuple[int, str], ...]]:
    current = {"DEF": start_counts[0], "MID": start_counts[1], "FWD": start_counts[2]}
    remaining = {"DEF": dnp_counts[0], "MID": dnp_counts[1], "FWD": dnp_counts[2]}

    def legal_counts(counts: Mapping[str, int]) -> bool:
        return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}" in LEGAL_FORMATIONS

    def rec(
        index: int,
        counts: dict[str, int],
        missing: dict[str, int],
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[tuple[int, str], ...]]:
        if index >= 3 or sum(missing.values()) <= 0:
            return (), (), ()
        reached = (index,)
        appears = bool(appearance_mask & (1 << index))
        if not appears:
            selected, later_reached, mapping = rec(index + 1, counts, missing)
            return selected, reached + later_reached, mapping

        bench_pos = bench_positions[index]
        choices: list[tuple[tuple[int, ...], tuple[int, ...], tuple[tuple[int, str], ...]]] = []
        for old_pos in OUTFIELD:
            if missing.get(old_pos, 0) <= 0:
                continue
            next_counts = dict(counts)
            next_counts[old_pos] -= 1
            next_counts[bench_pos] += 1
            if not legal_counts(next_counts):
                continue
            next_missing = dict(missing)
            next_missing[old_pos] -= 1
            selected, later_reached, mapping = rec(index + 1, next_counts, next_missing)
            choices.append(
                ((index,) + selected, reached + later_reached, ((index, old_pos),) + mapping)
            )
        if not choices:
            selected, later_reached, mapping = rec(index + 1, counts, missing)
            return selected, reached + later_reached, mapping
        choices.sort(key=lambda row: (len(row[0]), tuple(-x for x in row[0])), reverse=True)
        return choices[0]

    return rec(0, current, remaining)


@lru_cache(maxsize=8192)
def _resolver_mask_table(
    start_counts: tuple[int, int, int],
    dnp_counts: tuple[int, int, int],
    bench_positions: tuple[str, str, str],
) -> tuple[tuple[int, int], ...]:
    """Exact selected/reached bitmasks for all eight bench appearance masks.

    This changes computation reuse only: every mask is delegated to the same
    canonical formation-legal resolver used before the optimization.
    """
    rows: list[tuple[int, int]] = []
    for appearance_mask in range(8):
        selected, reached, _ = _resolve_outfield_pattern(
            start_counts,
            dnp_counts,
            bench_positions,
            appearance_mask,
        )
        selected_bits = sum(1 << index for index in selected)
        reached_bits = sum(1 << index for index in reached)
        rows.append((selected_bits, reached_bits))
    return tuple(rows)


def _expected_outfield_autosub(
    starters: Sequence[Mapping[str, Any]],
    bench_order: Sequence[Mapping[str, Any]],
    *,
    cameo_as_dnp: bool = False,
    late_cameo_as_dnp: bool = False,
    count_states: Sequence[tuple[tuple[int, int, int], float]] | None = None,
) -> dict[str, Any]:
    """Exact autosub expectation with vectorized probability-mass aggregation.

    The canonical formation-legal resolver is unchanged.  NumPy replaces only
    the hot Python accumulation over DNP-count states x eight bench-appearance
    masks; every selected/reached mask still comes from _resolver_mask_table.
    """
    outfield_starters = [
        row for row in starters if row.get("position") in OUTFIELD
    ]
    start_counts = tuple(
        sum(
            1
            for row in outfield_starters
            if row.get("position") == position
        )
        for position in OUTFIELD
    )
    bench_positions = tuple(
        str(row.get("position")) for row in bench_order
    )
    resolved_count_states = (
        list(count_states)
        if count_states is not None
        else _dnp_count_distribution(
            outfield_starters,
            cameo_as_dnp=cameo_as_dnp,
            late_cameo_as_dnp=late_cameo_as_dnp,
        )
    )
    appear = tuple(
        max(0.0, min(1.0, _f(row.get("p_appearance"))))
        for row in bench_order
    )
    mask_probabilities = np.asarray(
        _appearance_mask_probabilities(appear),
        dtype=np.float64,
    )
    conditioned_rows = [
        dict(row.get("appearance_conditioned") or {})
        for row in bench_order
    ]
    expected_by_slot = np.asarray(
        [_f(row.get("expected_points")) for row in conditioned_rows],
        dtype=np.float64,
    )
    blank_by_slot = tuple(
        None
        if row.get("p_fpl_blank") is None
        else _f(row.get("p_fpl_blank"))
        for row in conditioned_rows
    )
    ge8_by_slot = tuple(
        None
        if row.get("p_points_ge_8") is None
        else _f(row.get("p_points_ge_8"))
        for row in conditioned_rows
    )
    ge10_by_slot = tuple(
        None
        if row.get("p_points_ge_10") is None
        else _f(row.get("p_points_ge_10"))
        for row in conditioned_rows
    )

    if not resolved_count_states:
        return {
            "expected_points": 0.0,
            "autosub_probability": 0.0,
            "slot_selected_probability": [0.0, 0.0, 0.0],
            "slot_reach_probability": [0.0, 0.0, 0.0],
            "expected_selected_blank_probability_mass": 0.0,
            "expected_selected_ge8_probability_mass": 0.0,
            "expected_selected_ge10_probability_mass": 0.0,
        }

    starter_probabilities = np.asarray(
        [float(probability) for _, probability in resolved_count_states],
        dtype=np.float64,
    )
    joint_probability = (
        starter_probabilities[:, None] * mask_probabilities[None, :]
    )

    selected_bits = np.empty(
        (len(resolved_count_states), 8),
        dtype=np.uint8,
    )
    reached_bits = np.empty_like(selected_bits)
    for state_index, (dnp_counts, _) in enumerate(
        resolved_count_states
    ):
        table = _resolver_mask_table(
            start_counts,
            dnp_counts,
            bench_positions,
        )
        selected_bits[state_index, :] = tuple(
            row[0] for row in table
        )
        reached_bits[state_index, :] = tuple(
            row[1] for row in table
        )

    autosub_probability = float(
        np.sum(
            joint_probability[selected_bits != 0],
            dtype=np.float64,
        )
    )
    selected_prob: list[float] = []
    reach_prob: list[float] = []
    for index in range(3):
        bit = 1 << index
        selected_prob.append(
            float(
                np.sum(
                    joint_probability[
                        (selected_bits & bit) != 0
                    ],
                    dtype=np.float64,
                )
            )
        )
        reach_prob.append(
            float(
                np.sum(
                    joint_probability[
                        (reached_bits & bit) != 0
                    ],
                    dtype=np.float64,
                )
            )
        )

    selected_array = np.asarray(
        selected_prob,
        dtype=np.float64,
    )
    expected_points = float(
        np.dot(selected_array, expected_by_slot)
    )
    selected_blank = float(
        sum(
            selected_prob[index] * float(value)
            for index, value in enumerate(blank_by_slot)
            if value is not None
        )
    )
    selected_ge8 = float(
        sum(
            selected_prob[index] * float(value)
            for index, value in enumerate(ge8_by_slot)
            if value is not None
        )
    )
    selected_ge10 = float(
        sum(
            selected_prob[index] * float(value)
            for index, value in enumerate(ge10_by_slot)
            if value is not None
        )
    )
    return {
        "expected_points": expected_points,
        "autosub_probability": autosub_probability,
        "slot_selected_probability": selected_prob,
        "slot_reach_probability": reach_prob,
        "expected_selected_blank_probability_mass": selected_blank,
        "expected_selected_ge8_probability_mass": selected_ge8,
        "expected_selected_ge10_probability_mass": selected_ge10,
    }

def _expected_gk_autosub(
    starter_gk: Mapping[str, Any],
    reserve_gk: Mapping[str, Any],
    *,
    cameo_as_dnp: bool = False,
    late_cameo_as_dnp: bool = False,
) -> dict[str, float]:
    trigger = _f(starter_gk.get("p_dnp"))
    if cameo_as_dnp:
        trigger += _f(starter_gk.get("p_cameo"))
    elif late_cameo_as_dnp:
        trigger += _f(starter_gk.get("p_late_cameo"))
    trigger = max(0.0, min(1.0, trigger))
    substitution_probability = trigger * _f(reserve_gk.get("p_appearance"))
    expected_points = trigger * _f(reserve_gk.get("xpts_mean"))
    return {
        "expected_points": expected_points,
        "autosub_probability": substitution_probability,
    }


def evaluate_bench_order(
    starters: Sequence[Mapping[str, Any]],
    reserve_gk: Mapping[str, Any],
    bench_order: Sequence[Mapping[str, Any]],
    *,
    include_blocking_counterfactual: bool = True,
    actual_count_states: Sequence[
        tuple[tuple[int, int, int], float]
    ] | None = None,
    include_slots: bool = True,
) -> dict[str, Any]:
    if len(bench_order) != 3 or any(row.get("position") == "GK" for row in bench_order):
        raise LineupOptimizerError("outfield bench order must contain exactly three non-GK players")
    cfg = load_config()
    objective = dict(cfg.get("objective") or {})
    actual = _expected_outfield_autosub(
        starters,
        bench_order,
        count_states=actual_count_states,
    )
    starter_gk = next(row for row in starters if row.get("position") == "GK")
    actual_gk = _expected_gk_autosub(starter_gk, reserve_gk)

    expected_autosub_value = actual["expected_points"] + actual_gk["expected_points"]
    autosub_probability = 1.0 - (
        (1.0 - actual["autosub_probability"]) * (1.0 - actual_gk["autosub_probability"])
    )

    blocked_value = None
    late_blocked_value = None
    blocked_probability = None
    if include_blocking_counterfactual:
        cameo_cf = _expected_outfield_autosub(
            starters, bench_order, cameo_as_dnp=True
        )
        late_cf = _expected_outfield_autosub(
            starters, bench_order, late_cameo_as_dnp=True
        )
        cameo_gk = _expected_gk_autosub(
            starter_gk, reserve_gk, cameo_as_dnp=True
        )
        late_gk = _expected_gk_autosub(
            starter_gk, reserve_gk, late_cameo_as_dnp=True
        )
        cameo_counterfactual = (
            cameo_cf["expected_points"] + cameo_gk["expected_points"]
        )
        late_counterfactual = (
            late_cf["expected_points"] + late_gk["expected_points"]
        )
        blocked_value = max(
            0.0, cameo_counterfactual - expected_autosub_value
        )
        late_blocked_value = max(
            0.0, late_counterfactual - expected_autosub_value
        )
        cameo_cf_probability = 1.0 - (
            (1.0 - cameo_cf["autosub_probability"])
            * (1.0 - cameo_gk["autosub_probability"])
        )
        blocked_probability = max(
            0.0, cameo_cf_probability - autosub_probability
        )

    blank_weight = _f(objective.get("bench_blank_probability_weight_points"), 0.20)
    upside_weight = _f(objective.get("bench_ge8_probability_weight_points"), 0.20)
    bench_utility = (
        expected_autosub_value
        - blank_weight * actual["expected_selected_blank_probability_mass"]
        + upside_weight * actual["expected_selected_ge8_probability_mass"]
    )
    slots: list[dict[str, Any]] = []
    if include_slots:
        for index, row in enumerate(bench_order):
            slots.append({
                "slot": index + 1,
                "element": row.get("element"),
                "name": row.get("name"),
                "position": row.get("position"),
                "reach_probability": round(actual["slot_reach_probability"][index], 9),
                "substitution_probability": round(actual["slot_selected_probability"][index], 9),
                "expected_utility_contribution": round(
                    actual["slot_selected_probability"][index]
                    * _f((row.get("appearance_conditioned") or {}).get("expected_points")),
                    6,
                ),
                "bench_score": round(
                    actual["slot_selected_probability"][index]
                    * _f((row.get("appearance_conditioned") or {}).get("expected_points")),
                    6,
                ),
                "appearance_conditioned_p_blank": (row.get("appearance_conditioned") or {}).get("p_fpl_blank"),
                "appearance_conditioned_p_ge_8": (row.get("appearance_conditioned") or {}).get("p_points_ge_8"),
                "appearance_conditioned_p_ge_10": (row.get("appearance_conditioned") or {}).get("p_points_ge_10"),
            })
    return {
        "order": [int(row.get("element") or 0) for row in bench_order],
        "slots": slots,
        "expected_autosub_value": round(expected_autosub_value, 6),
        "expected_blocked_autosub_value": (
            None if blocked_value is None else round(blocked_value, 6)
        ),
        "expected_late_cameo_blocked_autosub_value": (
            None if late_blocked_value is None else round(late_blocked_value, 6)
        ),
        "autosub_probability": round(autosub_probability, 9),
        "blocked_autosub_probability": (
            None if blocked_probability is None else round(blocked_probability, 9)
        ),
        "expected_selected_blank_probability_mass": round(actual["expected_selected_blank_probability_mass"], 9),
        "expected_selected_ge8_probability_mass": round(actual["expected_selected_ge8_probability_mass"], 9),
        "expected_selected_ge10_probability_mass": round(actual["expected_selected_ge10_probability_mass"], 9),
        "bench_order_utility": round(bench_utility, 6),
        "reserve_gk": {
            "element": reserve_gk.get("element"),
            "name": reserve_gk.get("name"),
            "position": "GK",
            "autosub_probability": round(actual_gk["autosub_probability"], 9),
            "expected_autosub_value": round(actual_gk["expected_points"], 6),
            "separate_from_outfield_priority": True,
        },
        "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
        "appearance_dependence_assumption": "INDEPENDENCE_APPROXIMATION_PENDING_COVARIANCE_MODEL",
        "governance": {
            "global_team_level_resolver": True,
            "cameo_blocks_autosub": True,
            "late_cameo_blocks_autosub": True,
            "dnp_only_triggers_autosub": True,
            "bench_points_not_treated_as_guaranteed": True,
            "blocking_counterfactual_evaluated": bool(include_blocking_counterfactual),
        },
    }


def optimize_bench_order(
    starters: Sequence[Mapping[str, Any]],
    reserve_gk: Mapping[str, Any],
    outfield_bench: Sequence[Mapping[str, Any]],
    *,
    include_winner_blocking_counterfactual: bool = True,
    publish_alternatives: bool = True,
    include_winner_slots: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    outfield_starters = [row for row in starters if row.get("position") in OUTFIELD]
    actual_count_states = _dnp_count_distribution(outfield_starters)
    screened = [
        evaluate_bench_order(
            starters,
            reserve_gk,
            permutation,
            include_blocking_counterfactual=False,
            actual_count_states=actual_count_states,
            include_slots=publish_alternatives,
        )
        for permutation in itertools.permutations(list(outfield_bench), 3)
    ]
    screened.sort(
        key=lambda row: (
            _f(row.get("bench_order_utility")),
            _f(row.get("expected_autosub_value")),
            -_f(row.get("expected_selected_blank_probability_mass")),
            _f(row.get("expected_selected_ge8_probability_mass")),
            _f(row.get("expected_selected_ge10_probability_mass")),
        ),
        reverse=True,
    )
    order_to_player = {int(row.get("element") or 0): row for row in outfield_bench}
    winner_order = [order_to_player[element] for element in screened[0]["order"]]
    if (
        not include_winner_blocking_counterfactual
        and not include_winner_slots
    ):
        # Compact route scoring already evaluated this exact permutation.
        # Reuse the exact screened metrics instead of running a seventh
        # identical autosub expectation pass.
        winner = dict(screened[0])
    else:
        winner = evaluate_bench_order(
            starters,
            reserve_gk,
            winner_order,
            include_blocking_counterfactual=include_winner_blocking_counterfactual,
            actual_count_states=actual_count_states,
            include_slots=include_winner_slots,
        )
    alternatives: list[dict[str, Any]] = []
    if publish_alternatives:
        alternatives = [winner] + [
            row for row in screened if row.get("order") != winner.get("order")
        ]
    return winner, alternatives


def _captain_vice_pair_row(
    captain: Mapping[str, Any],
    vice: Mapping[str, Any],
    *,
    downside_weight: float,
    upside_weight: float,
) -> dict[str, Any]:
    captain_downside = _f(captain.get("expected_shortfall"))
    captain_upside = _f(captain.get("expected_excess_ge_8"))
    captain_utility = (
        _f(captain.get("xpts_mean"))
        - downside_weight * captain_downside
        + upside_weight * captain_upside
    )
    p_cap_dnp = _f(captain.get("p_dnp"))
    vice_mean_fallback = p_cap_dnp * _f(vice.get("xpts_mean"))
    vice_downside = p_cap_dnp * _f(vice.get("expected_shortfall"))
    vice_upside = p_cap_dnp * _f(vice.get("expected_excess_ge_8"))
    vice_utility = (
        vice_mean_fallback
        - downside_weight * vice_downside
        + upside_weight * vice_upside
    )
    takeover_probability = p_cap_dnp * _f(vice.get("p_appearance"))
    joint_failure = p_cap_dnp * _f(vice.get("p_dnp"))
    return {
        "captain_element": int(captain.get("element") or 0),
        "vice_element": int(vice.get("element") or 0),
        "captain_name": captain.get("name"),
        "vice_name": vice.get("name"),
        "pair_utility": round(captain_utility + vice_utility, 6),
        "expected_captain_multiplier_value": round(_f(captain.get("xpts_mean")), 6),
        "expected_vice_takeover_value": round(vice_mean_fallback, 6),
        "vice_takeover_probability": round(takeover_probability, 9),
        "joint_dnp_failure_probability": round(joint_failure, 9),
        "joint_downside": round(captain_downside + vice_downside, 6),
        "joint_upside": round(captain_upside + vice_upside, 6),
        "captain_cameo_blocks_vice": True,
        "captain_late_cameo_blocks_vice": True,
        "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
        "dependence_assumption": "CAPTAIN_DNP_AND_VICE_OUTCOME_INDEPENDENCE_APPROXIMATION",
    }


def _captain_pair_sort_key(
    row: Mapping[str, Any],
) -> tuple[float, float, float, float, float]:
    return (
        _f(row.get("pair_utility")),
        _f(row.get("expected_captain_multiplier_value")),
        _f(row.get("joint_upside")),
        -_f(row.get("joint_downside")),
        _f(row.get("expected_vice_takeover_value")),
    )


def evaluate_captain_vice_pairs(starters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    cfg = load_config()
    objective = dict(cfg.get("objective") or {})
    downside_weight = _f(objective.get("captain_downside_weight"), 0.15)
    upside_weight = _f(objective.get("captain_upside_weight"), 0.10)
    pairs = [
        _captain_vice_pair_row(
            captain,
            vice,
            downside_weight=downside_weight,
            upside_weight=upside_weight,
        )
        for captain in starters
        for vice in starters
        if int(vice.get("element") or -1) != int(captain.get("element") or -1)
    ]
    pairs.sort(key=_captain_pair_sort_key, reverse=True)
    return pairs


def _best_captain_vice_pair(
    starters: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Exact best ordered pair without materializing/sorting all 110 rows."""
    cfg = load_config()
    objective = dict(cfg.get("objective") or {})
    downside_weight = _f(objective.get("captain_downside_weight"), 0.15)
    upside_weight = _f(objective.get("captain_upside_weight"), 0.10)
    prepared = []
    for row in starters:
        mean = _f(row.get("xpts_mean"))
        downside = _f(row.get("expected_shortfall"))
        upside = _f(row.get("expected_excess_ge_8"))
        base = mean - downside_weight * downside + upside_weight * upside
        prepared.append((row, mean, downside, upside, base))

    best_pair: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None
    best_key: tuple[float, float, float, float, float] | None = None
    for captain, cap_mean, cap_downside, cap_upside, cap_base in prepared:
        p_cap_dnp = _f(captain.get("p_dnp"))
        for vice, vice_mean, vice_downside_base, vice_upside_base, vice_base in prepared:
            if int(vice.get("element") or -1) == int(captain.get("element") or -1):
                continue
            key = (
                round(cap_base + p_cap_dnp * vice_base, 6),
                round(cap_mean, 6),
                round(cap_upside + p_cap_dnp * vice_upside_base, 6),
                -round(cap_downside + p_cap_dnp * vice_downside_base, 6),
                round(p_cap_dnp * vice_mean, 6),
            )
            if best_key is None or key > best_key:
                best_key = key
                best_pair = (captain, vice)
    if best_pair is None:
        raise LineupOptimizerError("no legal captain/vice pair")
    return _captain_vice_pair_row(
        best_pair[0],
        best_pair[1],
        downside_weight=downside_weight,
        upside_weight=upside_weight,
    )


def _lineup_route(
    players: Sequence[Mapping[str, Any]],
    xi_indices: Sequence[int],
    *,
    compact: bool = False,
) -> dict[str, Any]:
    cfg = load_config()
    objective = dict(cfg.get("objective") or {})
    starters = [players[index] for index in xi_indices]
    formation = _formation(starters)
    if not formation:
        raise LineupOptimizerError("illegal XI entered route evaluation")
    starter_ids = {int(row.get("element") or 0) for row in starters}
    bench = [
        row for row in players
        if int(row.get("element") or 0) not in starter_ids
    ]
    reserve_gk_rows = [row for row in bench if row.get("position") == "GK"]
    outfield_bench = [row for row in bench if row.get("position") != "GK"]
    if len(reserve_gk_rows) != 1 or len(outfield_bench) != 3:
        raise LineupOptimizerError("legal XI must leave one reserve GK and three outfield substitutes")
    bench_best, bench_alternatives = optimize_bench_order(
        starters,
        reserve_gk_rows[0],
        outfield_bench,
        include_winner_blocking_counterfactual=not compact,
        publish_alternatives=not compact,
        include_winner_slots=not compact,
    )
    if compact:
        cvc = _best_captain_vice_pair(starters)
        cvc_pairs: list[dict[str, Any]] = []
    else:
        cvc_pairs = evaluate_captain_vice_pairs(starters)
        if not cvc_pairs:
            raise LineupOptimizerError("no legal captain/vice pair")
        cvc = cvc_pairs[0]

    expected_points = sum(_f(row.get("xpts_mean")) for row in starters)
    expected_shortfall = sum(_f(row.get("expected_shortfall")) for row in starters)
    expected_excess = sum(_f(row.get("expected_excess_ge_8")) for row in starters)
    base_distributional_utility = (
        expected_points
        - _f(objective.get("lineup_downside_weight"), 0.10) * expected_shortfall
        + _f(objective.get("lineup_upside_weight"), 0.05) * expected_excess
    )
    lineup_utility = base_distributional_utility + _f(bench_best.get("bench_order_utility"))
    route_utility = lineup_utility + _f(cvc.get("pair_utility"))
    variance = sum(_f(row.get("xpts_variance")) for row in starters)
    tactical_rows = [row.get("tactical_role") or {} for row in starters]
    tactical_scores = [_f(row.get("score")) for row in tactical_rows if row.get("score") is not None]
    tactical_weighted = [_f(row.get("weighted_component_points")) for row in tactical_rows if row.get("weighted_component_points") is not None]
    pmf_ready = sum(1 for row in starters if (row.get("distribution_status") or {}).get("status") == "READY")

    route: dict[str, Any] = {
        "formation": formation,
        "element_ids": sorted(starter_ids),
        "base_football_utility": round(base_distributional_utility, 6),
        "route_utility": round(route_utility, 6),
        "expected_fpl_points_before_captain": round(expected_points + _f(bench_best.get("expected_autosub_value")), 6),
        "expected_fpl_points_with_captain_vice": round(
            expected_points
            + _f(bench_best.get("expected_autosub_value"))
            + _f(cvc.get("expected_captain_multiplier_value"))
            + _f(cvc.get("expected_vice_takeover_value")),
            6,
        ),
        "distributional_downside": round(expected_shortfall, 6),
        "supportable_upside": round(expected_excess, 6),
        "aggregate_variance": round(variance, 6),
        "aggregate_std": round(math.sqrt(max(0.0, variance)), 6),
        "aggregate_variance_semantics": "SUM_OF_PLAYER_VARIANCES_ZERO_COVARIANCE_APPROXIMATION",
        "expected_autosub_value": bench_best.get("expected_autosub_value"),
        "expected_blocked_autosub_value": bench_best.get("expected_blocked_autosub_value"),
        "autosub_probability": bench_best.get("autosub_probability"),
        "blocked_autosub_probability": bench_best.get("blocked_autosub_probability"),
        "tactical_role_contribution": {
            "canonical_weight": 0.25,
            "mean_canonical_tactical_role_score": (
                round(sum(tactical_scores) / len(tactical_scores), 6) if tactical_scores else None
            ),
            "mean_weighted_component_points": (
                round(sum(tactical_weighted) / len(tactical_weighted), 6) if tactical_weighted else None
            ),
            "consumption": "READ_ONLY_TIE_BREAK_AND_EXPLAINABILITY",
            "formula_recomputed": False,
        },
        "uncertainty": {
            "pmf_ready_starters": pmf_ready,
            "pmf_total_starters": 11,
            "distribution_completeness": "FULL_P1_3B_SURFACE_FOR_XI" if pmf_ready == 11 else "PARTIAL",
            "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
        },
        "confidence": "HIGH" if pmf_ready == 11 else "MEDIUM" if pmf_ready >= 8 else "LOW",
        "robustness": {
            "mean_not_sole_objective": True,
            "distributional_downside_used": True,
            "supportable_upside_used": True,
            "autosub_option_value_used": True,
            "cameo_blocking_explicit": True,
        },
    }
    if compact:
        route.update({
            "_xi_indices": tuple(int(index) for index in xi_indices),
            "_bench_order": tuple(int(value) for value in bench_best.get("order") or []),
            "_captain_element": int(cvc.get("captain_element") or 0),
            "_vice_element": int(cvc.get("vice_element") or 0),
        })
        return route
    route.update({
        "starters": starters,
        "bench": bench_best,
        "bench_alternatives": bench_alternatives,
        "captain_vice": cvc,
        "captain_vice_alternatives": cvc_pairs[: min(20, len(cvc_pairs))],
    })
    return route


def _route_sort_key(route: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    tactical = dict(route.get("tactical_role_contribution") or {})
    return (
        _f(route.get("route_utility")),
        _f(route.get("expected_fpl_points_with_captain_vice")),
        -_f(route.get("distributional_downside")),
        _f(route.get("supportable_upside")),
        _f(tactical.get("mean_weighted_component_points")),
    )


def _compact_public_route(
    route: Mapping[str, Any],
    *,
    selected_utility: float,
) -> dict[str, Any]:
    """Publish an exact ranked route summary without re-running full explainability.

    The compact pass already evaluates the same legal XI, all six bench orders,
    and the exact winning ordered captain/vice pair. This helper only omits
    publish-only slot/counterfactual detail for non-selected routes.
    """
    public = {
        key: deepcopy(value)
        for key, value in route.items()
        if not str(key).startswith("_")
    }
    public["bench"] = {
        "order": list(route.get("_bench_order") or ()),
        "slots": [],
        "materialization_status": "EXACT_COMPACT_WINNER_SUMMARY",
    }
    public["captain_vice"] = {
        "captain_element": int(route.get("_captain_element") or 0),
        "vice_element": int(route.get("_vice_element") or 0),
        "materialization_status": "EXACT_COMPACT_WINNER_SUMMARY",
    }
    public["bench_alternatives"] = []
    public["captain_vice_alternatives"] = []
    public["expected_regret"] = round(
        max(0.0, float(selected_utility) - _f(route.get("route_utility"))),
        6,
    )
    public["expected_regret_semantics"] = "DECISION_UTILITY_OPPORTUNITY_GAP"
    public["publish_materialization_status"] = (
        "EXACT_RANKED_COMPACT_SUMMARY_NO_RECOMPUTE"
    )
    return public


def _decision_core(players: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    legal = enumerate_legal_xi(players)
    compact_routes = [_lineup_route(players, indices, compact=True) for indices in legal]
    compact_routes.sort(key=_route_sort_key, reverse=True)
    if not compact_routes:
        raise LineupOptimizerError("no legal P1.7 route")

    compact_best_by_formation: dict[str, dict[str, Any]] = {}
    for route in compact_routes:
        formation = str(route.get("formation"))
        if formation not in compact_best_by_formation:
            compact_best_by_formation[formation] = route

    materialized: dict[tuple[int, ...], dict[str, Any]] = {}

    def full_route(compact_route: Mapping[str, Any]) -> dict[str, Any]:
        key = tuple(int(value) for value in compact_route.get("_xi_indices") or ())
        if len(key) != 11:
            raise LineupOptimizerError("compact P1.7 route lost XI identity")
        if key not in materialized:
            detailed = _lineup_route(players, key, compact=False)
            compact_key = _route_sort_key(compact_route)
            detailed_key = _route_sort_key(detailed)
            if any(
                not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                for left, right in zip(compact_key, detailed_key)
            ):
                raise LineupOptimizerError(
                    "compact P1.7 route score diverged from exact materialized route"
                )
            if tuple(int(value) for value in (detailed.get("bench") or {}).get("order") or ()) != tuple(compact_route.get("_bench_order") or ()):
                raise LineupOptimizerError(
                    "compact P1.7 bench winner diverged during materialization"
                )
            pair = dict(detailed.get("captain_vice") or {})
            if (
                int(pair.get("captain_element") or 0) != int(compact_route.get("_captain_element") or 0)
                or int(pair.get("vice_element") or 0) != int(compact_route.get("_vice_element") or 0)
            ):
                raise LineupOptimizerError(
                    "compact P1.7 C/VC winner diverged during materialization"
                )
            materialized[key] = detailed
        return materialized[key]

    published_compact = compact_routes[:12]
    selected = full_route(published_compact[0])
    alternative = (
        full_route(published_compact[1])
        if len(published_compact) > 1
        else None
    )
    published_routes: list[dict[str, Any]] = [selected]
    if alternative is not None:
        published_routes.append(alternative)
    selected_utility = _f(selected.get("route_utility"))
    for route in published_compact[len(published_routes):]:
        published_routes.append(
            _compact_public_route(
                route,
                selected_utility=selected_utility,
            )
        )

    materialized_by_indices = {
        tuple(int(value) for value in route.get("_xi_indices") or ()): row
        for route, row in (
            (published_compact[0], selected),
            *(
                [(published_compact[1], alternative)]
                if alternative is not None and len(published_compact) > 1
                else []
            ),
        )
        if row is not None
    }
    formation_comparison = []
    for formation, compact_row in sorted(compact_best_by_formation.items()):
        key = tuple(
            int(value) for value in compact_row.get("_xi_indices") or ()
        )
        detailed = materialized_by_indices.get(key)
        formation_comparison.append({
            "formation": formation,
            "element_ids": list(compact_row.get("element_ids") or []),
            "route_utility": compact_row.get("route_utility"),
            "expected_fpl_points_with_captain_vice": compact_row.get(
                "expected_fpl_points_with_captain_vice"
            ),
            "distributional_downside": compact_row.get(
                "distributional_downside"
            ),
            "supportable_upside": compact_row.get("supportable_upside"),
            "expected_autosub_value": compact_row.get(
                "expected_autosub_value"
            ),
            "cameo_blocking_cost": (
                detailed.get("expected_blocked_autosub_value")
                if detailed is not None
                else None
            ),
            "cameo_blocking_cost_status": (
                "MATERIALIZED_SELECTED_OR_BEST_ALTERNATIVE"
                if detailed is not None
                else "NOT_REMATERIALIZED_FORMATION_SUMMARY"
            ),
            "selected": formation == selected.get("formation"),
            "ranking_source": "EXACT_COMPACT_ROUTE",
        })
    if alternative:
        delta_utility = _f(selected.get("route_utility")) - _f(alternative.get("route_utility"))
        selected_ids = set(int(x) for x in selected.get("element_ids") or [])
        alternative_ids = set(int(x) for x in alternative.get("element_ids") or [])
        player_by_id = {int(row.get("element") or 0): row for row in players}
        proof = {
            "status": "CLOSE" if delta_utility <= _f((load_config().get("objective") or {}).get("close_call_utility_delta"), 0.35) else "CLEAR",
            "margin": round(delta_utility, 6),
            "selected_xi": selected.get("element_ids"),
            "best_alternative_xi": alternative.get("element_ids"),
            "starter_side": [
                {
                    "element": player_by_id[element].get("element"),
                    "name": player_by_id[element].get("name"),
                    "position": player_by_id[element].get("position"),
                    "selection_score": player_by_id[element].get("distributional_utility"),
                }
                for element in sorted(selected_ids - alternative_ids)
                if element in player_by_id
            ],
            "bench_side": [
                {
                    "element": player_by_id[element].get("element"),
                    "name": player_by_id[element].get("name"),
                    "position": player_by_id[element].get("position"),
                    "selection_score": player_by_id[element].get("distributional_utility"),
                }
                for element in sorted(alternative_ids - selected_ids)
                if element in player_by_id
            ],
            "alternative_formation": alternative.get("formation"),
            "delta_expected_utility": round(delta_utility, 6),
            "delta_mean": round(_f(selected.get("expected_fpl_points_with_captain_vice")) - _f(alternative.get("expected_fpl_points_with_captain_vice")), 6),
            "delta_downside": round(_f(selected.get("distributional_downside")) - _f(alternative.get("distributional_downside")), 6),
            "delta_upside": round(_f(selected.get("supportable_upside")) - _f(alternative.get("supportable_upside")), 6),
            "delta_autosub_value": round(_f(selected.get("expected_autosub_value")) - _f(alternative.get("expected_autosub_value")), 6),
            "delta_cameo_block_risk": round(_f(selected.get("expected_blocked_autosub_value")) - _f(alternative.get("expected_blocked_autosub_value")), 6),
            "delta_tactical_component": round(
                _f((selected.get("tactical_role_contribution") or {}).get("mean_weighted_component_points"))
                - _f((alternative.get("tactical_role_contribution") or {}).get("mean_weighted_component_points")),
                6,
            ),
            "expected_regret_delta": round(max(0.0, _f(selected.get("route_utility")) - _f(alternative.get("route_utility"))), 6),
            "expected_regret_semantics": "DECISION_UTILITY_OPPORTUNITY_GAP_NOT_COVARIANCE_AWARE_OUTCOME_REGRET",
            "reversal_triggers": [
                "fresh P1.1 availability/state probabilities erase delta_expected_utility",
                "fresh P1.3 point distribution changes downside/upside enough to erase delta_expected_utility",
                "fresh P1.6 canonical tactical-role evidence changes final tie-break after distributional utility convergence",
            ],
        }
    else:
        proof = {"status": "NO_ALTERNATIVE", "selected_xi": selected.get("element_ids")}
    for route in published_routes:
        route["expected_regret"] = round(max(0.0, _f(selected.get("route_utility")) - _f(route.get("route_utility"))), 6)
        route["expected_regret_semantics"] = "DECISION_UTILITY_OPPORTUNITY_GAP"
    return {
        "selected": selected,
        "best_alternative": alternative,
        "formation_comparison": formation_comparison,
        "close_call_proof": proof,
        "alternatives": published_routes,
        "legal_xi_count": len(legal),
        "legal_formations_evaluated": sorted(compact_best_by_formation),
        "materialization_governance": {
            "all_legal_routes_ranked_exactly": True,
            "selected_route_fully_materialized": True,
            "best_alternative_fully_materialized": alternative is not None,
            "other_published_routes": "EXACT_COMPACT_WINNER_SUMMARY",
            "formation_comparison_source": "EXACT_COMPACT_ROUTE",
            "route_pruning_applied": False,
            "route_utility_changed": False,
        },
    }


def _canonical_sha256() -> str:
    return hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()


def _model_evidence_binding(
    *,
    projections: Mapping[str, Any],
    squad_ids: Sequence[int],
    planning_gw: int,
    deterministic_output: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    cfg = load_config()
    projection_timestamp = str(projections.get("generated_at") or generated_at)
    projection_fingerprint = fingerprint({
        "planning_gw": planning_gw,
        "players": [
            {
                "element": row.get("element"),
                "xmins": row.get("xmins"),
                "xpts_by_gw": row.get("xpts_by_gw"),
                "tactical_role_component": row.get("tactical_role_component"),
            }
            for row in projections.get("players") or []
            if int(row.get("element") or -1) in set(int(x) for x in squad_ids)
        ],
    })
    snapshot_id = f"p1.7:{projection_fingerprint[:20]}"
    binding = build_model_run_binding(
        input_snapshot_id=snapshot_id,
        factual_snapshot_timestamps={"projections_generated_at": projection_timestamp},
        factual_artifact_fingerprints={"projections_subset": projection_fingerprint},
        deterministic_factual_inputs={
            "planning_gw": planning_gw,
            "owned_elements": sorted(int(x) for x in squad_ids),
            "projections_subset_fingerprint": projection_fingerprint,
        },
        model_version=str(cfg.get("model_version")),
        feature_version=str(cfg.get("feature_version")),
        parameter_version=str(cfg.get("parameter_version")),
        parameters={
            "objective": cfg.get("objective"),
            "autosub": cfg.get("autosub"),
            "covariance": cfg.get("covariance"),
        },
        calibration_version=str(cfg.get("calibration_version")),
        calibration_cutoff=cfg.get("calibration_cutoff"),
        calibration_parameters={
            "parameter_manifest": cfg.get("parameter_manifest"),
            "automatic_retuning": False,
            "settled_lineup_sample_size": 0,
        },
        generated_at=generated_at,
        planning_gw=planning_gw,
        canonical_v12_revision=_canonical_sha256(),
    )
    bound = bind_deterministic_output(binding, deterministic_output)
    return {
        "authority": False,
        **binding,
        "output_fingerprint": bound["output_fingerprint"],
        "raw_v6_payload_duplicated": False,
        "repository_python_execution_claimed": False,
    }


def optimize_lineup(
    projections: Mapping[str, Any],
    squad_ids: Sequence[int],
    *,
    planning_gw: int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    generated = generated_at or _now()
    gw = int(planning_gw or projections.get("planning_gw") or 1)
    pmap = {int(row.get("element") or -1): row for row in projections.get("players") or []}
    ids = [int(x) for x in squad_ids]
    if len(ids) != 15 or len(set(ids)) != 15:
        raise LineupOptimizerError("P1.7 squad must contain 15 unique elements")
    missing = [element for element in ids if element not in pmap]
    if missing:
        raise LineupOptimizerError(f"P1.7 missing projections for owned elements: {missing}")
    players = [build_player_surface(pmap[element], gw) for element in ids]
    core = _decision_core(players)
    selected = core["selected"]
    captain_id = int((selected.get("captain_vice") or {}).get("captain_element") or 0)
    vice_id = int((selected.get("captain_vice") or {}).get("vice_element") or 0)
    by_id = {int(row.get("element") or 0): row for row in players}
    output_core = {
        "model": "governed_lineup_v2",
        "native_model": cfg.get("model_id"),
        "model_owner": MODEL_OWNER,
        "ruleset_id": RULESET_ID,
        "planning_gw": gw,
        "formation": selected.get("formation"),
        "squad_rows": players,
        "starting_xi": selected.get("starters"),
        "captain": {
            **{k: v for k, v in by_id[captain_id].items() if k != "point_distribution"},
            "captain_score": (selected.get("captain_vice") or {}).get("pair_utility"),
            "vice_score": (selected.get("captain_vice") or {}).get("expected_vice_takeover_value"),
            "pair": selected.get("captain_vice"),
        },
        "vice_captain": {
            **{k: v for k, v in by_id[vice_id].items() if k != "point_distribution"},
            "captain_score": (selected.get("captain_vice") or {}).get("pair_utility"),
            "vice_score": (selected.get("captain_vice") or {}).get("expected_vice_takeover_value"),
            "pair": selected.get("captain_vice"),
        },
        "captain_safe_pool": [],
        "bench": {
            "gk": selected.get("bench", {}).get("reserve_gk"),
            "order": selected.get("bench", {}).get("slots"),
            "distributional_evaluation": selected.get("bench"),
            "close_battles": [],
        },
        "lineup_score": {
            "robust": selected.get("route_utility"),
            "base_robust": selected.get("base_football_utility"),
            "xpts_mean": selected.get("expected_fpl_points_before_captain"),
            "xpts_std": selected.get("aggregate_std"),
            "distributional_downside": selected.get("distributional_downside"),
            "supportable_upside": selected.get("supportable_upside"),
            "expected_autosub_value": selected.get("expected_autosub_value"),
            "cameo_blocking_cost": selected.get("expected_blocked_autosub_value"),
            "captain_multiplier_value": (selected.get("captain_vice") or {}).get("expected_captain_multiplier_value"),
            "vice_fallback_value": (selected.get("captain_vice") or {}).get("expected_vice_takeover_value"),
            "expected_regret": 0.0,
            "risk_adjustment": {
                "method": "P1_7_DISTRIBUTIONAL_UTILITY",
                "adjustment": round(
                    _f(selected.get("route_utility"))
                    - _f(selected.get("expected_fpl_points_with_captain_vice")),
                    6,
                ),
                "raw_xpts_mutated": False,
            },
            "confidence": selected.get("confidence"),
            "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
        },
        "main_starting_xi_battle": core.get("close_call_proof"),
        "formation_comparison": core.get("formation_comparison"),
        "alternatives": core.get("alternatives"),
        "legal_xi_count": core.get("legal_xi_count"),
        "legal_formations_evaluated": core.get("legal_formations_evaluated"),
        "materialization_governance": core.get("materialization_governance"),
        "governance": {
            "v12_native_owner": MODEL_OWNER,
            "all_legal_xi_enumerated": True,
            "global_autosub_resolver": True,
            "cameo_blocking_explicit": True,
            "bench_order_distributional": True,
            "reserve_gk_separate": True,
            "captain_vice_jointly_evaluated": True,
            "mean_xpts_is_not_sole_objective": True,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_6_canonical_weight": 0.25,
            "methodology_weights_20_25_30_25_unchanged": True,
            "covariance_status": "COVARIANCE_NOT_MODELLED_YET",
            "monte_carlo_applied": False,
            "package_optimizer_implemented": False,
            "mini_league_overlay_applied": False,
            "v6_mutated": False,
            "transfer_economics_consumed": False,
        },
    }
    seen_captains: set[int] = set()
    captain_pool: list[dict[str, Any]] = []

    # Compatibility surface only: health/report consumers historically expect
    # both selected C and VC in captain_safe_pool. This does not re-run or
    # override the joint distributional C/VC decision.
    selected_pair = dict(selected.get("captain_vice") or {})
    for required_element, required_role in (
        (captain_id, "SELECTED_CAPTAIN"),
        (vice_id, "SELECTED_VICE"),
    ):
        if required_element <= 0 or required_element in seen_captains:
            continue
        surface = by_id[required_element]
        captain_pool.append({
            "element": required_element,
            "name": surface.get("name"),
            "captain_score": (
                selected_pair.get("pair_utility")
                if required_role == "SELECTED_CAPTAIN"
                else surface.get("distributional_utility")
            ),
            "vice_score": (
                selected_pair.get("expected_vice_takeover_value")
                if required_role == "SELECTED_VICE"
                else 0.0
            ),
            "pair_utility": selected_pair.get("pair_utility"),
            "expected_captain_multiplier_value": (
                selected_pair.get("expected_captain_multiplier_value")
                if required_role == "SELECTED_CAPTAIN"
                else surface.get("xpts_mean")
            ),
            "expected_vice_takeover_value": (
                selected_pair.get("expected_vice_takeover_value")
                if required_role == "SELECTED_VICE"
                else 0.0
            ),
            "vice_takeover_probability": (
                selected_pair.get("vice_takeover_probability")
                if required_role == "SELECTED_VICE"
                else 0.0
            ),
            "compatibility_role": required_role,
        })
        seen_captains.add(required_element)

    for row in selected.get("captain_vice_alternatives") or []:
        element = int(row.get("captain_element") or 0)
        if element <= 0 or element in seen_captains:
            continue
        seen_captains.add(element)
        captain_pool.append({
            "element": element,
            "name": row.get("captain_name"),
            "captain_score": row.get("pair_utility"),
            "vice_score": row.get("expected_vice_takeover_value"),
            "pair_utility": row.get("pair_utility"),
            "expected_captain_multiplier_value": row.get("expected_captain_multiplier_value"),
            "expected_vice_takeover_value": row.get("expected_vice_takeover_value"),
            "vice_takeover_probability": row.get("vice_takeover_probability"),
        })
        if len(captain_pool) >= 5:
            break
    output_core["captain_safe_pool"] = captain_pool

    evidence = _model_evidence_binding(
        projections=projections,
        squad_ids=ids,
        planning_gw=gw,
        deterministic_output=output_core,
        generated_at=generated,
    )
    return {
        "generated_at": generated,
        **output_core,
        "model_evidence_binding": evidence,
    }


def compare_legacy_decision(
    legacy: Mapping[str, Any],
    native: Mapping[str, Any],
) -> dict[str, Any]:
    legacy_xi = {int(row.get("element") or 0) for row in legacy.get("starting_xi") or []}
    native_xi = {int(row.get("element") or 0) for row in native.get("starting_xi") or []}
    legacy_bench = [int(row.get("element") or 0) for row in (legacy.get("bench") or {}).get("order") or []]
    native_bench = [int(row.get("element") or 0) for row in (native.get("bench") or {}).get("order") or []]
    legacy_c = int((legacy.get("captain") or {}).get("element") or 0)
    native_c = int((native.get("captain") or {}).get("element") or 0)
    legacy_v = int((legacy.get("vice_captain") or {}).get("element") or 0)
    native_v = int((native.get("vice_captain") or {}).get("element") or 0)
    regressions: list[str] = []
    if len(native_xi) != 11 or _formation(native.get("starting_xi") or []) is None:
        regressions.append("NATIVE_XI_ILLEGAL")
    if not (native.get("bench") or {}).get("gk"):
        regressions.append("NATIVE_RESERVE_GK_MISSING")
    if native_c not in native_xi or native_v not in native_xi or native_c == native_v:
        regressions.append("NATIVE_CAPTAIN_VICE_ILLEGAL")
    legacy_xi_legal = len(legacy_xi) == 11 and _formation(legacy.get("starting_xi") or []) is not None
    legacy_reserve_gk = ((legacy.get("bench") or {}).get("gk") or {}).get("element")
    legacy_cvc_legal = (
        legacy_c in legacy_xi
        and legacy_v in legacy_xi
        and legacy_c != legacy_v
    )
    legacy_structurally_legal = bool(
        legacy_xi_legal and legacy_reserve_gk and legacy_cvc_legal
    )
    native_blocked_value = _f(
        (((native.get("bench") or {}).get("distributional_evaluation") or {}).get(
            "expected_blocked_autosub_value"
        ))
    )

    if regressions:
        classification = "UNEXPECTED_REGRESSION"
    elif not legacy_structurally_legal:
        classification = "BUG_FIX"
    elif legacy_xi == native_xi and legacy_bench == native_bench and legacy_c == native_c and legacy_v == native_v:
        classification = "EXACT_EQUIVALENT"
    elif legacy_xi != native_xi:
        classification = "DISTRIBUTIONAL_IMPROVEMENT"
    elif legacy_bench != native_bench:
        classification = (
            "CAMEO_BLOCKING_IMPROVEMENT"
            if native_blocked_value > 0.0
            else "AUTOSUB_OPTION_VALUE_IMPROVEMENT"
        )
    elif legacy_c != native_c or legacy_v != native_v:
        classification = "CAPTAIN_FALLBACK_IMPROVEMENT"
    else:
        classification = "AUTOSUB_OPTION_VALUE_IMPROVEMENT"
    return {
        "classification": classification,
        "unexpected_regressions": regressions,
        "unexpected_regression_count": len(regressions),
        "legacy": {
            "formation": legacy.get("formation"),
            "xi": sorted(legacy_xi),
            "bench_order": legacy_bench,
            "captain": legacy_c,
            "vice": legacy_v,
        },
        "native": {
            "formation": native.get("formation"),
            "xi": sorted(native_xi),
            "bench_order": native_bench,
            "captain": native_c,
            "vice": native_v,
        },
        "ownership_migration_blocked": bool(regressions),
        "classification_taxonomy": [
            "EXACT_EQUIVALENT",
            "DISTRIBUTIONAL_IMPROVEMENT",
            "AUTOSUB_OPTION_VALUE_IMPROVEMENT",
            "CAMEO_BLOCKING_IMPROVEMENT",
            "CAPTAIN_FALLBACK_IMPROVEMENT",
            "BUG_FIX",
            "UNEXPECTED_REGRESSION",
        ],
    }


def freeze_lineup_decision(
    decision: Mapping[str, Any],
    *,
    deadline_time: Any,
    frozen_at: Any,
    existing_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    binding = dict(decision.get("model_evidence_binding") or {})
    players = []
    frozen_player_rows = decision.get("squad_rows") or decision.get("player_surfaces") or []
    for row in frozen_player_rows:
        players.append({
            "element": row.get("element"),
            "xpts": row.get("xpts_mean"),
            "xmins": row.get("xmins"),
            "start_probability": row.get("p_start"),
            "dnp_probability": row.get("p_dnp"),
            "projection_confidence": row.get("confidence"),
            "p_fpl_blank": row.get("p_fpl_blank"),
            "point_tails": {
                "ge_8": row.get("p_points_ge_8"),
                "ge_10": row.get("p_points_ge_10"),
            },
        })
    alternatives_considered = []
    for route in decision.get("alternatives") or []:
        pair = dict(route.get("captain_vice") or {})
        bench = dict(route.get("bench") or {})
        alternatives_considered.append({
            "formation": route.get("formation"),
            "xi": list(route.get("element_ids") or []),
            "route_utility": route.get("route_utility"),
            "expected_fpl_points_with_captain_vice": route.get(
                "expected_fpl_points_with_captain_vice"
            ),
            "expected_autosub_value": route.get("expected_autosub_value"),
            "cameo_blocking_cost": route.get("expected_blocked_autosub_value"),
            "bench_order": list(bench.get("order") or []),
            "captain": pair.get("captain_element"),
            "vice_captain": pair.get("vice_element"),
        })

    decision_snapshot = {
        "captured_at": decision.get("generated_at"),
        "decision_kind": "P1.7_XI_BENCH_CAPTAIN_VICE",
        "formation": decision.get("formation"),
        "xi": [row.get("element") for row in decision.get("starting_xi") or []],
        "bench_gk": ((decision.get("bench") or {}).get("gk") or {}).get("element"),
        "bench_order": [row.get("element") for row in (decision.get("bench") or {}).get("order") or []],
        "captain": (decision.get("captain") or {}).get("element"),
        "vice_captain": (decision.get("vice_captain") or {}).get("element"),
        "selected_route_summary": deepcopy(decision.get("lineup_score")),
        "main_starting_xi_battle": deepcopy(decision.get("main_starting_xi_battle")),
        "formation_comparison": deepcopy(decision.get("formation_comparison")),
        "alternatives_considered": alternatives_considered,
        "migration_comparison": deepcopy(decision.get("migration_comparison")),
        "model_evidence_output_fingerprint": binding.get("output_fingerprint"),
    }
    return freeze_prediction(
        model_binding=binding,
        deadline_time=deadline_time,
        forecast_generated_at=decision.get("generated_at"),
        frozen_at=frozen_at,
        forecast_rows=players,
        decision_snapshot=decision_snapshot,
        existing_record=existing_record,
    )


def settle_lineup_decision(
    frozen_record: Mapping[str, Any],
    *,
    actual_rows: Sequence[Mapping[str, Any]],
    decision_outcome_evidence: Mapping[str, Any],
    event_finished: bool,
    settled_at: Any,
) -> dict[str, Any]:
    return settle_frozen_record(
        frozen_record,
        actual_rows=actual_rows,
        decision_outcome_evidence=decision_outcome_evidence,
        event_finished=event_finished,
        settled_at=settled_at,
    )
