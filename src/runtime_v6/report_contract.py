from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .delivery_integrity import (
    RETRIEVAL_RECOVERY_CONDITIONS,
    direct_fresh_allowed as source_allows_direct_fresh,
)


REPORT_MODES = frozenset(
    {
        "normal_hourly",
        "04:30_deep",
        "05:30_price",
        "12:30_deep",
        "21:30_deep",
        "match_mode",
        "deadline_mode",
        "ad_hoc_deep",
    }
)

VISIBLE_STATUS_LAYERS = (
    "CORE TRANSPORT",
    "ACQUISITION",
    "PUBLISH_INTEGRITY",
    "PUBLISH VALIDATION",
    "NEW PUBLICATION",
    "LAST-GOOD",
    "SCHEDULER PROOF",
    "REPORT PREFETCH",
    "TARGET REPORT FRESHNESS",
    "AUTH",
    "REPORT DELIVERY",
)


class ReportContractError(ValueError):
    pass


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReportContractError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportContractError("timestamp must include timezone offset")
    return parsed.astimezone(timezone.utc)


def _display_time(value: str | datetime) -> str:
    """Preserve the caller's timezone representation for user-facing evidence fields.

    Arithmetic remains UTC-normalized through _parse_time. This helper exists so an
    Asia/Jakarta scheduler proof is not rendered as a different-looking UTC clock time
    even though both timestamps represent the same instant.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ReportContractError("timestamp must include timezone offset")
        return value.isoformat()
    text = str(value)
    _parse_time(text)
    return text


def core_slot_key(schedule_kind: str, logical_slot: str) -> str:
    if not str(schedule_kind).strip():
        raise ReportContractError("schedule_kind is required")
    _parse_time(logical_slot)
    return f"{schedule_kind}|{logical_slot}"


def safety_net_decision(
    *,
    logical_slot: str,
    primary_owned: bool,
    prefetched: bool,
    delivered: bool,
) -> dict[str, Any]:
    _parse_time(logical_slot)
    reasons = []
    if primary_owned:
        reasons.append("PRIMARY_OWNS_SLOT")
    if prefetched:
        reasons.append("REPORT_ALREADY_PREFETCHED")
    if delivered:
        reasons.append("REPORT_ALREADY_DELIVERED")
    if reasons:
        return {
            "logical_slot": logical_slot,
            "action": "NO_OP",
            "reason": "+".join(reasons),
            "deduplicated": True,
        }
    return {
        "logical_slot": logical_slot,
        "action": "RECOVER",
        "reason": "UNOWNED_UNPREFETCHED_UNDELIVERED_SLOT",
        "deduplicated": False,
    }


def choose_report_source(
    *,
    fresh_v6_available: bool,
    direct_fresh_available: bool,
    last_good_available: bool,
    field_is_volatile: bool,
    v6_scope_state: str | None = None,
    retrieval_state: str = "COMPLETE",
) -> str:
    retrieval = str(retrieval_state or "COMPLETE").upper()
    if fresh_v6_available:
        if retrieval in RETRIEVAL_RECOVERY_CONDITIONS:
            return "V6_RETRIEVAL_RECOVERY"
        if retrieval != "COMPLETE":
            raise ReportContractError(f"unsupported V6 retrieval state: {retrieval}")
        return "FRESH_V6"

    scope_state = str(v6_scope_state or "V6_SCOPE_FAILED").upper()
    if direct_fresh_available and source_allows_direct_fresh(
        v6_scope_state=scope_state,
        retrieval_state="COMPLETE",
    ):
        return "DIRECT_FRESH"
    if last_good_available and not field_is_volatile:
        return "LAST_GOOD_NONVOLATILE"
    return "UNAVAILABLE"


def _normalized_scope_id(scope_id: str) -> str:
    value = str(scope_id or "").strip()
    if not value:
        raise ReportContractError("scope_id is required")
    return value


def _normalized_auth_status(auth_status: str | None) -> str:
    value = str(auth_status or "NOT REQUESTED").strip().upper()
    aliases = {
        "AUTH_AVAILABLE": "OK",
        "AVAILABLE": "OK",
        "AUTH_EXPIRED": "EXPIRED",
        "AUTH_UNAVAILABLE": "FAILED",
    }
    return aliases.get(value, value)


def resolve_report_scope(
    *,
    scope_id: str,
    required: bool,
    auth_required: bool,
    volatile: bool,
    fresh_v6_available: bool,
    v6_scope_state: str | None,
    retrieval_state: str,
    direct_fresh_available: bool,
    last_good_available: bool,
    auth_status: str | None,
) -> dict[str, Any]:
    """Resolve one report scope without allowing unrelated scopes to influence it."""
    scope = _normalized_scope_id(scope_id)
    auth = _normalized_auth_status(auth_status)

    if auth_required and auth != "OK":
        reason_auth = auth.replace(" ", "_")
        return {
            "scope_id": scope,
            "required": bool(required),
            "auth_required": True,
            "volatile": bool(volatile),
            "source": "PRIVATE_AUTH_UNAVAILABLE",
            "action": "DISCLOSE_PRIVATE_AUTH_UNAVAILABLE",
            "status": "DEGRADED",
            "report_blocking": False,
            "degraded": True,
            "direct_fresh_allowed": False,
            "legacy_fallback_allowed": False,
            "reason": f"AUTH_{reason_auth}",
        }

    source = choose_report_source(
        fresh_v6_available=bool(fresh_v6_available),
        direct_fresh_available=bool(direct_fresh_available),
        last_good_available=bool(last_good_available),
        field_is_volatile=bool(volatile),
        v6_scope_state=v6_scope_state,
        retrieval_state=retrieval_state,
    )

    if source == "FRESH_V6":
        action = "READ_V6"
        status = "PASS"
        report_blocking = False
        degraded = False
        reason = "FRESH_V6"
        scoped_direct_fresh_allowed = False
    elif source == "V6_RETRIEVAL_RECOVERY":
        action = "SAME_V6_RETRIEVAL_RECOVERY"
        status = "RECOVERY_REQUIRED"
        report_blocking = bool(required)
        degraded = not bool(required)
        reason = f"RETRIEVAL_{str(retrieval_state or '').strip().upper()}"
        scoped_direct_fresh_allowed = False
    elif source == "DIRECT_FRESH":
        action = "SCOPED_DIRECT_FRESH"
        status = "PASS"
        report_blocking = False
        degraded = False
        reason = "VERIFIED_V6_SCOPE_FAILURE"
        scoped_direct_fresh_allowed = True
    elif source == "LAST_GOOD_NONVOLATILE":
        action = "READ_LAST_GOOD_NONVOLATILE"
        status = "PASS"
        report_blocking = False
        degraded = False
        reason = "NONVOLATILE_LAST_GOOD_RECOVERY"
        scoped_direct_fresh_allowed = False
    else:
        report_blocking = bool(required)
        degraded = not report_blocking
        status = "BLOCKED" if report_blocking else "DEGRADED"
        action = (
            "DISCLOSE_REQUIRED_SCOPE_UNAVAILABLE"
            if report_blocking
            else "DISCLOSE_OPTIONAL_SCOPE_UNAVAILABLE"
        )
        reason = "NO_VALID_SCOPE_SOURCE"
        scoped_direct_fresh_allowed = False

    return {
        "scope_id": scope,
        "required": bool(required),
        "auth_required": bool(auth_required),
        "volatile": bool(volatile),
        "source": source,
        "action": action,
        "status": status,
        "report_blocking": report_blocking,
        "degraded": degraded,
        "direct_fresh_allowed": scoped_direct_fresh_allowed,
        "legacy_fallback_allowed": False,
        "reason": reason,
    }


def resolve_report_scope_matrix(
    scopes: Mapping[str, Mapping[str, Any]],
    *,
    auth_status: str | None,
) -> dict[str, Any]:
    """Resolve every report scope independently and aggregate only delivery blockers."""
    resolved: dict[str, dict[str, Any]] = {}
    for scope_id, policy in scopes.items():
        resolved[scope_id] = resolve_report_scope(
            scope_id=scope_id,
            required=bool(policy.get("required", True)),
            auth_required=bool(policy.get("auth_required", False)),
            volatile=bool(policy.get("volatile", True)),
            fresh_v6_available=bool(policy.get("fresh_v6_available", False)),
            v6_scope_state=policy.get("v6_scope_state"),
            retrieval_state=str(policy.get("retrieval_state", "COMPLETE")),
            direct_fresh_available=bool(policy.get("direct_fresh_available", False)),
            last_good_available=bool(policy.get("last_good_available", False)),
            auth_status=auth_status,
        )

    blocking_scopes = [
        scope_id
        for scope_id, result in resolved.items()
        if result["report_blocking"]
    ]
    degraded_scopes = [
        scope_id
        for scope_id, result in resolved.items()
        if result["degraded"]
    ]
    recovery_scopes = [
        scope_id
        for scope_id, result in resolved.items()
        if result["status"] == "RECOVERY_REQUIRED"
    ]
    direct_fresh_scopes = [
        scope_id
        for scope_id, result in resolved.items()
        if result["source"] == "DIRECT_FRESH"
    ]

    return {
        "report_ready": not blocking_scopes,
        "blocking_scopes": blocking_scopes,
        "degraded_scopes": degraded_scopes,
        "recovery_scopes": recovery_scopes,
        "direct_fresh_scopes": direct_fresh_scopes,
        "legacy_fallback_allowed": False,
        "scopes": resolved,
    }


def map_auth_status(*, requested: bool, raw_state: str | None) -> str:
    if not requested:
        return "NOT REQUESTED"
    state = str(raw_state or "").strip().upper()
    if state in {"AUTH_AVAILABLE", "AVAILABLE", "OK"}:
        return "OK"
    if state in {"AUTH_EXPIRED", "EXPIRED"}:
        return "EXPIRED"
    return "FAILED"


def report_delivery_status(
    *,
    due: bool,
    fresh_v6_available: bool,
    direct_fresh_available: bool,
    last_good_nonvolatile_available: bool,
    v6_scope_state: str | None = None,
    retrieval_state: str = "COMPLETE",
) -> str:
    if not due:
        return "N/A"
    source = choose_report_source(
        fresh_v6_available=fresh_v6_available,
        direct_fresh_available=direct_fresh_available,
        last_good_available=last_good_nonvolatile_available,
        field_is_volatile=False,
        v6_scope_state=v6_scope_state,
        retrieval_state=retrieval_state,
    )
    if source == "V6_RETRIEVAL_RECOVERY":
        return "BLOCKED | SAME V6 RETRIEVAL RECOVERY"
    if source == "FRESH_V6":
        return "PASS | FRESH V6"
    if source == "DIRECT_FRESH":
        return "PASS | DIRECT FRESH FALLBACK"
    if source == "LAST_GOOD_NONVOLATILE":
        return "PASS | LAST_GOOD NONVOLATILE FALLBACK"
    return "PASS | UNAVAILABLE FIELDS DISCLOSED"


def status_entry(
    state: str,
    *,
    observed_at: str | datetime,
    source_at: str | datetime | None = None,
) -> dict[str, Any]:
    observed = _parse_time(observed_at)
    entry: dict[str, Any] = {
        "state": state,
        "observed_at": observed.isoformat(),
    }
    if source_at is not None:
        source = _parse_time(source_at)
        entry["source_at"] = source.isoformat()
        entry["age_seconds"] = round(max(0.0, (observed - source).total_seconds()), 3)
    return entry


def build_status_view(
    *,
    observed_at: str | datetime,
    core_transport: str,
    acquisition: str,
    publish_integrity: str,
    publish_validation: str,
    new_publication: str,
    last_good_state: str,
    last_good_generated_at: str | datetime | None,
    scheduler_proof_state: str,
    scheduler_proof_at: str | datetime | None,
    report_prefetch: str,
    target_report_freshness: str,
    auth: str,
    report_delivery: str,
) -> dict[str, dict[str, Any]]:
    last_good = status_entry(
        last_good_state,
        observed_at=observed_at,
        source_at=last_good_generated_at,
    )
    if "age_seconds" in last_good and last_good_generated_at is not None:
        last_good["last_good_age_seconds"] = last_good["age_seconds"]
        last_good["generated_at"] = _display_time(last_good_generated_at)

    scheduler_proof = status_entry(
        scheduler_proof_state,
        observed_at=observed_at,
        source_at=scheduler_proof_at,
    )
    if "age_seconds" in scheduler_proof and scheduler_proof_at is not None:
        scheduler_proof["scheduler_proof_age_seconds"] = scheduler_proof["age_seconds"]
        scheduler_proof["scheduler_proof_at"] = _display_time(scheduler_proof_at)

    view = {
        "CORE TRANSPORT": status_entry(core_transport, observed_at=observed_at),
        "ACQUISITION": status_entry(acquisition, observed_at=observed_at),
        "PUBLISH_INTEGRITY": status_entry(publish_integrity, observed_at=observed_at),
        "PUBLISH VALIDATION": status_entry(publish_validation, observed_at=observed_at),
        "NEW PUBLICATION": status_entry(new_publication, observed_at=observed_at),
        "LAST-GOOD": last_good,
        "SCHEDULER PROOF": scheduler_proof,
        "REPORT PREFETCH": status_entry(report_prefetch, observed_at=observed_at),
        "TARGET REPORT FRESHNESS": status_entry(target_report_freshness, observed_at=observed_at),
        "AUTH": status_entry(auth, observed_at=observed_at),
        "REPORT DELIVERY": status_entry(report_delivery, observed_at=observed_at),
    }
    assert tuple(view) == VISIBLE_STATUS_LAYERS
    return view
