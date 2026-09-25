from __future__ import annotations

"""Sample-aware defensive-contribution hit probability evidence.

This module is deliberately separate from the canonical P1.3 DEFCON owner.
It provides an A/B candidate evidence surface only.
"""

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.rules import DC_POINTS_CAP_PER_MATCH, DC_RULES, POSITION_TO_ELEMENT_TYPE

ROOT = Path(__file__).resolve().parents[2]
FEATURE_CONFIG = ROOT / "config" / "intelligence" / "player_features.json"


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _i(value: Any) -> int | None:
    value = _f(value)
    return None if value is None else int(value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    try:
        payload = json.loads(FEATURE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload.get("defensive_contribution") or {})


def _poisson_tail(threshold: int, expected_count: float) -> float:
    if threshold <= 0:
        return 1.0
    lam = max(0.0, float(expected_count))
    if lam <= 0.0:
        return 0.0
    term = math.exp(-lam)
    cumulative = term
    for count in range(1, threshold):
        term *= lam / count
        cumulative += term
    return _clamp(1.0 - cumulative, 0.0, 1.0)


def _position(row: Mapping[str, Any], fallback: str | None = None) -> str | None:
    raw = str(row.get("position") or fallback or "").upper().strip()
    return raw if raw in {"GK", "DEF", "MID", "FWD"} else None


def _rule(position: str) -> dict[str, Any]:
    element_type = POSITION_TO_ELEMENT_TYPE.get(position)
    return dict(DC_RULES.get(int(element_type or 0)) or {})


def defensive_actions(
    row: Mapping[str, Any],
    *,
    position: str | None = None,
) -> tuple[float | None, str | None]:
    """Return a non-fabricated per-match official-rule defensive count."""
    position = _position(row, position)
    if position == "GK":
        return None, "INELIGIBLE_POSITION"
    direct = _f(
        row.get("defensive_contribution")
        if row.get("defensive_contribution") is not None
        else row.get("defensive_contributions")
    )
    if direct is not None:
        return max(0.0, direct), "DIRECT_DEFENSIVE_CONTRIBUTION"

    cbi = _f(row.get("clearances_blocks_interceptions"))
    tackles = _f(row.get("tackles"))
    if cbi is None:
        clearances = _f(row.get("clearances"))
        blocks = _f(row.get("blocks"))
        interceptions = _f(row.get("interceptions"))
        if None not in (clearances, blocks, interceptions):
            cbi = float(clearances) + float(blocks) + float(interceptions)
    if cbi is None or tackles is None:
        return None, "MISSING_CBIT_COMPONENT"

    total = cbi + tackles
    if position in {"MID", "FWD"}:
        recoveries = _f(
            row.get("recoveries")
            if row.get("recoveries") is not None
            else row.get("ball_recoveries")
        )
        if recoveries is None:
            return None, "MISSING_RECOVERIES_FOR_CBIRT"
        total += recoveries
    return max(0.0, total), "RECONSTRUCTED_OFFICIAL_RULE_COMPONENTS"


def _measurable_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    position: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows:
        minutes = _f(raw.get("minutes"))
        if minutes is None:
            minutes = _f(raw.get("minutes_played"))
        if minutes is None or minutes <= 0.0:
            continue
        count, source = defensive_actions(raw, position=position)
        if count is None:
            continue
        row = dict(raw)
        row["_dc_minutes"] = minutes
        row["_dc_actions"] = count
        row["_dc_source"] = source
        out.append(row)
    out.sort(
        key=lambda row: (
            _i(row.get("gw")) or 0,
            str(row.get("match_id") or row.get("fixture") or ""),
        )
    )
    return out


def _rate(rows: Sequence[Mapping[str, Any]]) -> float | None:
    minutes = sum(float(row["_dc_minutes"]) for row in rows)
    if minutes <= 0.0:
        return None
    actions = sum(float(row["_dc_actions"]) for row in rows)
    return actions * 90.0 / minutes


def _starts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if bool(row.get("starter"))]


def _hit_rate(rows: Sequence[Mapping[str, Any]], threshold: int) -> float | None:
    if not rows:
        return None
    return sum(float(row["_dc_actions"]) >= threshold for row in rows) / len(rows)


def _confidence(eligible_starts: int, minutes: float) -> dict[str, Any]:
    if eligible_starts <= 0 or minutes <= 0:
        return {"label": "NONE", "score": 0.0}
    score = min(1.0, eligible_starts / 8.0) * min(1.0, minutes / 720.0)
    if eligible_starts < 3:
        label = "LOW"
    elif eligible_starts < 5 or minutes < 360:
        label = "DEVELOPING"
    elif eligible_starts < 8 or minutes < 720:
        label = "MODERATE"
    else:
        label = "HIGH"
    return {"label": label, "score": round(score, 4)}


def build_defcon_context(
    all_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build position priors and opponent-induced defensive workload."""
    by_position: dict[str, list[dict[str, Any]]] = {}
    by_opp_position: dict[tuple[int, str], list[dict[str, Any]]] = {}

    positions = ("DEF", "MID", "FWD")
    for position in positions:
        position_rows = [
            row for row in all_rows if _position(row) == position
        ]
        measured = _measurable_rows(position_rows, position=position)
        by_position[position] = measured
        for row in measured:
            opponent = _i(row.get("opponent_team_id") or row.get("opponent"))
            if opponent is not None and opponent > 0:
                by_opp_position.setdefault((opponent, position), []).append(row)

    position_priors: dict[str, Any] = {}
    for position, measured in by_position.items():
        rule = _rule(position)
        threshold = int(rule.get("threshold") or 0)
        starts = _starts(measured)
        position_priors[position] = {
            "sample_appearances": len(measured),
            "sample_starts": len(starts),
            "sample_minutes": round(
                sum(float(row["_dc_minutes"]) for row in measured), 1
            ),
            "def_actions_per90": (
                None if _rate(measured) is None else round(float(_rate(measured)), 6)
            ),
            "hit_rate": (
                None
                if _hit_rate(starts, threshold) is None
                else round(float(_hit_rate(starts, threshold)), 6)
            ),
        }

    opponent_workload: dict[str, Any] = {}
    for (opponent, position), measured in sorted(by_opp_position.items()):
        rate = _rate(measured)
        unique_matches = {
            (row.get("gw"), row.get("match_id") or row.get("fixture"))
            for row in measured
        }
        opponent_workload[f"{opponent}:{position}"] = {
            "opponent_team_id": opponent,
            "position": position,
            "def_actions_per90_induced": (
                None if rate is None else round(rate, 6)
            ),
            "sample_player_rows": len(measured),
            "sample_matches": len(unique_matches),
            "sample_minutes": round(
                sum(float(row["_dc_minutes"]) for row in measured), 1
            ),
        }

    return {
        "contract": "V12_DEFCON_CONTEXT_V1",
        "position_priors": position_priors,
        "opponent_workload": opponent_workload,
        "governance": {
            "official_ruleset_threshold_authority": True,
            "missing_action_components_not_zero_filled": True,
            "opponent_workload_is_derived_from_measured_actions": True,
        },
    }


def _venue_factor(
    starts: Sequence[Mapping[str, Any]],
    *,
    home: bool | None,
    season_rate: float,
) -> tuple[float, dict[str, Any]]:
    if home is None:
        return 1.0, {
            "status": "DEGRADED_UPCOMING_VENUE_UNAVAILABLE",
            "factor": 1.0,
            "sample_starts": 0,
            "rate_per90": None,
        }
    venue_rows = [row for row in starts if bool(row.get("home")) is bool(home)]
    venue_rate = _rate(venue_rows)
    if (
        len(venue_rows) < 2
        or venue_rate is None
        or season_rate <= 0.0
    ):
        return 1.0, {
            "status": "DEGRADED_INSUFFICIENT_VENUE_SAMPLE",
            "factor": 1.0,
            "sample_starts": len(venue_rows),
            "rate_per90": None if venue_rate is None else round(venue_rate, 6),
        }
    raw = venue_rate / season_rate
    weight = len(venue_rows) / (len(venue_rows) + 3.0)
    factor = 1.0 + weight * (raw - 1.0)
    factor = _clamp(factor, 0.75, 1.25)
    return factor, {
        "status": "APPLIED",
        "factor": round(factor, 6),
        "sample_starts": len(venue_rows),
        "rate_per90": round(venue_rate, 6),
    }


def _recent_factor(
    measured: Sequence[Mapping[str, Any]],
    season_rate: float,
) -> tuple[float, dict[str, Any]]:
    recent = list(measured)[-3:]
    recent_rate = _rate(recent)
    if len(recent) < 3 or recent_rate is None or season_rate <= 0.0:
        return 1.0, {
            "status": "DEGRADED_INSUFFICIENT_RECENT_SAMPLE",
            "factor": 1.0,
            "sample_appearances": len(recent),
            "recent_def_actions_per90": (
                None if recent_rate is None else round(recent_rate, 6)
            ),
        }
    raw = recent_rate / season_rate
    factor = _clamp(1.0 + 0.5 * (raw - 1.0), 0.75, 1.25)
    return factor, {
        "status": "APPLIED",
        "factor": round(factor, 6),
        "sample_appearances": len(recent),
        "recent_def_actions_per90": round(recent_rate, 6),
    }


def _opponent_factor(
    context: Mapping[str, Any] | None,
    *,
    opponent_team_id: int | None,
    position: str,
    position_rate: float | None,
) -> tuple[float, dict[str, Any]]:
    if context is None or opponent_team_id is None or position_rate is None or position_rate <= 0:
        return 1.0, {
            "status": "DEGRADED_OPPONENT_WORKLOAD_UNAVAILABLE",
            "factor": 1.0,
        }
    row = dict(
        (context.get("opponent_workload") or {}).get(
            f"{int(opponent_team_id)}:{position}"
        )
        or {}
    )
    sample_matches = int(row.get("sample_matches") or 0)
    opponent_rate = _f(row.get("def_actions_per90_induced"))
    if sample_matches < 3 or opponent_rate is None:
        return 1.0, {
            "status": "DEGRADED_INSUFFICIENT_OPPONENT_SAMPLE",
            "factor": 1.0,
            "sample_matches": sample_matches,
            "opponent_rate_per90": opponent_rate,
        }
    raw = opponent_rate / position_rate
    weight = sample_matches / (sample_matches + 4.0)
    factor = _clamp(1.0 + weight * (raw - 1.0), 0.75, 1.25)
    return factor, {
        "status": "APPLIED",
        "factor": round(factor, 6),
        "sample_matches": sample_matches,
        "opponent_rate_per90": round(opponent_rate, 6),
    }


def project_defcon_hit_probability(
    player_rows: Sequence[Mapping[str, Any]],
    *,
    position: str,
    xmins: float | None,
    home: bool | None,
    opponent_team_id: int | None = None,
    context: Mapping[str, Any] | None = None,
    role_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    position = str(position or "").upper()
    rule = _rule(position)
    threshold = _i(rule.get("threshold"))
    points = min(
        float(rule.get("points") or 0.0),
        float(DC_POINTS_CAP_PER_MATCH),
    )
    if not rule.get("eligible") or threshold is None:
        return {
            "contract": "V12_DEFCON_HIT_PROBABILITY_V1",
            "eligible": False,
            "position": position,
            "threshold": threshold,
            "points": points,
            "projected_hit_probability": 0.0,
            "DEFCON_EV": 0.0,
            "status": "INELIGIBLE_POSITION",
        }

    measured = _measurable_rows(player_rows, position=position)
    starts = _starts(measured)
    home_starts = [row for row in starts if bool(row.get("home"))]
    away_starts = [row for row in starts if not bool(row.get("home"))]
    minutes = sum(float(row["_dc_minutes"]) for row in measured)
    season_rate = _rate(measured)
    hits = sum(float(row["_dc_actions"]) >= threshold for row in starts)
    hit_rate = _hit_rate(starts, threshold)
    home_hit_rate = _hit_rate(home_starts, threshold)
    away_hit_rate = _hit_rate(away_starts, threshold)
    confidence = _confidence(len(starts), minutes)

    position_prior = dict(
        (context or {}).get("position_priors", {}).get(position) or {}
    )
    prior_rate = _f(position_prior.get("def_actions_per90"))
    prior_hit = _f(position_prior.get("hit_rate"))
    shrink_minutes = float(_policy().get("rate_shrinkage_minutes") or 450.0)

    if season_rate is None and prior_rate is None:
        return {
            "contract": "V12_DEFCON_HIT_PROBABILITY_V1",
            "eligible": True,
            "position": position,
            "threshold": threshold,
            "points": points,
            "status": "UNAVAILABLE_NO_MEASURABLE_DEFENSIVE_ACTIONS",
            "defcon_hits": hits,
            "eligible_starts": len(starts),
            "hit_rate": None if hit_rate is None else round(hit_rate, 6),
            "home_hit_rate": (
                None if home_hit_rate is None else round(home_hit_rate, 6)
            ),
            "away_hit_rate": (
                None if away_hit_rate is None else round(away_hit_rate, 6)
            ),
            "def_actions_per90": None,
            "sample_size": {
                "appearances": len(measured),
                "eligible_starts": len(starts),
                "minutes": round(minutes, 1),
            },
            "confidence": confidence,
            "projected_hit_probability": None,
            "DEFCON_EV": None,
        }

    if season_rate is None:
        posterior_rate = float(prior_rate)
        rate_source = "POSITION_PRIOR_ONLY"
    elif prior_rate is None:
        posterior_rate = float(season_rate)
        rate_source = "PLAYER_RATE_ONLY_NO_POSITION_PRIOR"
    else:
        posterior_rate = (
            season_rate * minutes + prior_rate * shrink_minutes
        ) / max(1e-9, minutes + shrink_minutes)
        rate_source = "PLAYER_RATE_SHRUNK_TO_POSITION_PRIOR"

    venue_factor, venue = _venue_factor(
        starts,
        home=home,
        season_rate=float(season_rate or posterior_rate),
    )
    opponent_factor, opponent = _opponent_factor(
        context,
        opponent_team_id=opponent_team_id,
        position=position,
        position_rate=prior_rate,
    )
    recent_factor, recent = _recent_factor(
        measured,
        float(season_rate or posterior_rate),
    )

    role = dict(role_evidence or {})
    role_factor = 1.0
    role_state = {
        "status": "DEGRADED_NO_CALIBRATED_ROLE_DEFCON_EFFECT",
        "factor": 1.0,
        "role": role.get("actual_tactical_role"),
        "classification": role.get("actual_tactical_role_class"),
    }
    explicit_role_multiplier = _f(role.get("defcon_rate_multiplier"))
    if (
        explicit_role_multiplier is not None
        and str(role.get("defcon_rate_multiplier_authority") or "").upper()
        == "CALIBRATED_DERIVED"
    ):
        role_factor = _clamp(explicit_role_multiplier, 0.75, 1.25)
        role_state = {
            "status": "APPLIED_CALIBRATED_DERIVED",
            "factor": round(role_factor, 6),
            "role": role.get("actual_tactical_role"),
            "classification": role.get("actual_tactical_role_class"),
        }

    projected_rate = (
        posterior_rate
        * venue_factor
        * opponent_factor
        * recent_factor
        * role_factor
    )
    if xmins is None:
        projected_probability = None
        defcon_ev = None
        projection_status = "UNAVAILABLE_NO_XMINS"
    else:
        minutes_projection = _clamp(float(xmins), 0.0, 90.0)
        count_probability = _poisson_tail(
            threshold,
            projected_rate * minutes_projection / 90.0,
        )
        if starts and prior_hit is not None:
            prior_strength = 4.0
            historical_posterior = (
                hits + prior_hit * prior_strength
            ) / (len(starts) + prior_strength)
            history_weight = min(0.35, len(starts) / (len(starts) + 8.0))
            projected_probability = (
                (1.0 - history_weight) * count_probability
                + history_weight * historical_posterior
            )
            calibration = {
                "status": "HISTORICAL_HIT_RATE_SHRINKAGE_APPLIED",
                "history_weight": round(history_weight, 6),
                "historical_posterior_hit_probability": round(
                    historical_posterior, 6
                ),
            }
        else:
            projected_probability = count_probability
            calibration = {
                "status": "COUNT_MODEL_ONLY_INSUFFICIENT_HIT_PRIOR",
                "history_weight": 0.0,
            }
        projected_probability = _clamp(projected_probability, 0.0, 1.0)
        defcon_ev = points * projected_probability
        projection_status = "AVAILABLE"

    return {
        "contract": "V12_DEFCON_HIT_PROBABILITY_V1",
        "status": projection_status,
        "eligible": True,
        "position": position,
        "threshold": threshold,
        "points": points,
        "defcon_hits": hits,
        "eligible_starts": len(starts),
        "hit_rate": None if hit_rate is None else round(hit_rate, 6),
        "home_hit_rate": (
            None if home_hit_rate is None else round(home_hit_rate, 6)
        ),
        "away_hit_rate": (
            None if away_hit_rate is None else round(away_hit_rate, 6)
        ),
        "def_actions_per90": (
            None if season_rate is None else round(season_rate, 6)
        ),
        "sample_size": {
            "appearances": len(measured),
            "eligible_starts": len(starts),
            "minutes": round(minutes, 1),
            "home_starts": len(home_starts),
            "away_starts": len(away_starts),
        },
        "confidence": confidence,
        "xmins": None if xmins is None else round(float(xmins), 3),
        "posterior_def_actions_per90": round(posterior_rate, 6),
        "projected_def_actions_per90": round(projected_rate, 6),
        "projected_hit_probability": (
            None
            if projected_probability is None
            else round(projected_probability, 6)
        ),
        "DEFCON_EV": None if defcon_ev is None else round(defcon_ev, 6),
        "conditions": {
            "rate_source": rate_source,
            "home_away": venue,
            "opponent_defensive_workload": opponent,
            "recent_defensive_actions": recent,
            "role": role_state,
            "calibration": (
                calibration if xmins is not None else {
                    "status": "NOT_RUN_NO_XMINS"
                }
            ),
        },
        "component_separation": {
            "DEFCON_EV": "SEPARATE_FPL_SCORING_COMPONENT",
            "CS_EV": "NOT_INCLUDED_HERE",
            "ATTACK_EV": "NOT_INCLUDED_HERE",
            "BONUS_EV": "NOT_INCLUDED_HERE",
            "cs_defcon_double_count": False,
        },
        "governance": {
            "canonical_p1_3_defcon_unchanged": True,
            "candidate_evidence_only": True,
            "opponent_conditioning_requires_sample": True,
            "uncalibrated_role_effect_not_applied": True,
            "missing_metrics_not_zero_filled": True,
            "no_recommendation_owner_created": True,
        },
    }
