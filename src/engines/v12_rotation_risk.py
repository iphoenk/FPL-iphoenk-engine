"""Canonical evidence and scenario contracts for rotation-risk decisions.

This module deliberately does not invent a starter probability.  It validates
news observations, exposes conditional states, and leaves numerical minutes
to V12_PLAYER_MINUTES and the canonical P1.4 sampler.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA = "V12_ROTATION_RISK_EVIDENCE_V1"
STATES = ("STARTER", "CAMEO", "DNP")
VALID_STRENGTH = {"LOW", "MEDIUM", "HIGH"}


def _time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def build_verified_rotation_event(
    *,
    source_url: str,
    published_at: str,
    observed_at: str,
    player_id: int,
    quote: str,
    evidence_strength: str,
    as_of_cutoff: str,
    source_type: str = "OFFICIAL_CLUB",
    event_type: str = "ROTATION_RISK",
) -> dict[str, Any]:
    """Validate a rotation observation without treating it as an injury flag."""
    if not str(source_url).startswith(("https://", "http://")):
        raise ValueError("SOURCE_VERIFIED requires source_url")
    if not str(quote).strip():
        raise ValueError("SOURCE_VERIFIED requires relevant quote")
    strength = str(evidence_strength).upper()
    if strength not in VALID_STRENGTH:
        raise ValueError("evidence_strength must be LOW, MEDIUM, or HIGH")
    published = _time(published_at)
    observed = _time(observed_at)
    cutoff = _time(as_of_cutoff)
    if published > cutoff or observed > cutoff:
        raise ValueError("AS_OF_VALID failed: event is after cutoff")
    payload = {
        "schema": SCHEMA,
        "event_type": event_type,
        "source_type": source_type,
        "source_url": source_url,
        "published_at": published.isoformat(),
        "observed_at": observed.isoformat(),
        "player_id": int(player_id),
        "quote": str(quote).strip(),
        "evidence_strength": strength,
        "as_of_cutoff": cutoff.isoformat(),
        "is_injury_flag": False,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["event_id"] = f"rotation:{digest[:16]}"
    return payload


def validate_rotation_events(
    events: Sequence[Mapping[str, Any]], *, as_of_cutoff: str, player_id: int
) -> dict[str, Any]:
    cutoff = _time(as_of_cutoff)
    valid: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = False
    errors: list[str] = []
    for raw in events:
        try:
            event = build_verified_rotation_event(
                source_url=str(raw.get("source_url") or ""),
                published_at=str(raw.get("published_at") or ""),
                observed_at=str(raw.get("observed_at") or ""),
                player_id=int(raw.get("player_id") or 0),
                quote=str(raw.get("quote") or ""),
                evidence_strength=str(raw.get("evidence_strength") or ""),
                as_of_cutoff=cutoff.isoformat(),
                source_type=str(raw.get("source_type") or "OFFICIAL_CLUB"),
                event_type=str(raw.get("event_type") or "ROTATION_RISK"),
            )
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if event["player_id"] != int(player_id):
            errors.append("player identity mismatch")
            continue
        if event["event_id"] in seen:
            duplicates = True
            continue
        seen.add(event["event_id"])
        valid.append(event)
    return {
        "status": "SOURCE_VERIFIED" if valid and not errors else "INSUFFICIENT_EVIDENCE",
        "source_verified": bool(valid),
        "no_duplicates": not duplicates,
        "as_of_valid": bool(valid) and not errors,
        "events": valid,
        "errors": errors,
        "player_id": int(player_id),
        "as_of_cutoff": cutoff.isoformat(),
    }



def canonical_conditional_minutes_support(
    projections: Mapping[str, Any] | None, *, player_id: int
) -> list[dict[str, Any]]:
    """Bind native xMins states without inventing a new rotation mixture.

    The state probabilities belong to the historical V12_PLAYER_MINUTES prior.
    They must NOT be represented as post-press-conference P(start) estimates.
    """
    rows = (projections or {}).get("players") or []
    player = next(
        (
            row for row in rows
            if isinstance(row, Mapping)
            and str(row.get("element") or "") == str(int(player_id))
        ),
        None,
    )
    if player is None:
        return []
    minutes = player.get("xmins")
    if not isinstance(minutes, Mapping):
        return []
    distribution = minutes.get("xmins_distribution")
    if not isinstance(distribution, Mapping):
        return []
    raw_states = distribution.get("states")
    if not isinstance(raw_states, list):
        return []
    by_name = {
        str(row.get("state") or "").upper(): row
        for row in raw_states
        if isinstance(row, Mapping)
    }
    groups = {
        "STARTER": ("START_FULL", "START_SUBBED", "EARLY_SUB"),
        "CAMEO": ("CAMEO", "LATE_CAMEO"),
        "DNP": ("DNP",),
    }
    if any(name not in by_name for names in groups.values() for name in names):
        return []
    support: list[dict[str, Any]] = []
    for group, names in groups.items():
        components: list[dict[str, Any]] = []
        for name in names:
            row = by_name[name]
            if not all(isinstance(row.get(field), (int, float)) and
                       not isinstance(row.get(field), bool)
                       for field in ("probability", "minutes_mean", "minutes_std")):
                return []
            components.append({
                "native_state": name,
                "minutes_mean": row["minutes_mean"],
                "minutes_std": row["minutes_std"],
                "historical_model_prior_weight": row["probability"],
                "timing_evidence": row.get("timing_evidence"),
            })
        support.append({
            "state": group,
            "components": components,
            "source": "V12_PLAYER_MINUTES",
            "post_news_probability_calibrated": False,
        })
    return support


def build_minutes_scenarios(
    *,
    player_id: int,
    existing_state_support: Sequence[Mapping[str, Any]],
    calibrated_weights: Mapping[str, float] | None = None,
    calibration_status: str = "NOT_VERIFIED",
) -> dict[str, Any]:
    """Expose STARTER/CAMEO/DNP conditionals; no uncalibrated blend is emitted."""
    weights = None
    if calibrated_weights is not None:
        candidate = {state: float(calibrated_weights.get(state, 0.0)) for state in STATES}
        if all(value >= 0 for value in candidate.values()) and abs(sum(candidate.values()) - 1.0) <= 1e-6 and calibration_status == "PASS":
            weights = candidate
    return {
        "player_id": int(player_id),
        "states": list(STATES),
        "canonical_state_support": [dict(row) for row in existing_state_support],
        "weights": weights,
        "weight_status": "CALIBRATED" if weights is not None else "UNKNOWN",
        "publication_mode": "MIXTURE" if weights is not None else "CONDITIONAL_ONLY",
        "calibration_status": calibration_status,
        "p_start_is_not_arbitrarily_reduced": True,
        "owner": "V12_PLAYER_MINUTES",
    }


def resolve_captain_vice(captain_minutes: float, vice_minutes: float) -> str:
    """Return the armband owner under the canonical FPL appearance rule."""
    if float(captain_minutes) > 0:
        return "CAPTAIN"
    if float(vice_minutes) > 0:
        return "VICE"
    return "NO_ACTIVE_ARMBAND"


def build_competitive_window(*, rivals: Sequence[Mapping[str, Any]], player_id: int) -> dict[str, Any]:
    rows = list(rivals)
    count_ok = len(rows) == 9
    return {
        "status": "PASS" if count_ok and all(row.get("effective_ownership") is not None for row in rows) else "INSUFFICIENT_EVIDENCE",
        "required_rivals": 9,
        "observed_rivals": len(rows),
        "player_id": int(player_id),
        "rows": [dict(row) for row in rows],
        "captain_shares_are_estimates": True,
        "no_predeadline_captain_fact_claim": True,
    }

