"""Freshness and provenance contracts for V12 report layers.

The helpers are deliberately fail-closed: absent timestamps or evidence are
classified as UNKNOWN/UNAVAILABLE and never silently treated as current.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

FRESH = "FRESH"
AGING = "AGING"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"
FRESHNESS_STATES = frozenset({FRESH, AGING, STALE, UNAVAILABLE, UNKNOWN})
REQUIRED_SECTION_IDS = ("S04", "S08", "S15", "S15B", "S17", "S18", "S19")
_PRIVATE_MARKERS = ("token", "cookie", "password", "credential", "authorization", "set-cookie")


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def classify_freshness(
    observed_at: Any,
    *,
    ttl_hours: float,
    now: Any = None,
    unavailable: bool = False,
) -> str:
    """Classify one source with a type-specific TTL."""
    if unavailable:
        return UNAVAILABLE
    observed = _parse(observed_at)
    current = _parse(now) or datetime.now(timezone.utc)
    if observed is None:
        return UNKNOWN
    age_hours = (current - observed).total_seconds() / 3600
    if age_hours < 0:
        return UNKNOWN
    if age_hours <= ttl_hours:
        return FRESH
    if age_hours <= ttl_hours * 2:
        return AGING
    return STALE


def build_source_provenance(
    *,
    source_id: str,
    source_type: str,
    source_authority: str,
    source_reference: str | None,
    fetched_at: Any,
    published_at: Any = None,
    observed_at: Any = None,
    evidence_cutoff_at: Any = None,
    root_source_id: str | None = None,
    is_republication: bool = False,
    ttl_hours: float = 24,
    now: Any = None,
    unavailable: bool = False,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "source_authority": source_authority,
        "source_url": source_reference,
        "source_reference": source_reference,
        "fetched_at": fetched_at,
        "published_at": published_at,
        "observed_at": observed_at,
        "freshness_state": classify_freshness(
            observed_at or fetched_at, ttl_hours=ttl_hours, now=now, unavailable=unavailable
        ),
        "evidence_cutoff_at": evidence_cutoff_at,
        "root_source_id": root_source_id or source_id,
        "is_republication": bool(is_republication),
    }


def build_dataset_provenance(
    *,
    dataset_id: str,
    dataset_version: str,
    generated_at: Any,
    coverage_start: Any,
    coverage_end: Any,
    target_gw: int | str | None,
    target_fixture_ids: Sequence[str] | None,
    source_ids: Sequence[str],
    schema_version: str,
    evidence_cutoff_at: Any,
    ttl_hours: float = 24,
    now: Any = None,
    unavailable: bool = False,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "generated_at": generated_at,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "target_gw": target_gw,
        "target_fixture_ids": list(target_fixture_ids or []),
        "source_ids": sorted(set(source_ids)),
        "schema_version": schema_version,
        "freshness_state": classify_freshness(
            generated_at, ttl_hours=ttl_hours, now=now, unavailable=unavailable
        ),
        "evidence_cutoff_at": evidence_cutoff_at,
    }


def build_player_evidence(
    *,
    player_id: str | int,
    target_gw: int | str | None,
    target_fixture_id: str | int | None,
    raw_claim: Any,
    normalized_claim: Any,
    claim_domain: str,
    evidence_polarity: str,
    derived_at: Any,
    evidence_cutoff_at: Any,
    source_id: str,
    ttl_hours: float = 24,
    now: Any = None,
    unavailable: bool = False,
) -> dict[str, Any]:
    return {
        "player_id": player_id,
        "target_gw": target_gw,
        "target_fixture_id": target_fixture_id,
        "raw_claim": raw_claim,
        "normalized_claim": normalized_claim,
        "claim_domain": claim_domain,
        "evidence_polarity": evidence_polarity,
        "derived_at": derived_at,
        "evidence_cutoff_at": evidence_cutoff_at,
        "source_id": source_id,
        "freshness_state": classify_freshness(
            derived_at, ttl_hours=ttl_hours, now=now, unavailable=unavailable
        ),
    }


def _walk(value: Any, key: str = ""):
    if isinstance(value, Mapping):
        for name, child in value.items():
            yield from _walk(child, str(name))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _walk(child, key)
    else:
        yield key, value


def _values(payload: Mapping[str, Any], names: set[str]) -> list[Any]:
    return [value for key, value in _walk(payload) if key.lower() in names and value not in (None, "")]


def _privacy_safe(payload: Any) -> bool:
    for key, value in _walk(payload):
        if any(marker in key.lower() for marker in _PRIVATE_MARKERS):
            return False
        if isinstance(value, str) and any(marker in value.lower() for marker in _PRIVATE_MARKERS):
            return False
    return True


def build_section_provenance(
    *,
    section_id: str,
    report_kind: str,
    target_gw: int | str | None,
    target_fixture_ids: Sequence[str] | None,
    source_ids: Sequence[str],
    dataset_ids: Sequence[str],
    player_ids: Sequence[str | int],
    evidence_cutoff_at: Any,
    freshness_summary: Mapping[str, int],
    degradation_state: str,
) -> dict[str, Any]:
    result = {
        "section_id": section_id,
        "report_kind": report_kind,
        "target_gw": target_gw,
        "target_fixture_ids": list(target_fixture_ids or []),
        "source_ids": sorted(set(str(item) for item in source_ids)),
        "dataset_ids": sorted(set(str(item) for item in dataset_ids)),
        "player_ids": sorted(set(str(item) for item in player_ids)),
        "evidence_cutoff_at": evidence_cutoff_at,
        "freshness_summary": dict(freshness_summary),
        "degradation_state": degradation_state,
    }
    if not _privacy_safe(result):
        raise ValueError("PROVENANCE_PRIVACY_VIOLATION")
    return result


def validate_section_provenance(
    provenance: Mapping[str, Any], *, report_timestamp: Any = None
) -> dict[str, Any]:
    state = str(provenance.get("degradation_state") or "UNKNOWN").upper()
    freshness = dict(provenance.get("freshness_summary") or {})
    cutoff = _parse(provenance.get("evidence_cutoff_at"))
    report_time = _parse(report_timestamp)
    errors: list[str] = []
    if state not in {"COMPLETE", "DEGRADED", UNAVAILABLE, UNKNOWN}:
        errors.append("INVALID_DEGRADATION_STATE")
    if cutoff is not None and report_time is not None and cutoff > report_time:
        errors.append("EVIDENCE_CUTOFF_AFTER_REPORT")
    if any(str(key).upper() not in FRESHNESS_STATES for key in freshness):
        errors.append("INVALID_FRESHNESS_STATE")
    if not _privacy_safe(provenance):
        errors.append("PROVENANCE_PRIVACY_VIOLATION")
    return {"valid": not errors, "errors": errors}


def attach_report_provenance(
    sections: Mapping[str, Any],
    *,
    report_kind: str,
    target_gw: int | str | None,
    report_timestamp: Any,
    target_fixture_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Attach provenance to required report sections without exposing payloads."""
    output = dict(sections)
    for section_id in REQUIRED_SECTION_IDS:
        section = output.get(section_id)
        if not isinstance(section, Mapping):
            continue
        content = dict(section.get("content") or {})
        freshness_values = [
            str(value).upper()
            for key, value in _walk(content)
            if key.lower() in {"freshness_state", "freshness", "state"}
            and str(value).upper() in FRESHNESS_STATES
        ]
        summary = {state: freshness_values.count(state) for state in FRESHNESS_STATES}
        source_ids = [str(value) for value in _values(content, {"source_id", "root_source_id"})]
        dataset_ids = [str(value) for value in _values(content, {"dataset_id"})]
        player_ids = _values(content, {"player_id", "element_id"})
        cutoff_values = _values(content, {"evidence_cutoff_at", "cutoff_at"})
        cutoff = cutoff_values[0] if cutoff_values else None
        degradation = "COMPLETE"
        if not cutoff or summary.get(UNKNOWN) or summary.get(UNAVAILABLE) or summary.get(STALE):
            degradation = "DEGRADED"
        provenance = build_section_provenance(
            section_id=section_id,
            report_kind=report_kind,
            target_gw=target_gw,
            target_fixture_ids=target_fixture_ids,
            source_ids=source_ids,
            dataset_ids=dataset_ids,
            player_ids=player_ids,
            evidence_cutoff_at=cutoff,
            freshness_summary=summary,
            degradation_state=degradation,
        )
        content["provenance"] = provenance
        content["provenance_validation"] = validate_section_provenance(
            provenance, report_timestamp=report_timestamp
        )
        output[section_id] = {**dict(section), "content": content}
    return output
