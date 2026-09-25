from __future__ import annotations

"""Structured availability evidence without medical diagnosis inference."""

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

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

FACT_SOURCES = {"OFFICIAL_FPL", "CLUB_OFFICIAL"}
OBSERVED_SOURCES = {"MATCH_OBSERVED", "INTERNATIONAL_MATCH_OBSERVED"}


def _parse_ts(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now(value: str | None) -> datetime:
    parsed = _parse_ts(value)
    return parsed or datetime.now(timezone.utc)


def _confidence(value: Any, default: str = "MEDIUM") -> str:
    token = str(value or default).upper().strip()
    return token if token in {"NONE", "LOW", "MEDIUM", "HIGH"} else default


def _source_class(value: Any) -> str:
    token = str(value or "EXTERNAL").upper().strip()
    if token in FACT_SOURCES:
        return "FACT"
    if token in OBSERVED_SOURCES:
        return "DERIVED_OBSERVATION"
    return "INFERRED_OR_REPORTED"


def _official_evidence(player: Mapping[str, Any], timestamp: str | None) -> list[dict[str, Any]]:
    status = str(player.get("status") or "a").lower().strip()
    chance = player.get("chance_of_playing_next_round")
    state: str
    if chance is not None:
        try:
            chance_value = float(chance)
        except (TypeError, ValueError):
            chance_value = None
        if chance_value is not None and chance_value <= 0:
            state = "UNAVAILABLE_CONFIRMED"
        elif chance_value is not None and chance_value < 100:
            state = "DOUBT"
        else:
            state = "FIT"
    elif status == "a":
        state = "FIT"
    elif status == "d":
        state = "DOUBT"
    else:
        state = "UNAVAILABLE_CONFIRMED"
    return [
        {
            "state": state,
            "source": "OFFICIAL_FPL",
            "source_class": "FACT",
            "timestamp": timestamp,
            "evidence_type": "OFFICIAL_AVAILABILITY_STATUS",
            "confidence": "HIGH",
            "expires_at": None,
            "staleness": "CURRENT_SNAPSHOT",
            "reason": f"official_status:{status}",
            "medical_diagnosis": None,
            "chance_of_playing_next_round": chance,
        }
    ]


def _normalize_event(
    raw: Mapping[str, Any],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    source = str(raw.get("source") or "EXTERNAL").upper().strip()
    evidence_type = str(raw.get("evidence_type") or "").upper().strip()
    timestamp = _parse_ts(raw.get("timestamp"))
    expires_at = _parse_ts(raw.get("expires_at"))
    stale = bool(expires_at and now > expires_at)
    staleness = (
        "STALE"
        if stale
        else "FRESH"
        if timestamp is not None
        else "UNKNOWN_TIMESTAMP"
    )
    explicit_state = str(raw.get("state") or "").upper().strip()
    states: list[str] = []

    if explicit_state in AVAILABILITY_STATES:
        states.append(explicit_state)
    elif evidence_type == "INTERNATIONAL_PLAYED":
        states.append("INTERNATIONAL_PLAYED")
    elif evidence_type == "TRAVEL_RETURN":
        states.append("TRAVEL_RETURN")
    elif evidence_type == "CLUB_CONFIRMED_AVAILABLE":
        states.append("CLUB_CONFIRMED_AVAILABLE")
    elif evidence_type in {"ABSENCE_REPORT", "NOT_IN_SQUAD", "UNAVAILABLE_REPORT"}:
        states.append("UNAVAILABLE_UNKNOWN")
    elif evidence_type in {"DOUBT_REPORT", "TRAINING_DOUBT"}:
        states.append("DOUBT")

    minutes = raw.get("minutes")
    try:
        minutes_value = float(minutes) if minutes is not None else None
    except (TypeError, ValueError):
        minutes_value = None
    if (
        evidence_type == "INTERNATIONAL_PLAYED"
        and minutes_value is not None
        and minutes_value >= 75.0
        and "INTERNATIONAL_HEAVY_MINUTES" not in states
    ):
        states.append("INTERNATIONAL_HEAVY_MINUTES")

    out = []
    for state in states:
        out.append(
            {
                "state": state,
                "source": source,
                "source_class": _source_class(source),
                "timestamp": raw.get("timestamp"),
                "evidence_type": evidence_type or "EXPLICIT_STATE",
                "confidence": _confidence(raw.get("confidence")),
                "expires_at": raw.get("expires_at"),
                "staleness": staleness,
                "stale": stale,
                "minutes": minutes_value,
                "reason": raw.get("reason"),
                "medical_diagnosis": None,
                "raw_claim_preserved": raw.get("claim"),
            }
        )
    return out


def _authority_rank(row: Mapping[str, Any]) -> tuple[int, int, datetime]:
    source = str(row.get("source") or "").upper()
    source_class = str(row.get("source_class") or "")
    if source == "OFFICIAL_FPL":
        rank = 4
    elif source == "CLUB_OFFICIAL":
        rank = 3
    elif source_class == "DERIVED_OBSERVATION":
        rank = 2
    else:
        rank = 1
    confidence = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(
        str(row.get("confidence") or "NONE").upper(),
        0,
    )
    ts = _parse_ts(row.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)
    return rank, confidence, ts


def build_availability_state(
    player: Mapping[str, Any],
    *,
    events: Sequence[Mapping[str, Any]] = (),
    snapshot_timestamp: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    now = _now(now_iso)
    evidence = _official_evidence(player, snapshot_timestamp)
    for raw in events:
        if isinstance(raw, Mapping):
            evidence.extend(_normalize_event(raw, now=now))

    active = [row for row in evidence if not bool(row.get("stale"))]
    authority = sorted(active, key=_authority_rank, reverse=True)
    dominant = authority[0] if authority else None
    states = sorted({str(row.get("state")) for row in active if row.get("state")})

    official = [row for row in active if row.get("source") == "OFFICIAL_FPL"]
    nonofficial = [row for row in active if row.get("source") != "OFFICIAL_FPL"]
    conflict = bool(
        official
        and nonofficial
        and any(row.get("state") != official[0].get("state") for row in nonofficial)
    )

    heavy_minutes = [
        row for row in active if row.get("state") == "INTERNATIONAL_HEAVY_MINUTES"
    ]
    travel = [row for row in active if row.get("state") == "TRAVEL_RETURN"]

    return {
        "contract": "V12_STRUCTURED_AVAILABILITY_V1",
        "dominant_state": dominant.get("state") if dominant else None,
        "states": states,
        "evidence": evidence,
        "conflict": conflict,
        "official_authority_present": bool(official),
        "stale_evidence_count": sum(bool(row.get("stale")) for row in evidence),
        "xmins_context": {
            "official_availability_may_be_consumed_by_p1_1": True,
            "external_availability_overrides_official": False,
            "international_heavy_minutes_present": bool(heavy_minutes),
            "travel_return_present": bool(travel),
            "automatic_numeric_congestion_factor": None,
            "automatic_numeric_rotation_risk": None,
            "reason": (
                "No uncalibrated numeric fatigue/travel multiplier is fabricated; "
                "P1.1 remains the minutes authority."
            ),
        },
        "governance": {
            "news_is_not_medical_diagnosis": True,
            "unknown_absence_not_relabelled_injury": True,
            "official_fpl_availability_is_factual_authority": True,
            "stale_evidence_cannot_be_dominant": True,
            "conflicting_lower_authority_evidence_preserved_not_overwritten": True,
        },
    }
