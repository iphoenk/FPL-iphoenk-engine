from __future__ import annotations

"""Target-aware injury / fitness / availability evidence semantics.

This module is an evidence normalizer and deterministic categorical resolver.
It is NOT a P(start) model, xMins model, optimizer, factual plane, or publisher.
Only the existing V12 player-minutes owner may convert normalized evidence into
probabilistic start/minutes outputs.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence


TRI = {"YES", "NO", "UNKNOWN"}
EVIDENCE_POLARITIES = {
    "SUPPORTS_CONCERN",
    "REDUCES_CONCERN",
    "NEUTRAL",
    "UNKNOWN",
}
EVIDENCE_TYPES = {
    "INJURY_EVENT",
    "ILLNESS",
    "FATIGUE",
    "WORKLOAD_MANAGEMENT",
    "INTERNATIONAL_WITHDRAWAL",
    "RETURNED_TO_CLUB",
    "SCAN_RESULT",
    "MANAGER_QUOTE",
    "TRAINING_ABSENCE",
    "PARTIAL_TRAINING",
    "FULL_TRAINING",
    "MATCH_APPEARANCE",
    "RETURN_TO_PLAY",
    "FPL_FLAG",
    "EXPECTED_RETURN",
    "OTHER",
}
INJURY_MECHANISMS = {
    "MUSCLE",
    "IMPACT",
    "CONTACT",
    "NON_CONTACT",
    "ILLNESS",
    "FATIGUE",
    "WORKLOAD",
    "UNKNOWN",
}
TRAINING_STATUSES = {"FULL", "PARTIAL", "INDIVIDUAL", "ABSENT", "UNKNOWN"}
MATCH_STATUSES = {
    "STARTED",
    "BENCH",
    "PLAYED",
    "SUBBED_IN",
    "SUBBED_OUT",
    "MISSED",
    "UNKNOWN",
}
MANAGER_SEVERITIES = {
    "NONE",
    "MINOR",
    "NOT_SERIOUS",
    "DOUBT",
    "SERIOUS",
    "UNKNOWN",
}
CLUB_ASSESSMENTS = {
    "CLEARED",
    "ASSESSING",
    "REHAB",
    "RETURN_TO_TRAINING",
    "RETURN_TO_PLAY",
    "UNKNOWN",
}
RETURN_AUTHORITIES = {
    "CLUB",
    "FEDERATION",
    "MANAGER",
    "JOURNALIST",
    "AGGREGATOR",
    "UNKNOWN",
}
CLAIM_DOMAINS = {
    "MEDICAL",
    "TRAINING",
    "SQUAD_SELECTION",
    "MATCH_PARTICIPATION",
    "MANAGER_INTENT",
    "RETURN_TIMELINE",
    "FPL_STATUS",
    "OTHER",
}
GW_AVAILABILITY = {
    "AVAILABLE",
    "LIKELY_AVAILABLE",
    "DOUBT",
    "STRONG_DOUBT",
    "OUT",
    "UNKNOWN",
}
SOURCE_AUTHORITIES = {
    "TIER_A_PRIMARY",
    "TIER_B_REPUTABLE",
    "TIER_C_SPECIALIST",
    "TIER_D_AGGREGATOR",
    "UNKNOWN",
}
_AUTHORITY_RANK = {
    "TIER_A_PRIMARY": 4,
    "TIER_B_REPUTABLE": 3,
    "TIER_C_SPECIALIST": 2,
    "TIER_D_AGGREGATOR": 1,
    "UNKNOWN": 0,
}
_DEFAULT_TTL_HOURS = {
    "FPL_FLAG": 36.0,
    "MANAGER_QUOTE": 96.0,
    "TRAINING_ABSENCE": 72.0,
    "PARTIAL_TRAINING": 120.0,
    "FULL_TRAINING": 120.0,
    "MATCH_APPEARANCE": 336.0,
    "INTERNATIONAL_WITHDRAWAL": 168.0,
    "RETURNED_TO_CLUB": 120.0,
    "RETURN_TO_PLAY": 168.0,
    "WORKLOAD_MANAGEMENT": 120.0,
    "FATIGUE": 96.0,
    "ILLNESS": 96.0,
    "INJURY_EVENT": 336.0,
    "SCAN_RESULT": 336.0,
    "EXPECTED_RETURN": 336.0,
    "OTHER": 72.0,
}
_STRONG_POSITIVE_TYPES = {"FULL_TRAINING", "MATCH_APPEARANCE", "RETURN_TO_PLAY"}
_LEGACY_TYPE_ALIASES = {
    "INTERNATIONAL_APPEARANCE": "MATCH_APPEARANCE",
    "TRAVEL": "RETURNED_TO_CLUB",
    "CLUB_STATEMENT": "OTHER",
    "OFFICIAL_STATUS": "OTHER",
    "NEWS_REPORT": "OTHER",
    "ANALYST_REPORT": "OTHER",
}


def _dt(value: Any) -> datetime | None:
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


def _enum(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in allowed else default


def _tri(value: Any) -> str:
    return _enum(value, TRI, "UNKNOWN")


def _stable_id(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _subject_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _source_authority(raw: Mapping[str, Any]) -> str:
    explicit = _enum(raw.get("source_authority"), SOURCE_AUTHORITIES, "UNKNOWN")
    if explicit != "UNKNOWN":
        return explicit
    source_type = str(raw.get("source_type") or "").strip().upper()
    source_class = str(raw.get("source_class") or "").strip().upper()
    if source_type in {
        "OFFICIAL_CLUB",
        "OFFICIAL_FEDERATION",
        "MANAGER_DIRECT",
        "MEDICAL_STAFF_DIRECT",
        "OFFICIAL_MATCH_RECORD",
    }:
        return "TIER_A_PRIMARY"
    if source_class == "VERIFIED_NEWS" or source_type in {
        "REUTERS",
        "MAJOR_REPORTING",
        "CLUB_CORRESPONDENT",
    }:
        return "TIER_B_REPUTABLE"
    if source_class == "SECONDARY_AVAILABILITY" or source_type in {
        "INJURY_SPECIALIST",
        "FPL_SPECIALIST",
    }:
        return "TIER_C_SPECIALIST"
    if source_class in {"COMMUNITY_SIGNAL", "PUNDIT_CONSENSUS"} or source_type in {
        "AGGREGATOR",
        "SOCIAL",
        "REPOST",
    }:
        return "TIER_D_AGGREGATOR"
    if source_type == "OFFICIAL_FPL":
        # High authority only for the FPL_STATUS domain, not medical diagnosis.
        return "TIER_A_PRIMARY"
    return "UNKNOWN"


def _claim_domain(raw: Mapping[str, Any], evidence_type: str) -> str:
    explicit = _enum(raw.get("claim_domain"), CLAIM_DOMAINS, "OTHER")
    if explicit != "OTHER":
        return explicit
    if evidence_type in {"INJURY_EVENT", "ILLNESS", "SCAN_RESULT"}:
        return "MEDICAL"
    if evidence_type in {
        "TRAINING_ABSENCE",
        "PARTIAL_TRAINING",
        "FULL_TRAINING",
        "RETURN_TO_PLAY",
    }:
        return "TRAINING"
    if evidence_type in {"INTERNATIONAL_WITHDRAWAL", "RETURNED_TO_CLUB"}:
        return "SQUAD_SELECTION"
    if evidence_type == "MATCH_APPEARANCE":
        return "MATCH_PARTICIPATION"
    if evidence_type == "MANAGER_QUOTE":
        return "MANAGER_INTENT"
    if evidence_type == "EXPECTED_RETURN":
        return "RETURN_TIMELINE"
    if evidence_type == "FPL_FLAG":
        return "FPL_STATUS"
    return "OTHER"


def _domain_authority(
    source_authority: str,
    claim_domain: str,
    source_type: str,
) -> str:
    """Contextual authority: a source is not equally authoritative in all domains."""
    if source_type == "OFFICIAL_FPL":
        return "HIGH" if claim_domain == "FPL_STATUS" else "LOW"
    if source_type in {"OFFICIAL_CLUB", "MEDICAL_STAFF_DIRECT"}:
        if claim_domain in {"MEDICAL", "TRAINING", "RETURN_TIMELINE"}:
            return "HIGH"
    if source_type == "OFFICIAL_FEDERATION":
        if claim_domain == "SQUAD_SELECTION":
            return "HIGH"
        if claim_domain == "MEDICAL":
            return "MEDIUM"
    if source_type == "MANAGER_DIRECT":
        if claim_domain in {"MANAGER_INTENT", "SQUAD_SELECTION"}:
            return "HIGH"
        if claim_domain == "MEDICAL":
            return "MEDIUM"
    if source_type == "OFFICIAL_MATCH_RECORD" and claim_domain == "MATCH_PARTICIPATION":
        return "HIGH"
    rank = _AUTHORITY_RANK.get(source_authority, 0)
    return "HIGH" if rank >= 4 else "MEDIUM" if rank >= 2 else "LOW" if rank == 1 else "UNKNOWN"


def _polarity(raw: Mapping[str, Any], evidence_type: str) -> str:
    explicit = _enum(raw.get("evidence_polarity"), EVIDENCE_POLARITIES, "UNKNOWN")
    if explicit != "UNKNOWN":
        return explicit
    if evidence_type == "FPL_FLAG":
        return "NEUTRAL"
    if evidence_type in {"FULL_TRAINING", "RETURN_TO_PLAY", "MATCH_APPEARANCE"}:
        return "REDUCES_CONCERN"
    if evidence_type in {
        "INJURY_EVENT",
        "ILLNESS",
        "TRAINING_ABSENCE",
        "SCAN_RESULT",
    }:
        return "SUPPORTS_CONCERN"
    if evidence_type == "PARTIAL_TRAINING":
        return "REDUCES_CONCERN"
    if evidence_type == "INTERNATIONAL_WITHDRAWAL":
        # Withdrawal itself is operational fact, not medical confirmation.
        return "UNKNOWN"
    if evidence_type == "WORKLOAD_MANAGEMENT":
        return "NEUTRAL"
    return "UNKNOWN"


def _explicit_no_is_supportable(raw: Mapping[str, Any]) -> bool:
    if raw.get("no_injury_explicit") is True:
        return True
    normalized = str(raw.get("normalized_claim") or "").strip().upper()
    return normalized in {
        "NO_INJURY",
        "TACTICAL_SUBSTITUTION_NO_INJURY",
        "WORKLOAD_NO_PHYSICAL_ISSUE",
        "NO_PHYSICAL_ISSUE",
    }


def _normalized_evidence_type(raw: Mapping[str, Any]) -> tuple[str, str]:
    raw_type = str(raw.get("evidence_type") or "OTHER").strip().upper()
    normalized = _LEGACY_TYPE_ALIASES.get(raw_type, raw_type)
    if normalized not in EVIDENCE_TYPES:
        normalized = "OTHER"
    return raw_type, normalized


def normalize_injury_evidence(
    evidence: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    """Normalize atomic claims while preserving raw facts and provenance."""
    as_of_dt = _dt(as_of)
    if as_of_dt is None:
        raise ValueError("as_of must be an ISO-8601 timestamp")

    rows: list[dict[str, Any]] = []
    root_first: dict[str, str] = {}
    for index, item in enumerate(evidence or ()):
        if not isinstance(item, Mapping):
            continue
        raw = dict(item)
        raw_type, evidence_type = _normalized_evidence_type(raw)
        observed = _dt(raw.get("observed_at") or raw.get("timestamp"))
        event_time = _dt(raw.get("event_time") or raw.get("timestamp") or raw.get("observed_at"))
        source = str(raw.get("source") or raw.get("source_id") or "UNKNOWN").strip()
        source_type = str(raw.get("source_type") or "").strip().upper() or "UNKNOWN"
        source_authority = _source_authority(raw)
        claim_domain = _claim_domain(raw, evidence_type)
        domain_authority = _domain_authority(source_authority, claim_domain, source_type)
        raw_claim = raw.get("raw_claim")
        if raw_claim is None:
            raw_claim = raw.get("source_quote_or_fact")
        if raw_claim is None:
            raw_claim = raw.get("summary")
        if raw_claim is None:
            raw_claim = raw.get("reason")
        normalized_claim = raw.get("normalized_claim")
        if normalized_claim is None:
            normalized_claim = raw.get("state_hint")
        if normalized_claim is None:
            normalized_claim = raw.get("availability")
        normalized_claim = str(normalized_claim or "UNKNOWN").strip().upper()

        injury_confirmed = _tri(raw.get("injury_confirmed"))
        semantic_warnings: list[str] = []
        if injury_confirmed == "NO" and not _explicit_no_is_supportable(raw):
            injury_confirmed = "UNKNOWN"
            semantic_warnings.append("STRICT_NO_DOWNGRADED_TO_UNKNOWN")

        mechanism = _enum(raw.get("injury_mechanism"), INJURY_MECHANISMS, "UNKNOWN")
        if evidence_type == "ILLNESS":
            mechanism = "ILLNESS"
        elif evidence_type == "FATIGUE":
            mechanism = "FATIGUE"
        elif evidence_type == "WORKLOAD_MANAGEMENT":
            mechanism = "WORKLOAD"

        body_part_raw = raw.get("body_part")
        if body_part_raw in (None, ""):
            body_part = None if injury_confirmed == "NO" else "UNKNOWN"
        else:
            body_part = str(body_part_raw).strip().upper()

        training_status = _enum(raw.get("training_status"), TRAINING_STATUSES, "UNKNOWN")
        if evidence_type == "FULL_TRAINING":
            training_status = "FULL"
        elif evidence_type == "PARTIAL_TRAINING":
            training_status = "PARTIAL"
        elif evidence_type == "TRAINING_ABSENCE":
            training_status = "ABSENT"

        match_status = _enum(raw.get("match_status"), MATCH_STATUSES, "UNKNOWN")
        minutes = raw.get("minutes")
        try:
            minutes_f = float(minutes) if minutes is not None else None
        except (TypeError, ValueError):
            minutes_f = None
        if evidence_type == "MATCH_APPEARANCE" and match_status == "UNKNOWN":
            match_status = "PLAYED" if (minutes_f or 0.0) > 0 else "UNKNOWN"

        manager_severity = _enum(
            raw.get("manager_severity"), MANAGER_SEVERITIES, "UNKNOWN"
        )
        club_assessment = _enum(
            raw.get("club_assessment"), CLUB_ASSESSMENTS, "UNKNOWN"
        )
        expected_return = raw.get("expected_return")
        expected_return_source = raw.get("expected_return_source")
        expected_return_authority = _enum(
            raw.get("expected_return_authority"), RETURN_AUTHORITIES, "UNKNOWN"
        )
        if expected_return not in (None, "", "UNKNOWN") and not expected_return_source:
            semantic_warnings.append("EXPECTED_RETURN_WITHOUT_PROVENANCE")
            expected_return = "UNKNOWN"
            expected_return_authority = "UNKNOWN"

        fpl_flag = raw.get("fpl_flag")
        try:
            fpl_flag_i = int(fpl_flag) if fpl_flag is not None else None
        except (TypeError, ValueError):
            fpl_flag_i = None
        if fpl_flag_i not in {0, 25, 50, 75, 100, None}:
            fpl_flag_i = None
            semantic_warnings.append("INVALID_FPL_FLAG_IGNORED")

        root_source_id = str(raw.get("root_source_id") or source or "UNKNOWN")
        root_source_type = str(raw.get("root_source_type") or source_type)
        root_claim_id = str(
            raw.get("root_claim_id")
            or _stable_id(
                root_source_id,
                _iso(event_time),
                evidence_type,
                normalized_claim,
                raw_claim,
            )
        )
        claim_id = str(
            raw.get("claim_id")
            or _stable_id(
                source,
                _iso(observed),
                root_claim_id,
                raw.get("source_url"),
            )
        )
        is_republication = bool(raw.get("is_republication"))
        dedup_from = root_first.get(root_claim_id)
        if dedup_from is None and not is_republication:
            root_first[root_claim_id] = claim_id
        elif dedup_from is None:
            dedup_from = root_claim_id
        independent = dedup_from is None and not is_republication

        ttl_raw = raw.get("ttl_hours")
        try:
            ttl = float(ttl_raw) if ttl_raw is not None else _DEFAULT_TTL_HOURS[evidence_type]
        except (TypeError, ValueError):
            ttl = _DEFAULT_TTL_HOURS[evidence_type]
        expires = observed + timedelta(hours=ttl) if observed else None
        stale = observed is None or bool(expires and as_of_dt > expires)

        explicit_availability = str(raw.get("availability") or "").strip().upper()
        explicit_target_out = bool(raw.get("explicit_target_unavailable"))
        if (
            explicit_availability in {"OUT", "UNAVAILABLE"}
            and domain_authority == "HIGH"
            and claim_domain in {
                "MEDICAL",
                "SQUAD_SELECTION",
                "MANAGER_INTENT",
                "TRAINING",
            }
        ):
            explicit_target_out = True

        row = {
            "index": index,
            "player_id": raw.get("player_id") or raw.get("element"),
            "player_name": raw.get("player_name") or raw.get("subject"),
            "claim_id": claim_id,
            "root_claim_id": root_claim_id,
            "root_source_id": root_source_id,
            "root_source_type": root_source_type,
            "is_republication": is_republication,
            "independent_root_claim": independent,
            "deduplicated_from_claim_id": dedup_from,
            "event_time": _iso(event_time),
            "observed_at": _iso(observed),
            "source": source or "UNKNOWN",
            "source_url": raw.get("source_url"),
            "source_type": source_type,
            "source_authority": source_authority,
            "claim_domain": claim_domain,
            "claim_domain_authority": domain_authority,
            "raw_claim": raw_claim,
            "normalized_claim": normalized_claim,
            "raw_evidence_type": raw_type,
            "evidence_type": evidence_type,
            "evidence_polarity": _polarity(raw, evidence_type),
            "injury_confirmed": injury_confirmed,
            "injury_mechanism": mechanism,
            "body_part": body_part,
            "withdrawn_from_squad": _tri(raw.get("withdrawn_from_squad")),
            "returned_to_club": _tri(raw.get("returned_to_club")),
            "training_status": training_status,
            "match_status": match_status,
            "minutes": minutes_f,
            "manager_severity": manager_severity,
            "manager_availability_language": str(
                raw.get("manager_availability_language") or "UNKNOWN"
            ).strip().upper(),
            "club_assessment": club_assessment,
            "expected_return": expected_return if expected_return not in (None, "") else "UNKNOWN",
            "expected_return_source": expected_return_source,
            "expected_return_authority": expected_return_authority,
            "fpl_flag": fpl_flag_i,
            "fpl_flag_reason": raw.get("fpl_flag_reason"),
            "target_gw": raw.get("target_gw"),
            "target_fixture_id": raw.get("target_fixture_id"),
            "availability_hint": explicit_availability or None,
            "explicit_target_unavailable": explicit_target_out,
            "international": bool(
                raw.get("international")
                or raw_type == "INTERNATIONAL_APPEARANCE"
                or evidence_type == "INTERNATIONAL_WITHDRAWAL"
            ),
            "travel_return": bool(raw.get("travel_return")),
            "ttl_hours": ttl,
            "expires_at": _iso(expires),
            "stale": stale,
            "semantic_warnings": semantic_warnings,
            "diagnosis_inferred": False,
        }
        rows.append(row)
    return rows


def _target_relevant(
    row: Mapping[str, Any],
    *,
    target_gw: int | None,
    target_fixture_id: Any,
) -> bool:
    row_gw = row.get("target_gw")
    if row_gw not in (None, "") and target_gw is not None:
        try:
            if int(row_gw) != int(target_gw):
                return False
        except (TypeError, ValueError):
            return False
    row_fixture = row.get("target_fixture_id")
    if row_fixture not in (None, "") and target_fixture_id not in (None, ""):
        if str(row_fixture) != str(target_fixture_id):
            return False
    return True


def _time_key(row: Mapping[str, Any]) -> datetime:
    return _dt(row.get("event_time") or row.get("observed_at")) or datetime.min.replace(
        tzinfo=timezone.utc
    )


def _is_strong_positive(row: Mapping[str, Any]) -> bool:
    if row.get("evidence_type") in _STRONG_POSITIVE_TYPES:
        if row.get("evidence_type") != "MATCH_APPEARANCE":
            return True
        return (row.get("minutes") or 0.0) > 0.0
    return row.get("club_assessment") in {"CLEARED", "RETURN_TO_PLAY"}


def _is_adverse(row: Mapping[str, Any]) -> bool:
    if row.get("evidence_polarity") == "SUPPORTS_CONCERN":
        return True
    if row.get("injury_confirmed") == "YES":
        return True
    if row.get("training_status") == "ABSENT":
        return True
    if row.get("manager_severity") in {"DOUBT", "SERIOUS"}:
        return True
    if row.get("explicit_target_unavailable") is True:
        return True
    return False


def _mark_field_supersession(rows: list[dict[str, Any]]) -> None:
    """Supersede only target-availability relevance, never historical medical facts."""
    positives = [row for row in rows if _is_strong_positive(row)]
    adverses = [row for row in rows if _is_adverse(row)]
    latest_positive = max(positives, key=_time_key) if positives else None
    latest_adverse = max(adverses, key=_time_key) if adverses else None
    for row in rows:
        row["availability_superseded"] = False
        row["availability_superseded_by_claim_id"] = None
        if (
            _is_adverse(row)
            and latest_positive is not None
            and _time_key(latest_positive) > _time_key(row)
        ):
            row["availability_superseded"] = True
            row["availability_superseded_by_claim_id"] = latest_positive["claim_id"]
        elif (
            row.get("evidence_polarity") == "REDUCES_CONCERN"
            and latest_adverse is not None
            and _time_key(latest_adverse) > _time_key(row)
        ):
            row["availability_superseded"] = True
            row["availability_superseded_by_claim_id"] = latest_adverse["claim_id"]


def derive_gw_availability(
    evidence: Sequence[Mapping[str, Any]],
    *,
    target_gw: int | None,
    target_fixture_id: Any = None,
    derived_at: str,
    evidence_cutoff_at: str | None = None,
) -> dict[str, Any]:
    """Resolve categorical target-fixture availability; never output P(start)."""
    derived_dt = _dt(derived_at)
    cutoff_dt = _dt(evidence_cutoff_at or derived_at)
    if derived_dt is None or cutoff_dt is None:
        raise ValueError("derived_at/evidence_cutoff_at must be ISO-8601 timestamps")

    normalized = normalize_injury_evidence(evidence, as_of=_iso(cutoff_dt) or derived_at)
    eligible: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    for row in normalized:
        observed = _dt(row.get("observed_at"))
        if observed is None or observed > cutoff_dt:
            historical.append(row)
            continue
        if not _target_relevant(
            row, target_gw=target_gw, target_fixture_id=target_fixture_id
        ):
            historical.append(row)
            continue
        eligible.append(row)

    _mark_field_supersession(eligible)
    active = [
        row
        for row in eligible
        if not row.get("stale")
        and not row.get("availability_superseded")
        and row.get("independent_root_claim") is True
    ]
    superseded = [
        row
        for row in eligible
        if row.get("availability_superseded") or row.get("stale")
    ]
    republications = [
        row for row in eligible if row.get("independent_root_claim") is not True
    ]

    hard_out = [
        row for row in active
        if row.get("explicit_target_unavailable") is True
        and row.get("claim_domain_authority") == "HIGH"
    ]
    strong_positive = [row for row in active if _is_strong_positive(row)]
    reassuring = [
        row for row in active
        if row.get("evidence_polarity") == "REDUCES_CONCERN"
        or row.get("manager_severity") in {"NONE", "MINOR", "NOT_SERIOUS"}
        or row.get("club_assessment") in {
            "CLEARED",
            "RETURN_TO_TRAINING",
            "RETURN_TO_PLAY",
        }
    ]
    confirmed_injury = [
        row for row in active
        if row.get("injury_confirmed") == "YES"
    ]
    serious = [
        row for row in active
        if row.get("manager_severity") == "SERIOUS"
        or row.get("club_assessment") == "REHAB"
        or row.get("training_status") == "ABSENT"
    ]
    doubts = [
        row for row in active
        if _is_adverse(row)
        or row.get("manager_availability_language") in {
            "ASSESS",
            "LATE_DECISION",
            "UNLIKELY",
        }
    ]
    workload_only = [
        row for row in active
        if row.get("evidence_type") in {"WORKLOAD_MANAGEMENT", "FATIGUE"}
    ]
    workload_explicit_no_injury = [
        row for row in workload_only
        if row.get("injury_confirmed") == "NO"
    ]
    withdrawal_unknown = [
        row for row in active
        if row.get("evidence_type") == "INTERNATIONAL_WITHDRAWAL"
        and row.get("injury_confirmed") == "UNKNOWN"
    ]
    fpl_only = bool(active) and all(
        row.get("claim_domain") == "FPL_STATUS" for row in active
    )

    support_roots = {
        row["root_claim_id"] for row in active
        if row.get("evidence_polarity") == "SUPPORTS_CONCERN"
    }
    reduce_roots = {
        row["root_claim_id"] for row in active
        if row.get("evidence_polarity") == "REDUCES_CONCERN"
    }
    conflicting_count = min(len(support_roots), len(reduce_roots))

    if hard_out:
        gw_state = "OUT"
        reason = "EXPLICIT_TARGET_GW_UNAVAILABLE"
        confidence = "HIGH"
    elif strong_positive and not doubts:
        gw_state = "AVAILABLE"
        reason = "CURRENT_FULL_TRAINING_RETURN_OR_MATCH_PARTICIPATION"
        confidence = "HIGH"
    elif workload_explicit_no_injury and not doubts:
        gw_state = "LIKELY_AVAILABLE"
        reason = "WORKLOAD_MANAGEMENT_WITH_EXPLICIT_NO_INJURY"
        confidence = "MEDIUM"
    elif confirmed_injury and serious:
        gw_state = "STRONG_DOUBT"
        reason = "CONFIRMED_INJURY_WITH_ACTIVE_ABSENCE_OR_REHAB"
        confidence = "MEDIUM"
    elif confirmed_injury:
        gw_state = "DOUBT"
        reason = "CONFIRMED_INJURY_AVAILABILITY_UNRESOLVED"
        confidence = "MEDIUM"
    elif doubts and reassuring:
        gw_state = "DOUBT"
        reason = "CURRENT_CONFLICTING_AVAILABILITY_EVIDENCE"
        confidence = "LOW"
    elif doubts:
        gw_state = "DOUBT"
        reason = "CURRENT_AVAILABILITY_CONCERN_UNRESOLVED"
        confidence = "LOW"
    elif reassuring:
        gw_state = "LIKELY_AVAILABLE"
        reason = "REASSURING_CURRENT_EVIDENCE_WITHOUT_FULL_CLEARANCE"
        confidence = "MEDIUM"
    elif withdrawal_unknown:
        gw_state = "UNKNOWN"
        reason = "INTERNATIONAL_WITHDRAWAL_WITHOUT_MEDICAL_CONFIRMATION"
        confidence = "LOW"
    elif fpl_only:
        gw_state = "UNKNOWN"
        reason = "FPL_STATUS_OBSERVATION_IS_NOT_MEDICAL_OR_START_PROBABILITY"
        confidence = "LOW"
    else:
        gw_state = "UNKNOWN"
        reason = "INSUFFICIENT_TARGET_SPECIFIC_EVIDENCE"
        confidence = "LOW"

    latest = max(active, key=_time_key) if active else None
    highest = max(
        active,
        key=lambda row: (
            _AUTHORITY_RANK.get(str(row.get("source_authority")), 0),
            _time_key(row),
        ),
        default=None,
    )
    latest_training = max(
        (
            row for row in active
            if row.get("training_status") != "UNKNOWN"
        ),
        key=_time_key,
        default=None,
    )
    latest_manager = max(
        (
            row for row in active
            if row.get("manager_severity") != "UNKNOWN"
            or row.get("manager_availability_language") != "UNKNOWN"
        ),
        key=_time_key,
        default=None,
    )

    model_features = {
        "gw_availability": gw_state,
        "explicit_out_for_target": bool(hard_out),
        "training_status": (
            latest_training.get("training_status") if latest_training else "UNKNOWN"
        ),
        "manager_severity": (
            latest_manager.get("manager_severity") if latest_manager else "UNKNOWN"
        ),
        "manager_availability_language": (
            latest_manager.get("manager_availability_language")
            if latest_manager else "UNKNOWN"
        ),
        "confirmed_injury_active": bool(confirmed_injury),
        "workload_management_only": bool(
            workload_only
            and not confirmed_injury
            and not [row for row in active if _is_adverse(row)]
        ),
        "full_training_or_return": bool(strong_positive),
        "fpl_flag_observed": any(
            row.get("evidence_type") == "FPL_FLAG" for row in eligible
        ),
        "fpl_flag_used_as_probability": False,
        "availability_confidence_used_as_probability": False,
    }

    return {
        "contract": "V12_TARGET_AWARE_AVAILABILITY_EVIDENCE_V1",
        "target_gw": target_gw,
        "target_fixture_id": target_fixture_id,
        "derived_at": _iso(derived_dt),
        "evidence_cutoff_at": _iso(cutoff_dt),
        "gw_availability": gw_state,
        "gw_availability_confidence": confidence,
        "availability_derivation_reason": reason,
        "active_evidence": active,
        "superseded_evidence": superseded,
        "republication_evidence": republications,
        "historical_evidence": historical,
        "model_features": model_features,
        "observability": {
            "latest_evidence_timestamp": (
                latest.get("observed_at") if latest else None
            ),
            "active_evidence_count": len(active),
            "highest_authority_source": (
                {
                    "source": highest.get("source"),
                    "source_authority": highest.get("source_authority"),
                    "claim_domain": highest.get("claim_domain"),
                    "claim_domain_authority": highest.get(
                        "claim_domain_authority"
                    ),
                }
                if highest else None
            ),
            "conflicting_evidence_count": conflicting_count,
            "stale_evidence_count": sum(
                1 for row in eligible if row.get("stale")
            ),
            "republication_count": len(republications),
            "independent_root_claim_count": len(
                {row["root_claim_id"] for row in active}
            ),
            "source_retrieval_failures": [],
        },
        "governance": {
            "target_aware": True,
            "claim_aware": True,
            "field_specific_supersession": True,
            "historical_medical_claims_preserved": True,
            "strict_no_semantics": True,
            "root_claim_deduplication": True,
            "domain_specific_authority": True,
            "fpl_flag_is_observation_not_probability": True,
            "gw_availability_is_categorical": True,
            "gw_availability_is_not_startability": True,
            "gw_availability_confidence_is_not_pstart": True,
            "pstart_owner": "V12_PLAYER_MINUTES",
        },
    }


def _exact_player_map(
    bootstrap: Mapping[str, Any],
) -> tuple[dict[str, int], dict[int, dict[str, Any]]]:
    by_key: dict[str, list[int]] = {}
    by_id: dict[int, dict[str, Any]] = {}
    for raw in bootstrap.get("elements") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            element = int(raw.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if element <= 0:
            continue
        by_id[element] = dict(raw)
        names = {
            str(raw.get("web_name") or "").strip(),
            str(raw.get("first_name") or "").strip(),
            str(raw.get("second_name") or "").strip(),
            " ".join(
                part for part in (
                    str(raw.get("first_name") or "").strip(),
                    str(raw.get("second_name") or "").strip(),
                )
                if part
            ),
        }
        for name in names:
            key = _subject_key(name)
            if key:
                by_key.setdefault(key, []).append(element)
    exact = {
        key: values[0]
        for key, values in by_key.items()
        if len(set(values)) == 1
    }
    return exact, by_id


def build_availability_evidence_by_player(
    bootstrap: Mapping[str, Any],
    report_time_evidence: Mapping[str, Any] | None,
    *,
    report_timestamp: str,
    target_gw: int | None,
) -> dict[int, list[dict[str, Any]]]:
    """Adapt existing factual/report-time surfaces into atomic evidence claims.

    Free text is preserved but never parsed into a diagnosis/body part/timeline.
    Optional structured availability fields may accompany report-time signals.
    """
    exact_names, by_id = _exact_player_map(bootstrap)
    out: dict[int, list[dict[str, Any]]] = {element: [] for element in by_id}

    for element, player in by_id.items():
        chance = player.get("chance_of_playing_next_round")
        news = str(player.get("news") or "").strip()
        status = str(player.get("status") or "").strip().lower()
        if chance is not None or news or status not in {"", "a"}:
            out[element].append(
                {
                    "player_id": element,
                    "player_name": player.get("web_name"),
                    "event_time": player.get("news_added") or report_timestamp,
                    "observed_at": player.get("news_added") or report_timestamp,
                    "source": "Official FPL",
                    "source_type": "OFFICIAL_FPL",
                    "source_authority": "TIER_A_PRIMARY",
                    "source_url": None,
                    "evidence_type": "FPL_FLAG",
                    "claim_domain": "FPL_STATUS",
                    "evidence_polarity": "NEUTRAL",
                    "raw_claim": news or f"FPL status={status or 'UNKNOWN'}",
                    "normalized_claim": "FPL_STATUS_OBSERVATION",
                    "injury_confirmed": "UNKNOWN",
                    "fpl_flag": chance,
                    "fpl_flag_reason": news or None,
                    "target_gw": target_gw,
                    "root_source_id": "official_fpl_bootstrap",
                    "root_source_type": "OFFICIAL_FPL",
                }
            )
        if status == "s":
            # Suspension is an operational availability fact, not an injury.
            out[element].append(
                {
                    "player_id": element,
                    "player_name": player.get("web_name"),
                    "event_time": player.get("news_added") or report_timestamp,
                    "observed_at": player.get("news_added") or report_timestamp,
                    "source": "Official FPL",
                    "source_type": "OFFICIAL_FPL",
                    "source_authority": "TIER_A_PRIMARY",
                    "evidence_type": "OTHER",
                    "claim_domain": "SQUAD_SELECTION",
                    "evidence_polarity": "SUPPORTS_CONCERN",
                    "raw_claim": news or "Official FPL suspension status",
                    "normalized_claim": "SUSPENDED",
                    "injury_confirmed": "NO",
                    "no_injury_explicit": True,
                    "availability": "OUT",
                    "explicit_target_unavailable": True,
                    "target_gw": target_gw,
                    "root_source_id": "official_fpl_bootstrap",
                    "root_source_type": "OFFICIAL_FPL",
                }
            )

    payload = dict(report_time_evidence or {})
    if payload.get("contract") != "report_time_evidence_v1":
        return {key: value for key, value in out.items() if value}

    try:
        from src.engines.report_time_intelligence import validate_evidence

        now = _dt(report_timestamp)
        validation = validate_evidence(
            payload,
            now=now if now is not None else datetime.now(timezone.utc),
        )
        accepted = validation.get("accepted") or []
    except (ImportError, OSError, ValueError, TypeError):
        accepted = []

    for signal in accepted:
        if not isinstance(signal, Mapping) or signal.get("current") is not True:
            continue
        subject_key = _subject_key(signal.get("subject"))
        element = exact_names.get(subject_key)
        if element is None:
            continue
        source_class = str(signal.get("source_class") or "").upper()
        if source_class not in {"VERIFIED_NEWS", "SECONDARY_AVAILABILITY"}:
            continue

        structured = signal.get("availability_evidence")
        structured = dict(structured) if isinstance(structured, Mapping) else {}
        evidence_type = str(
            structured.get("evidence_type")
            or signal.get("evidence_type")
            or "OTHER"
        ).upper()
        stance = str(signal.get("stance") or "").upper()
        polarity = (
            structured.get("evidence_polarity")
            or signal.get("evidence_polarity")
            or ("SUPPORTS_CONCERN" if stance == "INJURY_RISK" else "UNKNOWN")
        )
        authority = (
            "TIER_B_REPUTABLE"
            if source_class == "VERIFIED_NEWS"
            else "TIER_C_SPECIALIST"
        )
        claim = {
            **structured,
            "player_id": element,
            "player_name": by_id[element].get("web_name"),
            "event_time": structured.get("event_time") or signal.get("observed_at"),
            "observed_at": signal.get("observed_at"),
            "source": signal.get("source_id"),
            "source_url": signal.get("source_url"),
            "source_class": source_class,
            "source_type": structured.get("source_type") or source_class,
            "source_authority": structured.get("source_authority") or authority,
            "evidence_type": evidence_type,
            "claim_domain": structured.get("claim_domain") or signal.get("claim_domain"),
            "evidence_polarity": polarity,
            "raw_claim": structured.get("raw_claim") or signal.get("summary"),
            "normalized_claim": (
                structured.get("normalized_claim")
                or signal.get("normalized_claim")
                or stance
                or "UNKNOWN"
            ),
            "injury_confirmed": structured.get(
                "injury_confirmed",
                signal.get("injury_confirmed", "UNKNOWN"),
            ),
            "body_part": structured.get("body_part", signal.get("body_part")),
            "withdrawn_from_squad": structured.get(
                "withdrawn_from_squad",
                signal.get("withdrawn_from_squad", "UNKNOWN"),
            ),
            "returned_to_club": structured.get(
                "returned_to_club",
                signal.get("returned_to_club", "UNKNOWN"),
            ),
            "training_status": structured.get(
                "training_status",
                signal.get("training_status", "UNKNOWN"),
            ),
            "manager_severity": structured.get(
                "manager_severity",
                signal.get("manager_severity", "UNKNOWN"),
            ),
            "manager_availability_language": structured.get(
                "manager_availability_language",
                signal.get("manager_availability_language", "UNKNOWN"),
            ),
            "club_assessment": structured.get(
                "club_assessment",
                signal.get("club_assessment", "UNKNOWN"),
            ),
            "expected_return": structured.get(
                "expected_return",
                signal.get("expected_return", "UNKNOWN"),
            ),
            "expected_return_source": structured.get(
                "expected_return_source",
                signal.get("expected_return_source"),
            ),
            "expected_return_authority": structured.get(
                "expected_return_authority",
                signal.get("expected_return_authority", "UNKNOWN"),
            ),
            "target_gw": structured.get("target_gw", target_gw),
            "target_fixture_id": structured.get("target_fixture_id"),
            "root_source_id": (
                structured.get("root_source_id")
                or signal.get("root_family")
                or signal.get("source_id")
            ),
            "root_source_type": structured.get("root_source_type") or source_class,
            "is_republication": bool(
                structured.get("is_republication")
                or signal.get("is_republication")
            ),
            "no_injury_explicit": bool(
                structured.get("no_injury_explicit")
                or signal.get("no_injury_explicit")
            ),
            "availability": structured.get("availability") or signal.get("availability"),
            "explicit_target_unavailable": bool(
                structured.get("explicit_target_unavailable")
                or signal.get("explicit_target_unavailable")
            ),
        }
        out[element].append(claim)

    return {key: value for key, value in out.items() if value}
