from __future__ import annotations

"""Stage B shadow evidence for DEFCON, availability, and role/duty.

This module is diagnostic/advisory by default. It does not own P1.1, P1.3,
P1.7, package utility, Monte Carlo, identity, or scheduler semantics.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.rules import DC_POINTS_CAP_PER_MATCH, DC_RULES, ELEMENT_TYPE_TO_POSITION

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_stageb_evidence.json"

AVAILABILITY_STATES = {
    "FIT",
    "DOUBT",
    "UNAVAILABLE_CONFIRMED",
    "UNAVAILABLE_UNKNOWN",
    "INTERNATIONAL_PLAYED",
    "INTERNATIONAL_HEAVY_MINUTES",
    "TRAVEL_RETURN",
    "CLUB_CONFIRMED_AVAILABLE",
}


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Stage B evidence config must be a JSON object")
    return value


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _optional_f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _poisson_tail_at_least(threshold: int, expected_count: float) -> float:
    if threshold <= 0:
        return 1.0
    lam = max(0.0, float(expected_count))
    if lam <= 0.0:
        return 0.0
    term = math.exp(-lam)
    cumulative = term
    for k in range(1, threshold):
        term *= lam / k
        cumulative += term
    return _clamp(1.0 - cumulative, 0.0, 1.0)


def _poisson_rate_for_tail(threshold: int, probability: float) -> float:
    target = _clamp(float(probability), 0.0, 0.999999)
    if target <= 0.0:
        return 0.0
    low, high = 0.0, max(1.0, float(threshold))
    while _poisson_tail_at_least(threshold, high) < target and high < 256.0:
        high *= 2.0
    for _ in range(64):
        mid = (low + high) / 2.0
        if _poisson_tail_at_least(threshold, mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _player_id(row: Mapping[str, Any]) -> int:
    return _i(
        row.get("player_id")
        or row.get("element")
        or row.get("official_element_id"),
        -1,
    )


def _sort_match_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in rows if isinstance(row, Mapping)),
        key=lambda row: (
            _i(row.get("gw")),
            str(row.get("match_id") or row.get("fixture") or ""),
        ),
    )


def _defensive_count(row: Mapping[str, Any]) -> float | None:
    """Resolve the Official FPL CBIT/CBIRT count without fabricating missing parts."""
    for key in ("defensive", "defensive_contribution", "defensive_contributions"):
        value = _optional_f(row.get(key))
        if value is not None:
            return max(0.0, value)

    position = str(row.get("position") or "").upper().strip()
    if position not in {"DEF", "MID", "FWD"}:
        return None

    cbi = _optional_f(row.get("clearances_blocks_interceptions"))
    if cbi is None:
        clearances = _optional_f(row.get("clearances"))
        blocks = _optional_f(row.get("blocks"))
        interceptions = _optional_f(row.get("interceptions"))
        if None in (clearances, blocks, interceptions):
            return None
        cbi = float(clearances) + float(blocks) + float(interceptions)

    tackles = _optional_f(row.get("tackles"))
    if tackles is None:
        return None
    total = float(cbi) + float(tackles)

    if position in {"MID", "FWD"}:
        recoveries = _optional_f(
            row.get("recoveries")
            if row.get("recoveries") is not None
            else row.get("ball_recoveries")
        )
        if recoveries is None:
            return None
        total += float(recoveries)

    return max(0.0, total)


def _def_actions_per90(rows: Sequence[Mapping[str, Any]]) -> float | None:
    usable = [
        row for row in rows
        if _f(row.get("minutes")) > 0 and _defensive_count(row) is not None
    ]
    minutes = sum(_f(row.get("minutes")) for row in usable)
    total = sum(_defensive_count(row) or 0.0 for row in usable)
    return total * 90.0 / minutes if minutes > 0.0 else None


def _rate(values: Sequence[bool]) -> float | None:
    return sum(bool(value) for value in values) / len(values) if values else None


def _xmins_atoms(xmins: Mapping[str, Any] | None) -> tuple[list[tuple[float, float]], str]:
    payload = dict(xmins or {})
    distribution = dict(payload.get("xmins_distribution") or {})
    atoms: list[tuple[float, float]] = []
    for row in distribution.get("states") or []:
        if not isinstance(row, Mapping):
            continue
        probability = _optional_f(row.get("probability"))
        minutes = _optional_f(row.get("minutes_mean"))
        if probability is None or minutes is None or probability < 0:
            continue
        atoms.append((probability, max(0.0, minutes)))
    total = sum(probability for probability, _ in atoms)
    if total > 0.0:
        return [(p / total, m) for p, m in atoms], "FINITE_STATE_DISTRIBUTION"
    mean = _optional_f(payload.get("expected_minutes"))
    if mean is None:
        mean = _optional_f(distribution.get("mean"))
    return ([(1.0, max(0.0, mean))] if mean is not None else []), "MEAN_ONLY"


def _xmins_uncertainty(xmins: Mapping[str, Any] | None, cfg: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(xmins or {})
    interval = payload.get("expected_minutes_interval") or []
    width = None
    if isinstance(interval, Sequence) and len(interval) == 2:
        lo, hi = _optional_f(interval[0]), _optional_f(interval[1])
        if lo is not None and hi is not None:
            width = max(0.0, hi - lo)
    if width is None:
        std = _optional_f(payload.get("minutes_std"))
        if std is not None:
            width = 2.56 * max(0.0, std)
    low_cut = _f(cfg.get("xmins_uncertainty_low_width"), 40.0)
    developing_cut = _f(cfg.get("xmins_uncertainty_developing_width"), 25.0)
    if width is None:
        label = "UNKNOWN"
    elif width >= low_cut:
        label = "LOW"
    elif width >= developing_cut:
        label = "DEVELOPING"
    else:
        label = "GOOD"
    return {"label": label, "interval_width": None if width is None else round(width, 3)}


def build_defcon_probability(
    *,
    player_id: int,
    element_type: int,
    match_rows: Sequence[Mapping[str, Any]],
    universe_rows: Sequence[Mapping[str, Any]] | None = None,
    xmins: Mapping[str, Any] | None = None,
    target_home: bool | None = None,
    target_opponent_team_id: int | None = None,
    target_role: str | None = None,
    baseline_probability: float | None = None,
    baseline_count_rate90: float | None = None,
) -> dict[str, Any]:
    cfg = dict((load_config().get("defcon") or {}))
    rule = dict(DC_RULES.get(int(element_type)) or {})
    if not rule.get("eligible"):
        return {
            "contract": "V12_STAGEB_DEFCON_PROBABILITY_V1",
            "player_id": int(player_id),
            "eligible": False,
            "position": ELEMENT_TYPE_TO_POSITION.get(int(element_type), "UNKNOWN"),
            "threshold": None,
            "points": 0.0,
            "projected_hit_probability": 0.0,
            "DEFCON_EV": 0.0,
            "confidence": "NONE",
            "reason": "POSITION_INELIGIBLE",
        }

    threshold = int(rule.get("threshold") or 0)
    points = min(float(rule.get("points") or 0.0), float(DC_POINTS_CAP_PER_MATCH))
    rows = [
        row for row in _sort_match_rows(match_rows)
        if _player_id(row) == int(player_id)
    ]
    starts = [
        row for row in rows
        if bool(row.get("starter"))
        and _f(row.get("minutes")) > 0.0
        and _defensive_count(row) is not None
    ]
    hits = [(_defensive_count(row) or 0.0) >= threshold for row in starts]
    home_rows = [row for row in starts if row.get("home") is True]
    away_rows = [row for row in starts if row.get("home") is False]
    season_rate = _def_actions_per90(starts)
    recent_n = max(1, int(cfg.get("recent_start_window") or 3))
    recent_rows = starts[-recent_n:]
    recent_rate = _def_actions_per90(recent_rows)
    evidence_minutes = sum(_f(row.get("minutes")) for row in starts)

    baseline_p = (
        _clamp(float(baseline_probability), 0.0, 1.0)
        if baseline_probability is not None
        else None
    )
    baseline_rate = (
        max(0.0, float(baseline_count_rate90))
        if baseline_count_rate90 is not None
        else (
            _poisson_rate_for_tail(threshold, baseline_p)
            if baseline_p is not None
            else None
        )
    )
    shrink_minutes = max(0.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    if season_rate is None:
        count_rate90 = baseline_rate
        count_rate_source = "BASELINE_ONLY" if baseline_rate is not None else "UNAVAILABLE"
    elif baseline_rate is None:
        count_rate90 = season_rate
        count_rate_source = "OBSERVED_ONLY_NO_BASELINE"
    else:
        count_rate90 = (
            season_rate * evidence_minutes + baseline_rate * shrink_minutes
        ) / max(1e-9, evidence_minutes + shrink_minutes)
        count_rate_source = "OBSERVED_SHRUNK_TO_EXISTING_P1_3_BASELINE"

    def factor_from_rate(
        subset: Sequence[Mapping[str, Any]],
        minimum: int,
        low: float,
        high: float,
    ) -> tuple[float, str, float | None]:
        rate = _def_actions_per90(subset)
        if (
            season_rate is None
            or season_rate <= 0.0
            or rate is None
            or len(subset) < minimum
        ):
            return 1.0, "UNAVAILABLE_OR_LOW_SAMPLE", rate
        return _clamp(rate / season_rate, low, high), "AVAILABLE", rate

    min_condition = max(1, int(cfg.get("minimum_starts_for_conditioning") or 3))
    venue_subset = (
        home_rows if target_home is True
        else away_rows if target_home is False
        else []
    )
    venue_factor, venue_state, venue_rate = factor_from_rate(
        venue_subset,
        min_condition,
        _f(cfg.get("venue_factor_min"), 0.75),
        _f(cfg.get("venue_factor_max"), 1.25),
    )

    position = ELEMENT_TYPE_TO_POSITION.get(int(element_type), "UNKNOWN")
    universe = _sort_match_rows(universe_rows or ())
    same_position = [
        row for row in universe
        if str(row.get("position") or "").upper() == position
        and bool(row.get("starter"))
        and _f(row.get("minutes")) > 0
        and _defensive_count(row) is not None
    ]
    opponent_rows = [
        row for row in same_position
        if target_opponent_team_id is not None
        and _i(row.get("opponent_team_id") or row.get("opponent"), -1)
        == int(target_opponent_team_id)
    ]
    league_rate = _def_actions_per90(same_position)
    opponent_rate = _def_actions_per90(opponent_rows)
    opp_min = max(1, int(cfg.get("opponent_minimum_same_position_starts") or 3))
    if (
        target_opponent_team_id is not None
        and len(opponent_rows) >= opp_min
        and league_rate is not None
        and league_rate > 0
        and opponent_rate is not None
    ):
        opponent_factor = _clamp(
            opponent_rate / league_rate,
            _f(cfg.get("opponent_factor_min"), 0.8),
            _f(cfg.get("opponent_factor_max"), 1.2),
        )
        opponent_state = "AVAILABLE"
    else:
        opponent_factor = 1.0
        opponent_state = "DEGRADED_NEUTRAL"

    role_rows = [
        row for row in starts
        if target_role
        and str(row.get("actual_role") or "").upper() == str(target_role).upper()
    ]
    role_min = max(1, int(cfg.get("role_minimum_starts") or 3))
    role_rate = _def_actions_per90(role_rows)
    if (
        target_role
        and len(role_rows) >= role_min
        and season_rate is not None
        and season_rate > 0
        and role_rate is not None
    ):
        role_factor = _clamp(
            role_rate / season_rate,
            _f(cfg.get("role_factor_min"), 0.85),
            _f(cfg.get("role_factor_max"), 1.15),
        )
        role_state = "AVAILABLE"
    else:
        role_factor = 1.0
        role_state = "DEGRADED_NEUTRAL"

    recent_factor = 1.0
    recent_state = "DEGRADED_NEUTRAL"
    if (
        recent_rate is not None
        and season_rate is not None
        and season_rate > 0
        and len(recent_rows) >= min_condition
    ):
        recent_factor = _clamp(recent_rate / season_rate, 0.8, 1.2)
        recent_state = "AVAILABLE"

    adjusted_rate90 = (
        max(0.0, count_rate90)
        * venue_factor
        * opponent_factor
        * role_factor
        * recent_factor
        if count_rate90 is not None
        else None
    )
    atoms, xmins_mode = _xmins_atoms(xmins)
    if adjusted_rate90 is None or not atoms:
        structural_p = baseline_p
    else:
        structural_p = sum(
            probability
            * _poisson_tail_at_least(
                threshold,
                adjusted_rate90 * max(0.0, minutes) / 90.0,
            )
            for probability, minutes in atoms
        )

    empirical_rate = _rate(hits)
    if structural_p is not None:
        calibrated_p = structural_p
        calibration_state = "COUNT_RATE_PLUS_XMINS_PRIMARY_HIT_RATE_DIAGNOSTIC"
    elif empirical_rate is not None:
        calibrated_p = empirical_rate
        calibration_state = "EMPIRICAL_FALLBACK_NO_STRUCTURAL_RATE_OR_XMINS"
    else:
        calibrated_p = None
        calibration_state = "UNAVAILABLE"

    probability = None if calibrated_p is None else _clamp(calibrated_p, 0.0, 1.0)
    ev = None if probability is None else points * probability
    uncertainty = _xmins_uncertainty(xmins, cfg)
    mature = max(1, int(cfg.get("minimum_starts_for_mature_hit_rate") or 5))
    if len(starts) < 3:
        confidence = "LOW"
    elif len(starts) < mature:
        confidence = "DEVELOPING"
    else:
        confidence = "HIGH"
    if uncertainty["label"] in {"LOW", "UNKNOWN"} and confidence == "HIGH":
        confidence = "DEVELOPING"
    if opponent_state != "AVAILABLE" and confidence == "HIGH":
        confidence = "DEVELOPING"

    return {
        "contract": "V12_STAGEB_DEFCON_PROBABILITY_V1",
        "player_id": int(player_id),
        "eligible": True,
        "position": position,
        "threshold": threshold,
        "points": points,
        "defcon_hits": sum(hits),
        "eligible_starts": len(starts),
        "hit_rate": None if empirical_rate is None else round(empirical_rate, 6),
        "home_hit_rate": None if not home_rows else round(
            sum((_defensive_count(row) or 0.0) >= threshold for row in home_rows)
            / len(home_rows),
            6,
        ),
        "away_hit_rate": None if not away_rows else round(
            sum((_defensive_count(row) or 0.0) >= threshold for row in away_rows)
            / len(away_rows),
            6,
        ),
        "def_actions_per90": None if season_rate is None else round(season_rate, 6),
        "recent_def_actions_per90": None if recent_rate is None else round(recent_rate, 6),
        "sample_size": {
            "starts": len(starts),
            "minutes": round(evidence_minutes, 1),
            "home_starts": len(home_rows),
            "away_starts": len(away_rows),
            "recent_starts": len(recent_rows),
        },
        "confidence": confidence,
        "projected_hit_probability": None if probability is None else round(probability, 6),
        "DEFCON_EV": None if ev is None else round(ev, 6),
        "model": {
            "baseline_probability": baseline_p,
            "baseline_count_rate90": baseline_rate,
            "count_rate90": None if count_rate90 is None else round(count_rate90, 6),
            "adjusted_count_rate90": None if adjusted_rate90 is None else round(adjusted_rate90, 6),
            "count_rate_source": count_rate_source,
            "calibration": calibration_state,
            "xmins_mode": xmins_mode,
            "xmins_uncertainty": uncertainty,
            "venue": {
                "target_home": target_home,
                "factor": round(venue_factor, 6),
                "state": venue_state,
                "observed_rate90": None if venue_rate is None else round(venue_rate, 6),
            },
            "opponent_workload": {
                "opponent_team_id": target_opponent_team_id,
                "factor": round(opponent_factor, 6),
                "state": opponent_state,
                "same_position_starts": len(opponent_rows),
                "opponent_def_actions_per90": None if opponent_rate is None else round(opponent_rate, 6),
                "league_def_actions_per90": None if league_rate is None else round(league_rate, 6),
            },
            "role_conditioning": {
                "role": target_role,
                "factor": round(role_factor, 6),
                "state": role_state,
                "starts": len(role_rows),
                "def_actions_per90": None if role_rate is None else round(role_rate, 6),
            },
            "recent_actions": {
                "factor": round(recent_factor, 6),
                "state": recent_state,
            },
        },
        "provenance": {
            "threshold_authority": "Official FPL active ruleset via src.rules.DC_RULES",
            "historical_rows": "V12 normalized player_match_rows",
            "baseline_prior": "existing P1.3 DEFCON posterior when supplied",
            "clean_sheet_used_as_input": False,
        },
        "governance": {
            "shadow_only": True,
            "not_added_on_top_of_existing_defcon_component": True,
            "ab_replacement_semantics": "REPLACE_BASELINE_DEFCON_COMPONENT_ONLY",
            "clean_sheet_defcon_double_count_guard": True,
            "no_final_xpts_mutation": True,
        },
    }


def _normalize_availability_evidence(
    evidence: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    cfg = dict((load_config().get("availability") or {}))
    as_of_dt = _timestamp(as_of)
    if as_of_dt is None:
        raise ValueError("as_of must be ISO-8601")
    ttl_map = dict(cfg.get("default_ttl_hours") or {})
    out = []
    for index, raw in enumerate(evidence or ()):
        if not isinstance(raw, Mapping):
            continue
        source = str(raw.get("source") or "").strip()
        evidence_type = str(raw.get("evidence_type") or "").strip().upper()
        stamp = _timestamp(raw.get("timestamp"))
        confidence = _clamp(_f(raw.get("confidence"), 0.0), 0.0, 1.0)
        ttl_hours = _optional_f(raw.get("ttl_hours"))
        if ttl_hours is None:
            ttl_hours = _optional_f(ttl_map.get(evidence_type))
        expires_at = stamp + timedelta(hours=ttl_hours) if stamp and ttl_hours is not None else None
        stale = stamp is None or (expires_at is not None and as_of_dt > expires_at)
        availability = str(raw.get("availability") or "").strip().upper() or None
        row = {
            "index": index,
            "source": source or None,
            "timestamp": _iso(stamp),
            "evidence_type": evidence_type or "UNKNOWN",
            "confidence": round(confidence, 4),
            "ttl_hours": ttl_hours,
            "expires_at": _iso(expires_at),
            "stale": stale,
            "availability": availability,
            "minutes": _optional_f(raw.get("minutes")),
            "travel_return": bool(raw.get("travel_return")),
            "reason": raw.get("reason"),
            "raw_state_hint": raw.get("state_hint"),
            "diagnosis_inferred": False,
        }
        out.append(row)
    return out


def build_availability_state(
    evidence: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> dict[str, Any]:
    cfg = dict((load_config().get("availability") or {}))
    rows = _normalize_availability_evidence(evidence, as_of=as_of)
    active = [row for row in rows if not row["stale"]]
    min_confirmed = _f(cfg.get("minimum_confirmed_confidence"), 0.8)

    confirmed_unavailable = [
        row for row in active
        if row["evidence_type"] in {"OFFICIAL_STATUS", "CLUB_STATEMENT"}
        and row["availability"] == "UNAVAILABLE"
        and row["confidence"] >= min_confirmed
    ]
    confirmed_available = [
        row for row in active
        if row["evidence_type"] in {"OFFICIAL_STATUS", "CLUB_STATEMENT"}
        and row["availability"] == "AVAILABLE"
        and row["confidence"] >= min_confirmed
    ]
    explicit_doubt = [
        row for row in active
        if row["evidence_type"] in {"OFFICIAL_STATUS", "CLUB_STATEMENT"}
        and row["availability"] == "DOUBT"
    ]
    international = [
        row for row in active
        if row["evidence_type"] == "INTERNATIONAL_APPEARANCE"
        and (row["minutes"] or 0.0) > 0.0
    ]
    travel = [
        row for row in active
        if row["evidence_type"] == "TRAVEL" and row["travel_return"]
    ]
    ambiguous_unavailable = [
        row for row in active
        if row["availability"] == "UNAVAILABLE"
        and row not in confirmed_unavailable
    ]
    conflict = bool(confirmed_unavailable and confirmed_available)

    if conflict:
        state = "DOUBT"
        resolution = "CONFLICTING_AUTHORITATIVE_EVIDENCE"
    elif confirmed_unavailable:
        state = "UNAVAILABLE_CONFIRMED"
        resolution = "CONFIRMED_UNAVAILABLE"
    elif confirmed_available:
        state = (
            "CLUB_CONFIRMED_AVAILABLE"
            if any(row["evidence_type"] == "CLUB_STATEMENT" for row in confirmed_available)
            else "FIT"
        )
        resolution = "CONFIRMED_AVAILABLE"
    elif explicit_doubt:
        state = "DOUBT"
        resolution = "EXPLICIT_DOUBT"
    elif international:
        heavy = max(row["minutes"] or 0.0 for row in international) >= _f(
            cfg.get("international_heavy_minutes_threshold"), 75.0
        )
        state = "INTERNATIONAL_HEAVY_MINUTES" if heavy else "INTERNATIONAL_PLAYED"
        resolution = "INTERNATIONAL_APPEARANCE"
    elif travel:
        state = "TRAVEL_RETURN"
        resolution = "TRAVEL_EVIDENCE"
    elif ambiguous_unavailable:
        state = "UNAVAILABLE_UNKNOWN"
        resolution = "UNAVAILABILITY_WITHOUT_CONFIRMED_MEDICAL_REASON"
    else:
        state = "FIT"
        resolution = "NO_ACTIVE_ADVERSE_EVIDENCE"

    if state not in AVAILABILITY_STATES:
        raise AssertionError("invalid availability state")

    heavy_international = bool(
        international
        and max(row["minutes"] or 0.0 for row in international) >= _f(
            cfg.get("international_heavy_minutes_threshold"), 75.0
        )
    )
    workload_states = []
    congestion = 1.0
    if international:
        workload_states.append(
            "INTERNATIONAL_HEAVY_MINUTES"
            if heavy_international
            else "INTERNATIONAL_PLAYED"
        )
    if travel:
        workload_states.append("TRAVEL_RETURN")
    if heavy_international:
        congestion = min(
            congestion,
            _clamp(
                _f(cfg.get("international_heavy_minutes_congestion_factor"), 0.9),
                0.0,
                1.0,
            ),
        )
    if travel:
        congestion = min(
            congestion,
            _clamp(
                _f(cfg.get("travel_return_congestion_factor"), 0.95),
                0.0,
                1.0,
            ),
        )
    xmins_effect = (
        "EXISTING_P1_1_CONGESTION_FACTOR"
        if congestion < 1.0
        else "NONE"
    )

    confidence = max((row["confidence"] for row in active), default=0.0)
    if conflict:
        confidence = min(confidence, 0.5)

    return {
        "contract": "V12_STAGEB_AVAILABILITY_STATE_V1",
        "state": state,
        "resolution": resolution,
        "confidence": round(confidence, 4),
        "as_of": as_of,
        "active_evidence": active,
        "stale_evidence": [row for row in rows if row["stale"]],
        "conflicting_sources": conflict,
        "secondary_workload_states": workload_states,
        "xmins_context_overlay": {
            "congestion_factor": round(congestion, 6),
            "application": xmins_effect,
            "availability_probability_override": None,
            "reason": (
                "Stage B may use existing P1.1 congestion input for workload/travel; "
                "it does not create a second availability owner."
            ),
        },
        "governance": {
            "news_or_event_is_not_medical_diagnosis": True,
            "unknown_unavailability_is_not_injury": True,
            "official_or_club_fact_precedes_analyst_claim": True,
            "stale_evidence_cannot_drive_active_state": True,
            "external_claim_does_not_overwrite_official_player_status": True,
        },
    }


def _fact(value: Any, source: str, *, timestamp: Any = None) -> dict[str, Any]:
    return {
        "class": "FACT",
        "value": value,
        "source": source,
        "timestamp": timestamp,
    }


def _derived(value: Any, source: str, *, inputs: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "class": "DERIVED",
        "value": value,
        "source": source,
        "inputs": list(inputs),
    }


def _inferred(value: Any, source: str, confidence: float) -> dict[str, Any]:
    return {
        "class": "INFERRED",
        "value": value,
        "source": source,
        "confidence": round(_clamp(confidence, 0.0, 1.0), 4),
        "authoritative_override": False,
    }


def build_role_duty_evidence(
    *,
    official_player: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]] = (),
    xmins: Mapping[str, Any] | None = None,
    tactical_role: Mapping[str, Any] | None = None,
    external_claims: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    cfg = dict((load_config().get("role_duty") or {}))
    player_id = _i(official_player.get("id") or official_player.get("element"), -1)
    rows = [
        row for row in _sort_match_rows(match_rows)
        if _player_id(row) == player_id
    ]
    played = [row for row in rows if _f(row.get("minutes")) > 0]
    last_n = max(1, int(cfg.get("starts_last_n") or 5))
    recent = played[-last_n:]
    starts = sum(bool(row.get("starter")) for row in recent)

    sub_n = max(1, int(cfg.get("sub_timing_last_n") or 5))
    starter_rows = [row for row in played if bool(row.get("starter"))][-sub_n:]
    sub_minutes = [
        _f(row.get("minutes"))
        for row in starter_rows
        if _f(row.get("minutes")) < 90.0
    ]
    sub_pattern = {
        "sample_starts": len(starter_rows),
        "subbed_starts": len(sub_minutes),
        "mean_minutes_when_subbed": (
            None if not sub_minutes else round(sum(sub_minutes) / len(sub_minutes), 3)
        ),
    }

    element_type = _i(official_player.get("element_type"), 0)
    nominal_position = ELEMENT_TYPE_TO_POSITION.get(element_type)
    xmins_payload = dict(xmins or {})
    interval = xmins_payload.get("expected_minutes_interval")
    role_payload = dict(tactical_role or {})
    role_value = role_payload.get("profile") or role_payload.get("role")
    role_class = "DERIVED" if role_value else "DERIVED"

    official_source = "OFFICIAL_FPL_BOOTSTRAP"
    facts = {
        "penalty_duty": _fact(
            {
                "order": official_player.get("penalties_order"),
                "text": official_player.get("penalties_text"),
            },
            official_source,
        ),
        "corner_indirect_fk_duty": _fact(
            {
                "order": official_player.get("corners_and_indirect_freekicks_order"),
                "text": official_player.get("corners_and_indirect_freekicks_text"),
            },
            official_source,
        ),
        "direct_fk_duty": _fact(
            {
                "order": official_player.get("direct_freekicks_order"),
                "text": official_player.get("direct_freekicks_text"),
            },
            official_source,
        ),
        "nominal_position": _fact(nominal_position, official_source),
    }
    derived = {
        "actual_tactical_role": {
            "class": role_class,
            "value": role_value,
            "source": role_payload.get("source") or "TACTICAL_ROLE_OBSERVED_ENRICHMENT",
            "confidence": role_payload.get("confidence"),
            "authoritative_override": False,
        },
        "starts_last_n": _derived(
            {
                "n": last_n,
                "sample_played": len(recent),
                "starts": starts,
                "rate": round(starts / len(recent), 6) if recent else None,
            },
            "NORMALIZED_PLAYER_MATCH_ROWS",
            inputs=("starter", "minutes"),
        ),
        "sub_timing_pattern": _derived(
            sub_pattern,
            "NORMALIZED_PLAYER_MATCH_ROWS",
            inputs=("starter", "minutes"),
        ),
        "xmins_security": _derived(
            {
                "p_start": xmins_payload.get("start_probability"),
                "expected_minutes": xmins_payload.get("expected_minutes"),
                "expected_minutes_interval": interval,
                "confidence": xmins_payload.get("confidence"),
            },
            "V12_PLAYER_MINUTES",
            inputs=("P1.1",),
        ),
    }
    inferred = []
    for claim in external_claims or ():
        if not isinstance(claim, Mapping):
            continue
        inferred.append(
            _inferred(
                {
                    "claim_type": claim.get("claim_type"),
                    "value": claim.get("value"),
                    "timestamp": claim.get("timestamp"),
                },
                str(claim.get("source") or "EXTERNAL_ANALYST"),
                _f(claim.get("confidence"), 0.0),
            )
        )

    return {
        "contract": "V12_STAGEB_ROLE_DUTY_EVIDENCE_V1",
        "player_id": player_id,
        "FACT": facts,
        "DERIVED": derived,
        "INFERRED": inferred,
        "governance": {
            "official_fact_not_overwritten_by_external_claim": True,
            "inferred_claims_are_advisory_only": True,
            "nominal_position_separate_from_tactical_role": True,
            "duty_rank_is_not_share_probability": True,
        },
    }


def build_opponent_defensive_workload(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in _sort_match_rows(rows):
        position = str(row.get("position") or "").upper()
        opponent = _i(row.get("opponent_team_id") or row.get("opponent"), -1)
        if (
            position in {"DEF", "MID", "FWD"}
            and opponent > 0
            and bool(row.get("starter"))
            and _f(row.get("minutes")) > 0
            and _defensive_count(row) is not None
        ):
            grouped[(position, opponent)].append(row)
    return {
        "contract": "V12_STAGEB_OPPONENT_DEFENSIVE_WORKLOAD_V1",
        "rows": {
            f"{position}:{opponent}": {
                "position": position,
                "opponent_team_id": opponent,
                "starts": len(group),
                "def_actions_per90": (
                    None
                    if _def_actions_per90(group) is None
                    else round(_def_actions_per90(group) or 0.0, 6)
                ),
            }
            for (position, opponent), group in sorted(grouped.items())
        },
        "derived_from": "normalized player-match defensive contribution totals",
        "interpretation": "how many eligible defensive actions same-position starters accumulate when facing the opponent",
    }
def attach_stageb_shadow_evidence(
    projections: dict[str, Any],
    *,
    bootstrap: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]],
    universe_rows: Sequence[Mapping[str, Any]] | None = None,
    availability_by_player: Mapping[int | str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: str | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """Attach Stage B evidence without mutating canonical score/minutes fields.

    Disabled is an exact no-op on the supplied object so feature-off output is
    structurally identical. Enabled only adds stageb_evidence.
    """
    if not enabled:
        return projections

    official = {
        _i(row.get("id"), -1): dict(row)
        for row in bootstrap.get("elements") or []
        if isinstance(row, Mapping) and _i(row.get("id"), -1) > 0
    }
    availability_map = dict(availability_by_player or {})
    evidence_players = 0
    for projection in projections.get("players") or []:
        if not isinstance(projection, dict):
            continue
        element = _i(projection.get("element"), -1)
        if element <= 0:
            continue
        player = official.get(element) or {}
        element_type = _i(player.get("element_type"), 0)
        xmins = dict(projection.get("xmins") or {})
        rates = dict(projection.get("posterior_rates") or {})
        baseline_dc = dict(rates.get("defcon") or {})

        target_home = None
        target_opponent = None
        gw_rows = projection.get("xpts_by_gw") or projection.get("fixtures") or []
        if gw_rows and isinstance(gw_rows[0], Mapping):
            fixture = dict(gw_rows[0])
            target_home = fixture.get("home")
            target_opponent = fixture.get("opponent")
            nested = fixture.get("fixtures") or []
            if nested and isinstance(nested[0], Mapping):
                target_home = nested[0].get("home", target_home)
                target_opponent = nested[0].get("opponent", target_opponent)

        baseline_probability = None
        if baseline_dc.get("expected_points90") is not None and baseline_dc.get("points"):
            baseline_probability = _f(baseline_dc.get("expected_points90")) / max(
                1e-9, _f(baseline_dc.get("points"))
            )
        role = dict(projection.get("tactical_role") or {})
        role_profile = role.get("profile") or role.get("role")

        defcon = build_defcon_probability(
            player_id=element,
            element_type=element_type,
            match_rows=match_rows,
            universe_rows=universe_rows or match_rows,
            xmins=xmins,
            target_home=target_home if isinstance(target_home, bool) else None,
            target_opponent_team_id=(
                _i(target_opponent, -1) if target_opponent is not None else None
            ),
            target_role=str(role_profile) if role_profile else None,
            baseline_probability=baseline_probability,
            baseline_count_rate90=_optional_f(
                baseline_dc.get("posterior_count_rate90")
            ),
        )
        role_duty = build_role_duty_evidence(
            official_player=player,
            match_rows=match_rows,
            xmins=xmins,
            tactical_role=role,
        )
        availability = None
        supplied = (
            availability_map.get(element)
            or availability_map.get(str(element))
            or []
        )
        if as_of and supplied:
            availability = build_availability_state(supplied, as_of=as_of)

        projection["stageb_evidence"] = {
            "defcon": defcon,
            "availability": availability,
            "role_duty": role_duty,
            "shadow_only": True,
            "canonical_xpts_mutated": False,
            "canonical_xmins_mutated": False,
        }
        evidence_players += 1

    projections["stageb_evidence_summary"] = {
        "contract": "V12_STAGEB_SHADOW_EVIDENCE_ATTACHMENT_V1",
        "enabled": True,
        "player_count": evidence_players,
        "canonical_xpts_mutated": False,
        "canonical_xmins_mutated": False,
        "p17_semantics_changed": False,
        "p12b_semantics_changed": False,
        "monte_carlo_semantics_changed": False,
    }
    return projections
