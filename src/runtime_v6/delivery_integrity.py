from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .temporal import (
    DEFAULT_RUNTIME_TIMEZONE,
    TemporalError,
    age_seconds,
    parse_timestamp,
)

ARTIFACT_SCOPES = (
    "bootstrap",
    "fixtures",
    "price_predictor",
    "personal",
    "icon_standings",
    "submitted_picks",
    "live",
    "external_provider",
)

HEALTHY_V6_SCOPE_STATES = frozenset({"CURRENT", "PASS", "ADEQUATE"})
RETRIEVAL_RECOVERY_CONDITIONS = frozenset(
    {
        "CONNECTOR_TRUNCATED",
        "PAYLOAD_TOO_LARGE",
        "FIRST_READ_PARTIAL",
        "PAGINATION_REQUIRED",
        "PARTIAL_CHUNK",
        "RENDERING_LIMIT",
    }
)
FINAL_UNAVAILABLE_REASONS = frozenset(
    {
        "V6_SCOPE_FAILED",
        "V6_SCOPE_STALE",
        "V6_SCOPE_MISSING",
        "V6_SCOPE_MATERIALLY_INCOMPLETE",
        "IDENTITY_CONFLICT",
        "PUBLICATION_CORRUPT",
        "GOVERNED_RETRY_EXHAUSTED",
    }
)
EXACT_SCOPE_RECOVERY_STEPS = (
    "CONTINUE_SAME_V6_SCOPE",
    "PAGINATE_OR_INCREASE_LIMIT",
    "CHUNK_BY_ROW_PLAYER_SECTION",
    "REASSEMBLE",
    "VALIDATE_COMPLETENESS",
)

MANDATORY_SECTIONS = tuple(
    [f"S{index:02d}" for index in range(1, 15)]
    + ["S14B"]
    + [f"S{index:02d}" for index in range(15, 19)]
)
PARTIAL_ALLOWED_SECTIONS = frozenset({"S02", "S13", "S14B", "S15"})
POSITION_TARGET = {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
_POSITION_ALIASES = {"GKP": "GK", "GOALKEEPER": "GK"}
REPORT_SLOT_STATES = frozenset({"NOT_STARTED", "BUILDING", "QA_FAILED", "DELIVERED"})


class DeliveryIntegrityError(ValueError):
    pass


def _parse_time(value: str | datetime) -> datetime:
    try:
        return parse_timestamp(
            value,
            label="timestamp",
            target_timezone=timezone.utc,
        )
    except TemporalError as exc:
        if "timezone-aware" in str(exc):
            raise DeliveryIntegrityError("timestamp must include timezone offset") from exc
        raise DeliveryIntegrityError("timestamp must be ISO-8601") from exc


def build_report_slot_id(*, logical_slot: str | datetime, report_type: str) -> str:
    try:
        slot = parse_timestamp(
            logical_slot,
            label="report logical slot",
            target_timezone=DEFAULT_RUNTIME_TIMEZONE,
        )
    except TemporalError as exc:
        if "timezone-aware" in str(exc):
            raise DeliveryIntegrityError("report logical slot must include timezone offset") from exc
        raise DeliveryIntegrityError("report logical slot must be ISO-8601") from exc
    if slot.second != 0 or slot.microsecond != 0:
        raise DeliveryIntegrityError("report logical slot must be minute-aligned")

    kind = str(report_type or "").strip().upper()
    if not kind or "|" in kind:
        raise DeliveryIntegrityError("report type must be a non-empty slot-safe identifier")
    return f"{slot.isoformat(timespec='minutes')}|{kind}"


def resolve_report_slot_decision(
    *,
    logical_slot: str | datetime,
    report_type: str,
    report_state: str,
    v6_already_published: bool,
    delivered_report_slot_id: str | None,
    delivery_proof_valid: bool,
) -> dict[str, Any]:
    report_slot_id = build_report_slot_id(
        logical_slot=logical_slot,
        report_type=report_type,
    )
    state = str(report_state or "").strip().upper()
    if state not in REPORT_SLOT_STATES:
        raise DeliveryIntegrityError(f"invalid report slot state: {state or '<empty>'}")

    same_slot_delivery_proof = bool(
        delivery_proof_valid
        and delivered_report_slot_id
        and delivered_report_slot_id == report_slot_id
    )
    report_delivered = state == "DELIVERED" and same_slot_delivery_proof

    if report_delivered:
        start_build = False
        duplicate = True
        reason = "SAME_SLOT_ALREADY_DELIVERED"
    elif state == "BUILDING":
        start_build = False
        duplicate = False
        reason = "SAME_SLOT_BUILD_IN_PROGRESS"
    elif state == "QA_FAILED":
        start_build = True
        duplicate = False
        reason = "SAME_SLOT_RECOVERY"
    elif state == "DELIVERED":
        start_build = True
        duplicate = False
        reason = "DELIVERY_PROOF_RECOVERY"
    else:
        start_build = True
        duplicate = False
        reason = "DUE_REPORT"

    return {
        "report_slot_id": report_slot_id,
        "report_state": state,
        "v6_already_published": bool(v6_already_published),
        "report_delivered": report_delivered,
        "report_required": not report_delivered,
        "start_build": start_build,
        "duplicate": duplicate,
        "reason": reason,
    }


def retrieval_decision(*, v6_scope_state: str, retrieval_state: str) -> dict[str, Any]:
    scope = str(v6_scope_state or "").upper()
    retrieval = str(retrieval_state or "").upper()
    if scope in HEALTHY_V6_SCOPE_STATES:
        if retrieval == "COMPLETE":
            return {
                "action": "READ_V6_ONLY",
                "direct_fresh_allowed": False,
                "final_unavailable_allowed": False,
            }
        if retrieval in RETRIEVAL_RECOVERY_CONDITIONS:
            return {
                "action": "SAME_V6_RETRIEVAL_RECOVERY",
                "direct_fresh_allowed": False,
                "final_unavailable_allowed": False,
            }
        raise DeliveryIntegrityError(f"unknown retrieval state for healthy V6: {retrieval}")

    if scope in FINAL_UNAVAILABLE_REASONS:
        return {
            "action": "SCOPED_DIRECT_FRESH_ALLOWED",
            "direct_fresh_allowed": True,
            "final_unavailable_allowed": True,
        }
    raise DeliveryIntegrityError(f"invalid V6 scope state: {scope}")


def _validate_v6_scope_id(v6_scope_id: str) -> str:
    value = str(v6_scope_id or "").strip()
    if not value:
        raise DeliveryIntegrityError("v6_scope_id must be non-empty")
    return value


def plan_exact_scope_retrieval(
    *,
    v6_scope_id: str,
    v6_scope_state: str,
    retrieval_state: str,
) -> dict[str, Any]:
    scope_id = _validate_v6_scope_id(v6_scope_id)
    decision = retrieval_decision(
        v6_scope_state=v6_scope_state,
        retrieval_state=retrieval_state,
    )
    exact_scope_recovery = decision["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    scope_lock_required = decision["action"] in {
        "READ_V6_ONLY",
        "SAME_V6_RETRIEVAL_RECOVERY",
    }
    return {
        "v6_scope_id": scope_id,
        "v6_scope_state": str(v6_scope_state or "").upper(),
        "retrieval_state": str(retrieval_state or "").upper(),
        "action": decision["action"],
        "scope_lock_required": scope_lock_required,
        "recovery_steps": list(EXACT_SCOPE_RECOVERY_STEPS) if exact_scope_recovery else [],
        "direct_fresh_allowed": bool(decision["direct_fresh_allowed"]),
        "legacy_fallback_allowed": False,
        "final_unavailable_allowed": bool(decision["final_unavailable_allowed"]),
    }


def validate_retrieval_reassembly(
    *,
    v6_scope_id: str,
    expected_ids: Iterable[int | str],
    retrieved_chunks: Sequence[Sequence[int | str]],
) -> dict[str, Any]:
    scope_id = _validate_v6_scope_id(v6_scope_id)
    expected = list(expected_ids)
    if not expected:
        raise DeliveryIntegrityError("expected_ids must define the scope completeness denominator")
    if any(item is None for item in expected):
        raise DeliveryIntegrityError("expected_ids cannot contain missing identity")
    if len(set(expected)) != len(expected):
        raise DeliveryIntegrityError("expected_ids must be unique")

    reassembled: list[int | str] = []
    for chunk in retrieved_chunks:
        reassembled.extend(chunk)

    counts = Counter(reassembled)
    expected_set = set(expected)
    retrieved_set = set(reassembled)
    missing = sorted(expected_set - retrieved_set, key=str)
    duplicates = sorted((item for item, count in counts.items() if count > 1), key=str)
    unexpected = sorted(retrieved_set - expected_set, key=str)
    complete = bool(
        len(reassembled) == len(expected)
        and not missing
        and not duplicates
        and not unexpected
    )

    return {
        "v6_scope_id": scope_id,
        "status": "PASS" if complete else "INCOMPLETE",
        "complete": complete,
        "expected_count": len(expected),
        "retrieved_count": len(reassembled),
        "retrieved_unique_count": len(retrieved_set),
        "chunk_count": len(retrieved_chunks),
        "missing_ids": missing,
        "duplicate_ids": duplicates,
        "unexpected_ids": unexpected,
        "reassembled_ids": reassembled,
        "action": "READ_REASSEMBLED_V6_SCOPE" if complete else "SAME_V6_RETRIEVAL_RECOVERY",
        "scope_lock_required": True,
        "direct_fresh_allowed": False,
        "legacy_fallback_allowed": False,
        "final_unavailable_allowed": False,
    }


def direct_fresh_allowed(*, v6_scope_state: str, retrieval_state: str = "COMPLETE") -> bool:
    return bool(
        retrieval_decision(
            v6_scope_state=v6_scope_state,
            retrieval_state=retrieval_state,
        )["direct_fresh_allowed"]
    )


def validate_final_unavailable_reason(reason: str) -> str:
    value = str(reason or "").upper()
    if value not in FINAL_UNAVAILABLE_REASONS:
        raise DeliveryIntegrityError(
            f"final UNAVAILABLE reason is not source-health eligible: {value or '<empty>'}"
        )
    return value


def assess_report_timing(
    *,
    logical_slot: str | datetime,
    report_generated_at: str | datetime,
    delivered_at: str | datetime | None = None,
) -> dict[str, Any]:
    slot = _parse_time(logical_slot)
    generated = _parse_time(report_generated_at)
    report_lateness = age_seconds(now=generated, earlier=slot)
    result: dict[str, Any] = {
        "report_timeliness": "ON_TIME" if report_lateness == 0 else "LATE",
        "report_lateness_seconds": round(report_lateness, 3),
    }
    if delivered_at is not None:
        delivered = _parse_time(delivered_at)
        delivery_lateness = age_seconds(now=delivered, earlier=generated)
        result.update(
            {
                "delivery_timeliness": "IMMEDIATE" if delivery_lateness == 0 else "LATE",
                "delivery_lateness_seconds": round(delivery_lateness, 3),
            }
        )
    return result


def assess_artifact_freshness(
    *,
    artifact: str,
    source_generated_at: str | datetime,
    observed_at: str | datetime,
    maximum_age_minutes: float,
    immutable_gw_cache: bool = False,
) -> dict[str, Any]:
    if artifact not in ARTIFACT_SCOPES:
        raise DeliveryIntegrityError(f"unknown report artifact scope: {artifact}")
    if maximum_age_minutes < 0:
        raise DeliveryIntegrityError("maximum_age_minutes must be non-negative")
    source = _parse_time(source_generated_at)
    observed = _parse_time(observed_at)
    age_minutes = age_seconds(now=observed, earlier=source) / 60.0
    if immutable_gw_cache:
        if artifact != "submitted_picks":
            raise DeliveryIntegrityError(
                "immutable GW cache reuse is only valid for submitted_picks"
            )
        state = "IMMUTABLE_GW_CACHE_REUSED"
    else:
        state = "CURRENT" if age_minutes <= maximum_age_minutes else "STALE"
    return {
        "artifact": artifact,
        "source_freshness": state,
        "source_age_minutes": round(age_minutes, 3),
        "maximum_age_minutes": float(maximum_age_minutes),
    }


def assess_artifact_matrix(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    observed_at: str | datetime,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for artifact, row in artifacts.items():
        result[artifact] = assess_artifact_freshness(
            artifact=artifact,
            source_generated_at=row["source_generated_at"],
            observed_at=observed_at,
            maximum_age_minutes=float(row["maximum_age_minutes"]),
            immutable_gw_cache=bool(row.get("immutable_gw_cache", False)),
        )
    return result


def _player_id(row: Mapping[str, Any]) -> int | str | None:
    for key in ("element_id", "player_id", "id"):
        if row.get(key) is not None:
            return row[key]
    return None


def _position(row: Mapping[str, Any]) -> str:
    raw = str(row.get("position") or row.get("pos") or "").upper()
    return _POSITION_ALIASES.get(raw, raw)


def validate_watchlist20(
    rows: Sequence[Mapping[str, Any]],
    *,
    owned_ids: Iterable[int | str] = (),
    universe_ids: Iterable[int | str] | None = None,
) -> dict[str, Any]:
    ids = [_player_id(row) for row in rows]
    positions = Counter(_position(row) for row in rows)
    owned = set(owned_ids)
    universe = set(universe_ids) if universe_ids is not None else None
    failures: list[str] = []
    if len(rows) != 20:
        failures.append(f"TOTAL={len(rows)}")
    if any(player_id is None for player_id in ids):
        failures.append("IDENTITY_MISSING")
    concrete_ids = [player_id for player_id in ids if player_id is not None]
    if len(set(concrete_ids)) != len(concrete_ids):
        failures.append("IDENTITY_DUPLICATE")
    overlap = sorted((set(concrete_ids) & owned), key=str)
    if overlap:
        failures.append(f"OWNED_OVERLAP={len(overlap)}")
    if universe is not None:
        outside = set(concrete_ids) - universe
        if outside:
            failures.append(f"OUTSIDE_CURRENT_UNIVERSE={len(outside)}")
    for position, target in POSITION_TARGET.items():
        if positions.get(position, 0) != target:
            failures.append(f"{position}={positions.get(position, 0)}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "reason": "OK" if not failures else "RETRIEVAL/COMPUTE_DEFECT",
        "failures": failures,
        "total": len(rows),
        "positions": {key: positions.get(key, 0) for key in POSITION_TARGET},
        "owned_overlap": len(overlap),
    }


def validate_rank20(rows: Sequence[Mapping[str, Any]], *, label: str) -> dict[str, Any]:
    ids = [_player_id(row) for row in rows]
    failures: list[str] = []
    if len(rows) != 20:
        failures.append(f"TOTAL={len(rows)}")
    if any(player_id is None for player_id in ids):
        failures.append("IDENTITY_MISSING")
    concrete_ids = [player_id for player_id in ids if player_id is not None]
    if len(set(concrete_ids)) != len(concrete_ids):
        failures.append("IDENTITY_DUPLICATE")
    return {
        "label": label,
        "status": "PASS" if not failures else "FAIL",
        "reason": "OK" if not failures else "RETRIEVAL/COMPUTE_DEFECT",
        "failures": failures,
        "total": len(rows),
    }


def pre_delivery_gate(
    section_statuses: Mapping[str, str],
    *,
    watchlist_rows: Sequence[Mapping[str, Any]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    owned_ids: Iterable[int | str] = (),
    universe_ids: Iterable[int | str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    missing = [section for section in MANDATORY_SECTIONS if section not in section_statuses]
    failures.extend(f"MISSING_{section}" for section in missing)
    for section in MANDATORY_SECTIONS:
        if section in {"S10", "S11", "S12"} or section not in section_statuses:
            continue
        state = str(section_statuses[section]).upper()
        if state == "PASS":
            continue
        if section in PARTIAL_ALLOWED_SECTIONS and state.startswith("PARTIAL"):
            continue
        failures.append(f"{section}={state}")

    watchlist = validate_watchlist20(
        watchlist_rows,
        owned_ids=owned_ids,
        universe_ids=universe_ids,
    )
    rise = validate_rank20(rise_rows, label="RISE20")
    fall = validate_rank20(fall_rows, label="FALL20")
    for section, result in (("S10", watchlist), ("S11", rise), ("S12", fall)):
        if result["status"] != "PASS":
            failures.append(f"{section}_{result['reason']}")
        declared = str(section_statuses.get(section, "MISSING")).upper()
        if declared != "PASS":
            failures.append(f"{section}={declared}")

    return {
        "report_ready": not failures,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "S10": watchlist,
        "S11": rise,
        "S12": fall,
    }


def post_render_gate(
    *,
    watchlist_rendered_rows: int,
    watchlist_position_counts: Mapping[str, int],
    rise_rendered_rows: int,
    fall_rendered_rows: int,
    mandatory_sections_missing: int,
) -> dict[str, Any]:
    normalized = {
        _POSITION_ALIASES.get(str(key).upper(), str(key).upper()): int(value)
        for key, value in watchlist_position_counts.items()
    }
    failures: list[str] = []
    if watchlist_rendered_rows != 20:
        failures.append(f"WATCHLIST_RENDERED={watchlist_rendered_rows}")
    for position, target in POSITION_TARGET.items():
        if normalized.get(position, 0) != target:
            failures.append(f"WATCHLIST_{position}={normalized.get(position, 0)}")
    if rise_rendered_rows != 20:
        failures.append(f"RISE_RENDERED={rise_rendered_rows}")
    if fall_rendered_rows != 20:
        failures.append(f"FALL_RENDERED={fall_rendered_rows}")
    if mandatory_sections_missing != 0:
        failures.append(f"MANDATORY_SECTION_MISSING={mandatory_sections_missing}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "action": "DELIVER" if not failures else "RENDER_AGAIN",
        "failures": failures,
    }
