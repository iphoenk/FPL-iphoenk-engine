from __future__ import annotations

"""Shared-world captain/vice simulation and goalkeeper event calibration.

This module is an adapter over canonical P1.3B point PMFs. It does not create
an alternative points model. A simulation is available only when every
candidate has a complete PMF and every goalkeeper candidate has an auditable
event calibration payload.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np


MC_PATHS = 500_000
DEFAULT_SEED = 120910
GK_REQUIRED = (
    "clean_sheet_probability",
    "conceded_goals",
    "saves",
    "bonus_probability",
    "penalty_save_probability",
    "appearance_probability",
)
GK_PROVENANCE_REQUIRED = (
    "source_id",
    "dataset_id",
    "calibration_version",
    "evidence_cutoff_at",
)


@dataclass(frozen=True)
class Validation:
    available: bool
    errors: tuple[str, ...]


def _probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 1.0 else None


def validate_goalkeeper_event_calibration(
    calibration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate event probabilities without inventing missing GK events."""
    payload = dict(calibration or {})
    errors: list[str] = []
    for field in GK_REQUIRED:
        if field not in payload:
            errors.append(f"MISSING_{field.upper()}")
    provenance = dict(payload.get("provenance") or {})
    for field in GK_PROVENANCE_REQUIRED:
        if not provenance.get(field):
            errors.append(f"MISSING_PROVENANCE_{field.upper()}")

    scalar_fields = (
        "clean_sheet_probability",
        "bonus_probability",
        "penalty_save_probability",
        "appearance_probability",
    )
    for field in scalar_fields:
        if field in payload and _probability(payload[field]) is None:
            errors.append(f"INVALID_{field.upper()}")

    conceded = dict(payload.get("conceded_goals") or {})
    if conceded:
        total = 0.0
        for key in ("0", "1", "2", "3_plus"):
            value = _probability(conceded.get(key))
            if value is None:
                errors.append(f"INVALID_CONCEDED_{key.upper()}")
            else:
                total += value
        if abs(total - 1.0) > 1e-6:
            errors.append("CONCEDED_GOALS_NOT_NORMALIZED")

    saves = dict(payload.get("saves") or {})
    if saves:
        total = 0.0
        for key, value in saves.items():
            probability = _probability(value)
            if probability is None:
                errors.append(f"INVALID_SAVES_{key}")
            else:
                total += probability
        if abs(total - 1.0) > 1e-6:
            errors.append("SAVES_NOT_NORMALIZED")

    if "clean_sheet_probability" in payload and conceded.get("0") is not None:
        clean_sheet = _probability(payload["clean_sheet_probability"])
        conceded_zero = _probability(conceded["0"])
        if clean_sheet is not None and conceded_zero is not None:
            if abs(clean_sheet - conceded_zero) > 1e-6:
                errors.append("CLEAN_SHEET_MUST_MATCH_CONCEDED_ZERO")

    return {
        "available": not errors,
        "errors": errors,
        "status": "AVAILABLE" if not errors else "UNAVAILABLE",
        "calibration_version": provenance.get("calibration_version"),
        "evidence_cutoff_at": provenance.get("evidence_cutoff_at"),
        "source_id": provenance.get("source_id"),
        "dataset_id": provenance.get("dataset_id"),
    }


def _pmf(candidate: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray] | None:
    distribution = dict(candidate.get("point_distribution") or {})
    raw = distribution.get("probabilities")
    if not isinstance(raw, Mapping) or not raw:
        return None
    pairs: list[tuple[float, float]] = []
    for points, probability in raw.items():
        try:
            x = float(points)
            p = float(probability)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(x) or not np.isfinite(p) or p < 0.0:
            return None
        pairs.append((x, p))
    pairs.sort()
    probabilities = np.asarray([p for _, p in pairs], dtype=float)
    total = float(probabilities.sum())
    if total <= 0.0:
        return None
    probabilities /= total
    return (
        np.asarray([x for x, _ in pairs], dtype=float),
        np.cumsum(probabilities),
    )


def _sample(
    candidate: Mapping[str, Any],
    world_u: np.ndarray,
    appearance_u: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    pmf = _pmf(candidate)
    if pmf is None:
        return None
    points, cumulative = pmf
    sampled = points[np.searchsorted(cumulative, world_u, side="right").clip(0, len(points) - 1)]
    try:
        p_dnp = float(candidate.get("p_dnp"))
    except (TypeError, ValueError):
        p_dnp = -1.0
    if not 0.0 <= p_dnp <= 1.0:
        return None
    dnp = appearance_u < p_dnp
    return np.where(dnp, 0.0, sampled), dnp


def _quantile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q, method="linear"))


def simulate_shared_world_cvc(
    candidates: Sequence[Mapping[str, Any]],
    *,
    captain_id: int,
    vice_captain_id: int,
    paths: int = MC_PATHS,
    seed: int = DEFAULT_SEED,
    mini_league_entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one deterministic shared world for C/VC and optional mini-league ranks."""
    if paths != MC_PATHS:
        raise ValueError(f"MC_PATHS must remain exactly {MC_PATHS}")
    by_id = {
        int(row.get("element_id", row.get("element"))): row
        for row in candidates
        if row.get("element_id", row.get("element")) is not None
    }
    if captain_id not in by_id or vice_captain_id not in by_id:
        return {"status": "UNAVAILABLE", "reason": "CAPTAIN_OR_VICE_NOT_FOUND"}
    errors: list[str] = []
    for element_id, row in by_id.items():
        if _pmf(row) is None:
            errors.append(f"PMF_UNAVAILABLE_{element_id}")
        position = str(row.get("position") or "").upper()
        if position in {"GK", "GKP"}:
            result = validate_goalkeeper_event_calibration(
                row.get("goalkeeper_event_calibration")
            )
            if not result["available"]:
                errors.extend(f"GK_{error}_{element_id}" for error in result["errors"])
    if errors:
        return {
            "status": "UNAVAILABLE",
            "reason": "CALIBRATION_OR_CANONICAL_PMF_INCOMPLETE",
            "errors": errors,
            "paths": MC_PATHS,
        }

    rng = np.random.default_rng(seed)
    world_u = rng.random(MC_PATHS)
    appearance_u = {
        element_id: rng.random(MC_PATHS) for element_id in by_id
    }
    sampled: dict[int, np.ndarray] = {}
    dnp: dict[int, np.ndarray] = {}
    for element_id, row in by_id.items():
        result = _sample(row, world_u, appearance_u[element_id])
        if result is None:
            return {
                "status": "UNAVAILABLE",
                "reason": f"INVALID_CANDIDATE_{element_id}",
                "paths": MC_PATHS,
            }
        sampled[element_id], dnp[element_id] = result

    captain = sampled[captain_id]
    vice = sampled[vice_captain_id]
    captain_dnp = dnp[captain_id]
    cvc = np.where(captain_dnp, vice, captain)
    winner_matrix = np.vstack([sampled[element_id] for element_id in by_id])
    winner_indexes = np.argmax(winner_matrix, axis=0)
    element_ids = list(by_id)
    winner_ids = np.asarray([element_ids[index] for index in winner_indexes])
    winner_probability = {
        str(element_id): round(float(np.mean(winner_ids == element_id)), 9)
        for element_id in element_ids
    }
    candidate_summary = {
        str(element_id): {
            "mean": round(float(np.mean(sampled[element_id])), 6),
            "q50": round(_quantile(sampled[element_id], 0.50), 6),
            "q75": round(_quantile(sampled[element_id], 0.75), 6),
            "q90": round(_quantile(sampled[element_id], 0.90), 6),
            "dnp_probability": round(float(np.mean(dnp[element_id])), 9),
        }
        for element_id in element_ids
    }
    captain_win = float(np.mean(winner_ids == captain_id))
    standard_error = float(np.sqrt(max(0.0, captain_win * (1.0 - captain_win) / MC_PATHS)))
    result: dict[str, Any] = {
        "status": "AVAILABLE",
        "paths": MC_PATHS,
        "seed": int(seed),
        "shared_world": True,
        "world_uniform_shared_across_candidates": True,
        "captain_id": captain_id,
        "vice_captain_id": vice_captain_id,
        "captain_winner_probability": round(captain_win, 9),
        "captain_winner_standard_error": round(standard_error, 9),
        "vice_activation_probability": round(float(np.mean(captain_dnp)), 9),
        "cvc_distribution": {
            "q50": round(_quantile(cvc, 0.50), 6),
            "q75": round(_quantile(cvc, 0.75), 6),
            "q90": round(_quantile(cvc, 0.90), 6),
            "mean": round(float(np.mean(cvc)), 6),
        },
        "candidate_distributions": candidate_summary,
        "winner_probability": winner_probability,
        "convergence": {
            "paths": MC_PATHS,
            "standard_error": round(standard_error, 9),
            "threshold": "EXISTING_V12_CONVERGENCE_GATE",
            "status": "AVAILABLE_FOR_EXISTING_GATE",
        },
        "provenance": {
            "source_ids": sorted({
                str((row.get("goalkeeper_event_calibration") or {})
                    .get("provenance", {}).get("source_id"))
                for row in by_id.values()
                if (row.get("goalkeeper_event_calibration") or {})
                .get("provenance", {}).get("source_id")
            }),
            "dataset_ids": sorted({
                str((row.get("goalkeeper_event_calibration") or {})
                    .get("provenance", {}).get("dataset_id"))
                for row in by_id.values()
                if (row.get("goalkeeper_event_calibration") or {})
                .get("provenance", {}).get("dataset_id")
            }),
            "evidence_cutoff_at": max(
                (
                    str((row.get("goalkeeper_event_calibration") or {})
                        .get("provenance", {}).get("evidence_cutoff_at"))
                    for row in by_id.values()
                    if (row.get("goalkeeper_event_calibration") or {})
                    .get("provenance", {}).get("evidence_cutoff_at")
                ),
                default=None,
            ),
        },
    }
    if mini_league_entries:
        result["mini_league"] = _simulate_mini_league_ranks(
            mini_league_entries, sampled, dnp, cvc
        )
    return result


def _simulate_mini_league_ranks(
    entries: Sequence[Mapping[str, Any]],
    sampled: Mapping[int, np.ndarray],
    dnp: Mapping[int, np.ndarray],
    cvc: np.ndarray,
) -> dict[str, Any]:
    rows = []
    for entry in entries:
        team_id = str(entry.get("team_id") or "")
        captain_id = int(entry.get("captain_id") or 0)
        vice_id = int(entry.get("vice_captain_id") or 0)
        base = float(entry.get("base_points") or 0.0)
        if captain_id not in sampled or vice_id not in sampled:
            return {"status": "UNAVAILABLE", "reason": f"TEAM_CVC_UNAVAILABLE_{team_id}"}
        team_total = base + np.where(dnp[captain_id], sampled[vice_id], sampled[captain_id])
        rows.append((team_id, team_total))
    if not rows:
        return {"status": "UNAVAILABLE", "reason": "NO_MINI_LEAGUE_ENTRIES"}
    totals = np.vstack([value for _, value in rows])
    ranks = 1 + np.sum(totals[:, None, :] < totals[None, :, :], axis=0)
    focal = rows[0][0]
    focal_rank = ranks[0]
    return {
        "status": "AVAILABLE",
        "focal_team_id": focal,
        "rank_q50": round(float(np.quantile(focal_rank, 0.50)), 6),
        "rank_q75": round(float(np.quantile(focal_rank, 0.75)), 6),
        "rank_q90": round(float(np.quantile(focal_rank, 0.90)), 6),
        "rank_mean": round(float(np.mean(focal_rank)), 6),
        "teams": len(rows),
        "shared_world": True,
    }
