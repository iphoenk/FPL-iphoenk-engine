from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .delivery_integrity import (
    RETRIEVAL_RECOVERY_CONDITIONS,
    direct_fresh_allowed as source_allows_direct_fresh,
)
from ..control_plane.schedule_policy import SCHEDULE_POLICY


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


def classify_report_outcome(
    *,
    data_slot_fulfilled: bool,
    report_contract_pass: bool,
    visible_emitted: bool,
    delivery_proof_valid: bool,
) -> dict[str, bool]:
    """Keep data, visible delivery and canonical report fulfillment independent."""
    report_delivered = bool(visible_emitted)
    report_slot_fulfilled = bool(
        report_delivered
        and report_contract_pass
        and delivery_proof_valid
    )
    return {
        "DATA_SLOT_FULFILLED": bool(data_slot_fulfilled),
        "REPORT_SLOT_FULFILLED": report_slot_fulfilled,
        "REPORT_DELIVERED": report_delivered,
        "REPORT_CONTRACT_PASS": bool(report_contract_pass),
        "DELIVERY_PROOF_VALID": bool(delivery_proof_valid),
    }


def safety_net_decision(
    *,
    logical_slot: str,
    primary_owned: bool,
    prefetched: bool,
    delivered: bool,
    report_contract_pass: bool = False,
    delivery_proof_valid: bool = False,
    report_slot_fulfilled: bool | None = None,
) -> dict[str, Any]:
    """Suppress recovery only for a positively fulfilled same-slot report.

    Ownership, prefetch and even a raw visible message are observability signals,
    never canonical delivery evidence on their own.
    """
    _parse_time(logical_slot)
    fulfilled = (
        bool(report_slot_fulfilled)
        if report_slot_fulfilled is not None
        else bool(delivered and report_contract_pass and delivery_proof_valid)
    )
    if fulfilled:
        return {
            "logical_slot": logical_slot,
            "action": "NO_OP",
            "reason": "REPORT_SLOT_FULFILLED",
            "deduplicated": True,
            "report_slot_fulfilled": True,
        }

    evidence: list[str] = []
    if primary_owned:
        evidence.append("PRIMARY_OWNS_SLOT_NONTERMINAL")
    if prefetched:
        evidence.append("REPORT_PREFETCHED_NONTERMINAL")
    if delivered:
        evidence.append("RAW_VISIBLE_DELIVERY_WITHOUT_FULFILLMENT")
    if not report_contract_pass:
        evidence.append("REPORT_CONTRACT_NOT_PASSED")
    if not delivery_proof_valid:
        evidence.append("DELIVERY_PROOF_NOT_VALID")

    return {
        "logical_slot": logical_slot,
        "action": "RECOVER",
        "reason": "+".join(evidence) if evidence else "REPORT_SLOT_UNFULFILLED",
        "deduplicated": False,
        "report_slot_fulfilled": False,
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
        # Source unavailability is a factual degradation, not permission to
        # shrink or suppress the canonical visible-report schema. Retrieval
        # partials remain blocking above until SAME-V6 recovery is exhausted;
        # once no valid source exists, the affected section must still render
        # truthfully as unavailable while unrelated report computation continues.
        report_blocking = False
        degraded = True
        status = "DEGRADED"
        action = (
            "RENDER_REQUIRED_SCOPE_UNAVAILABLE"
            if required
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
    report_contract_pass: bool = False,
    report_slot_fulfilled: bool = False,
    report_delivered: bool = False,
    delivery_proof_valid: bool = False,
) -> str:
    """Report delivery truth is contract/proof truth, not source availability."""
    if not due:
        return "N/A"

    if report_delivered and not (
        report_contract_pass and report_slot_fulfilled and delivery_proof_valid
    ):
        return "FAIL | RAW DELIVERY WITHOUT CONTRACT FULFILLMENT"
    if (
        report_delivered
        and report_contract_pass
        and report_slot_fulfilled
        and delivery_proof_valid
    ):
        return "PASS | REPORT SLOT FULFILLED"

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
        return "PENDING | FRESH V6 | REPORT CONTRACT NOT PROVEN"
    if source == "DIRECT_FRESH":
        return "PENDING | DIRECT FRESH | REPORT CONTRACT NOT PROVEN"
    if source == "LAST_GOOD_NONVOLATILE":
        return "PENDING | LAST_GOOD NONVOLATILE | REPORT CONTRACT NOT PROVEN"
    return "DEGRADED | UNAVAILABLE FIELDS DISCLOSED | REPORT CONTRACT NOT PROVEN"


def _parse_aware_preserve(value: str | datetime, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReportContractError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportContractError(f"{label} must include timezone offset")
    return parsed


def _canonical_checkpoint_at_or_after(value: datetime) -> datetime:
    timezone_name = ZoneInfo(SCHEDULE_POLICY.timezone)
    local = value.astimezone(timezone_name)
    candidate = local.replace(
        minute=SCHEDULE_POLICY.physical_minute,
        second=0,
        microsecond=0,
    )
    cadence = timedelta(minutes=SCHEDULE_POLICY.cadence_minutes)
    while candidate < local:
        candidate += cadence
    return candidate


def _deadline_windows(
    official_deadline: str | datetime | None,
) -> dict[str, datetime | None]:
    if official_deadline is None:
        return {
            "official_deadline": None,
            "deadline_active_start": None,
            "final_window_raw_start": None,
            "first_final_checkpoint": None,
        }

    deadline = _parse_aware_preserve(official_deadline, label="official_deadline")
    deadline = deadline.astimezone(ZoneInfo(SCHEDULE_POLICY.timezone))
    deadline_active_start = _canonical_checkpoint_at_or_after(
        deadline - timedelta(hours=24)
    )
    if deadline.hour < 2:
        final_window_raw_start = deadline - timedelta(hours=3)
    else:
        final_window_raw_start = deadline - timedelta(minutes=90)
    first_final_checkpoint = _canonical_checkpoint_at_or_after(final_window_raw_start)
    return {
        "official_deadline": deadline,
        "deadline_active_start": deadline_active_start,
        "final_window_raw_start": final_window_raw_start,
        "first_final_checkpoint": first_final_checkpoint,
    }


def resolve_master_report_occurrence(
    *,
    intended_report_slot: str | datetime,
    observed_at: str | datetime,
    official_deadline: str | datetime | None = None,
    match_live: bool = False,
    post_all_match_due: bool = False,
    v6_degraded: bool = False,
    transport_failed: bool = False,
    report_prefetch_state: str = "CURRENT",
) -> dict[str, Any]:
    """Resolve one natural Master occurrence without rewriting its canonical identity.

    Runtime scheduling, deadline/final routing and late recovery share this single
    state transition so scheduler lateness cannot silently turn a mandatory report
    into NOT_DUE.
    """
    intended = _parse_aware_preserve(
        intended_report_slot,
        label="intended_report_slot",
    ).astimezone(ZoneInfo(SCHEDULE_POLICY.timezone))
    observed = _parse_aware_preserve(observed_at, label="observed_at")
    observed_local = observed.astimezone(ZoneInfo(SCHEDULE_POLICY.timezone))

    tolerance = float(SCHEDULE_POLICY.scheduled_dispatch_tolerance_seconds)
    delta_seconds = (observed_local - intended).total_seconds()
    if delta_seconds < -tolerance:
        raise ReportContractError(
            "scheduled dispatch precedes intended occurrence beyond tolerance"
        )

    recovery_deadline = intended + timedelta(minutes=SCHEDULE_POLICY.cadence_minutes)
    if abs(delta_seconds) <= tolerance:
        occurrence_state = "ON_TIME"
    elif observed_local <= recovery_deadline:
        occurrence_state = "LATE_RECOVERABLE"
    else:
        occurrence_state = "LATE_EXPIRED"

    windows = _deadline_windows(official_deadline)
    official = windows["official_deadline"]
    deadline_active_start = windows["deadline_active_start"]
    first_final_checkpoint = windows["first_final_checkpoint"]

    deadline_locked = bool(official is not None and intended >= official)
    deadline_active = bool(
        official is not None
        and deadline_active_start is not None
        and deadline_active_start <= intended < official
    )
    final_active = bool(
        deadline_active
        and first_final_checkpoint is not None
        and intended >= first_final_checkpoint
    )

    is_deep = intended.minute == SCHEDULE_POLICY.physical_minute and intended.hour in {
        4,
        12,
        21,
    }
    is_price = (
        intended.minute == SCHEDULE_POLICY.physical_minute
        and intended.hour == 5
    )

    if final_active:
        base_mode = "FINAL"
    elif deadline_active:
        base_mode = "DEADLINE"
    elif post_all_match_due:
        base_mode = "POST_ALL_MATCH"
    elif is_deep:
        base_mode = "DEEP"
    elif is_price:
        base_mode = "PRICE"
    else:
        base_mode = "SILENT"

    if match_live:
        if base_mode == "FINAL":
            route_mode = "FINAL+MATCH"
        elif base_mode == "DEADLINE":
            route_mode = "DEADLINE+MATCH"
        elif base_mode == "DEEP":
            route_mode = "FULL+MATCH"
        elif base_mode in {"SILENT", "PRICE"}:
            route_mode = "MATCH"
        else:
            route_mode = base_mode
    else:
        route_mode = base_mode

    nominal_visible_due = route_mode != "SILENT"
    visible_occurrence_due = bool(
        nominal_visible_due and occurrence_state != "LATE_EXPIRED"
    )
    late_catch_up = bool(
        nominal_visible_due and occurrence_state == "LATE_RECOVERABLE"
    )

    embedded_obligations: list[str] = []
    if route_mode.startswith(("DEADLINE", "FINAL")) and is_price:
        embedded_obligations.append("PRICE")
    if "+MATCH" in route_mode:
        embedded_obligations.append("MATCH")

    prefetch_state = str(report_prefetch_state or "UNKNOWN").strip().upper()
    if prefetch_state in {"STALE", "MISSING", "INCOMPLETE", "MISMATCH"}:
        prefetch_action = "GOVERNED_REFRESH_THEN_CONTINUE"
    elif prefetch_state == "CURRENT":
        prefetch_action = "USE_CURRENT"
    else:
        prefetch_action = "VERIFY_THEN_CONTINUE"

    return {
        "occurrence_state": occurrence_state,
        "intended_report_slot": intended.isoformat(),
        "observed_at": observed.isoformat(),
        "dispatch_delta_seconds": round(delta_seconds, 6),
        "on_time_tolerance_seconds": int(tolerance),
        "recovery_deadline": recovery_deadline.isoformat(),
        "route_mode": route_mode,
        "nominal_visible_occurrence_due": nominal_visible_due,
        "visible_occurrence_due": visible_occurrence_due,
        "delivery_required": visible_occurrence_due,
        "late_catch_up": late_catch_up,
        "late_label_required": late_catch_up,
        "historical_delivery_state": (
            "UNDELIVERED"
            if nominal_visible_due and occurrence_state == "LATE_EXPIRED"
            else None
        ),
        "deadline_active": deadline_active,
        "deadline_locked": deadline_locked,
        "deadline_active_start": (
            deadline_active_start.isoformat()
            if deadline_active_start is not None
            else None
        ),
        "first_final_checkpoint": (
            first_final_checkpoint.isoformat()
            if first_final_checkpoint is not None
            else None
        ),
        "official_deadline": official.isoformat() if official is not None else None,
        "embedded_obligations": embedded_obligations,
        "visible_report_count": 1 if visible_occurrence_due else 0,
        "v6_degraded": bool(v6_degraded),
        "transport_failed": bool(transport_failed),
        "report_prefetch_state": prefetch_state,
        "report_prefetch_action": prefetch_action,
        "data_slot_report_slot_delivery_independent": True,
        "replacement_report_slot_allowed": False,
        "v6_data_plane_backfill_allowed": False,
        "future_fill_allowed": False,
    }


def _is_genuine_natural_occurrence(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("natural") is True
        and str(row.get("schedule_kind") or "") == "chatgpt_scheduler"
        and row.get("manual") is not True
        and row.get("recovery") is not True
        and row.get("report_prefetch") is not True
        and row.get("ad_hoc") is not True
        and row.get("retro") is not True
        and row.get("future_fill") is not True
    )


def _natural_acceptance(row: Mapping[str, Any]) -> str:
    if str(row.get("core_acceptance") or "").upper() != "PASS":
        return "FAIL"
    if row.get("mandatory_visible_report") is True:
        report_pass = bool(
            row.get("report_contract_pass") is True
            and row.get("report_slot_fulfilled") is True
            and row.get("delivery_proof_valid") is True
            and row.get("visible_emitted") is True
            and row.get("status_only") is not True
        )
        return "PASS" if report_pass else "FAIL"
    return "PASS"


def evaluate_rolling_natural_acceptance(
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate the latest 12 genuine natural occurrences only.

    Manual/recovery/prefetch/ad-hoc/retro/future-fill evidence is never countable.
    A mandatory visible occurrence counts only with core PASS plus canonical
    report contract and delivery proof.
    """
    target = 12
    genuine: list[tuple[datetime, str, Mapping[str, Any]]] = []
    slot_counts: dict[str, int] = {}
    for row in occurrences:
        if not _is_genuine_natural_occurrence(row):
            continue
        slot_raw = row.get("logical_slot")
        if slot_raw is None:
            continue
        slot = _parse_time(str(slot_raw))
        slot_key = slot.isoformat()
        slot_counts[slot_key] = slot_counts.get(slot_key, 0) + 1
        genuine.append((slot, slot_key, row))

    genuine.sort(key=lambda item: item[0])
    unique: dict[str, tuple[datetime, Mapping[str, Any]]] = {}
    for slot, slot_key, row in genuine:
        unique[slot_key] = (slot, row)

    ordered_unique = sorted(unique.items(), key=lambda item: item[1][0])
    latest = ordered_unique[-target:]
    latest_keys = {key for key, _ in latest}
    duplicates = sorted(
        key
        for key, count in slot_counts.items()
        if count > 1 and key in latest_keys
    )

    latest_window: list[dict[str, Any]] = []
    pass_count = 0
    for slot_key, (_, row) in latest:
        acceptance = _natural_acceptance(row)
        if acceptance == "PASS":
            pass_count += 1
        rendered = dict(row)
        rendered["logical_slot"] = slot_key
        rendered["acceptance"] = acceptance
        latest_window.append(rendered)

    complete = len(latest_window) == target
    zero_misses = complete and pass_count == target and not duplicates
    return {
        "window_target": target,
        "countable_natural_count": len(ordered_unique),
        "latest_window_size": len(latest_window),
        "pass_count": pass_count,
        "zero_misses": zero_misses,
        "duplicate_logical_slots": duplicates,
        "latest_window": latest_window,
        "production_green": zero_misses,
    }


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
