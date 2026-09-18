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


_JAKARTA = ZoneInfo(SCHEDULE_POLICY.timezone)
_ON_TIME_TOLERANCE_SECONDS = SCHEDULE_POLICY.scheduled_dispatch_tolerance_seconds
_FINAL_WINDOW_STANDARD = timedelta(minutes=90)
_FINAL_WINDOW_LATE_NIGHT = timedelta(hours=3)
_DEADLINE_ACTIVE_LOOKBACK = timedelta(hours=24)
_DEEP_CHECKPOINT_HOURS = frozenset({4, 12, 21})


def _parse_jakarta(value: str | datetime, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReportContractError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportContractError(f"{label} must include timezone offset")
    return parsed.astimezone(_JAKARTA)



_REPORT_CONTINUATION_POLICY = {
    "maximum_wait_seconds": int(_ON_TIME_TOLERANCE_SECONDS),
    "poll_interval_seconds": 5,
}
# Backward-compatible alias: one Runtime-owned policy controls both freshness
# waiting and workflow terminal continuation.
_REPORT_DATA_READINESS_POLICY = _REPORT_CONTINUATION_POLICY

REPORT_ACQUISITION_STATES = frozenset({
    "ACQUISITION_NOT_STARTED",
    "ACQUISITION_QUEUED",
    "ACQUISITION_IN_PROGRESS",
    "PUBLICATION_IN_PROGRESS",
    "PUBLICATION_READY",
    "ACQUISITION_FAILED",
    "PUBLICATION_FAILED",
})
_TRANSITIONAL_REPORT_ACQUISITION_STATES = frozenset({
    "ACQUISITION_QUEUED",
    "ACQUISITION_IN_PROGRESS",
    "PUBLICATION_IN_PROGRESS",
})
_TERMINAL_SUCCESS_REPORT_ACQUISITION_STATES = frozenset({"PUBLICATION_READY"})
_TERMINAL_FAILURE_REPORT_ACQUISITION_STATES = frozenset({
    "ACQUISITION_FAILED",
    "PUBLICATION_FAILED",
})
_REPORT_DATA_FRESHNESS_LADDER = (
    "FRESH_CURRENT_PUBLICATION",
    "BOUNDED_WAIT_SAME_ACQUISITION",
    "FRESHEST_VALID_AUTHORITATIVE_PUBLICATION_WITHIN_SLA",
    "EXACT_SCOPE_GOVERNED_RECOVERY",
    "EXACT_SCOPE_DIRECT_FRESH_IF_RUNTIME_PERMITS",
    "PERMITTED_NONVOLATILE_LAST_GOOD",
    "TRUTHFUL_FIELD_LEVEL_UNAVAILABLE",
)



def _normalize_report_acquisition_state(value: Any) -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "NOT_STARTED": "ACQUISITION_NOT_STARTED",
        "QUEUED": "ACQUISITION_QUEUED",
        "PENDING": "ACQUISITION_QUEUED",
        "IN_PROGRESS": "ACQUISITION_IN_PROGRESS",
        "RUNNING": "ACQUISITION_IN_PROGRESS",
        "STARTED": "ACQUISITION_IN_PROGRESS",
        "PUBLISHING": "PUBLICATION_IN_PROGRESS",
        "PUBLISH_IN_PROGRESS": "PUBLICATION_IN_PROGRESS",
        "READY": "PUBLICATION_READY",
        "COMPLETE": "PUBLICATION_READY",
        "COMPLETED": "PUBLICATION_READY",
        "PUBLISHED": "PUBLICATION_READY",
        "SUCCESS": "PUBLICATION_READY",
        "PASS": "PUBLICATION_READY",
        "FAILED": "ACQUISITION_FAILED",
        "ERROR": "ACQUISITION_FAILED",
        "CANCELLED": "ACQUISITION_FAILED",
        "PUBLISH_FAILED": "PUBLICATION_FAILED",
        "PUBLICATION_FAILED": "PUBLICATION_FAILED",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in REPORT_ACQUISITION_STATES:
        raise ReportContractError(f"unknown report acquisition state: {raw or '<empty>'}")
    return normalized


def resolve_terminal_continuation(
    *,
    report_slot_id: str,
    workflow_run_id: str,
    workflow_reads: Sequence[Mapping[str, Any]],
    started_at: str | datetime,
    evaluated_at: str | datetime,
) -> dict[str, Any]:
    """Enforce same-run continuation across transitional workflow states.

    This function is intentionally report-plane only. It never triggers V6,
    never changes workflow identity, and never permits a transitional status to
    become the final scheduled user output.
    """
    slot_id = str(report_slot_id or "").strip()
    run_id = str(workflow_run_id or "").strip()
    if not slot_id:
        raise ReportContractError("report_slot_id is required")
    if not run_id:
        raise ReportContractError("workflow_run_id is required")
    if not workflow_reads:
        raise ReportContractError("at least one workflow read is required")

    started = _parse_jakarta(started_at, label="started_at")
    evaluated = _parse_jakarta(evaluated_at, label="evaluated_at")
    if evaluated < started:
        raise ReportContractError("evaluated_at cannot precede started_at")

    budget = int(_REPORT_CONTINUATION_POLICY["maximum_wait_seconds"])
    poll_interval = int(_REPORT_CONTINUATION_POLICY["poll_interval_seconds"])
    elapsed = (evaluated - started).total_seconds()
    reads: list[dict[str, Any]] = []
    final_state = None
    for index, raw in enumerate(workflow_reads):
        observed_run_id = str(raw.get("workflow_run_id") or run_id).strip()
        if observed_run_id != run_id:
            raise ReportContractError("workflow identity drift during continuation")
        state = _normalize_report_acquisition_state(raw.get("state"))
        read = {
            "sequence": index + 1,
            "workflow_run_id": run_id,
            "state": state,
            "observed_at": raw.get("observed_at"),
        }
        reads.append(read)
        final_state = state
        if state in _TERMINAL_SUCCESS_REPORT_ACQUISITION_STATES:
            break
        if state in _TERMINAL_FAILURE_REPORT_ACQUISITION_STATES:
            break

    assert final_state is not None
    common = {
        "report_slot_id": slot_id,
        "workflow_run_id": run_id,
        "reads": reads,
        "final_observed_state": final_state,
        "continuation_policy": dict(_REPORT_CONTINUATION_POLICY),
        "elapsed_seconds": round(elapsed, 3),
        "same_workflow_only": True,
        "start_new_acquisition": False,
        "replacement_report_slot_allowed": False,
        "intermediate_user_output_allowed": False,
        "status_only_final_output_allowed": False,
        "legacy_fallback_allowed": False,
        "v3_v4_v5_fallback_allowed": False,
    }

    if final_state in _TERMINAL_SUCCESS_REPORT_ACQUISITION_STATES:
        return {
            **common,
            "status": "TERMINAL_SUCCESS",
            "terminal": True,
            "continue_same_run": True,
            "resume_same_report_pipeline": True,
            "next_action": "RESUME_CANONICAL_REPORT_PIPELINE",
            "pipeline_resume_steps": [
                "PUBLICATION_READBACK",
                "FRESHNESS_COMPLETENESS_VERIFY",
                "DECISION_CONTEXT_HYDRATE",
                "REPORT_PREFETCH_IDENTITY_VERIFY",
                "REPORT_PREFETCH_RECOVERY_IF_NEEDED",
                "RETRIEVE",
                "DOWNSTREAM_ANALYTICS",
                "WEATHER",
                "PRE_RENDER_QA",
                "RENDER",
                "POST_RENDER_QA",
                "DELIVERY",
                "SAME_SLOT_DELIVERY_RECEIPT",
            ],
        }

    if final_state in _TERMINAL_FAILURE_REPORT_ACQUISITION_STATES:
        return {
            **common,
            "status": "TERMINAL_FAILURE",
            "terminal": True,
            "continue_same_run": True,
            "resume_same_report_pipeline": True,
            "next_action": "FAIL_OPERATIONAL_REPORT_RECOVERY",
            "pipeline_resume_steps": [
                "FRESHEST_VALID_AUTHORITATIVE_SNAPSHOT",
                "EXACT_SCOPE_GOVERNED_RECOVERY",
                "EXACT_SCOPE_DIRECT_FRESH_IF_RUNTIME_PERMITS",
                "TRUTHFUL_FIELD_LEVEL_UNAVAILABLE",
                "DECISION_CONTEXT_HYDRATE",
                "REPORT_PREFETCH_IDENTITY_VERIFY",
                "RETRIEVE",
                "DOWNSTREAM_ANALYTICS",
                "WEATHER",
                "PRE_RENDER_QA",
                "RENDER",
                "POST_RENDER_QA",
                "DELIVERY",
                "SAME_SLOT_DELIVERY_RECEIPT",
            ],
        }

    budget_exhausted = elapsed >= budget
    return {
        **common,
        "status": "CONTINUATION_BUDGET_EXHAUSTED" if budget_exhausted else "TRANSITIONAL",
        "terminal": False,
        "continue_same_run": True,
        "resume_same_report_pipeline": budget_exhausted,
        "next_action": (
            "FAIL_OPERATIONAL_REPORT_RECOVERY"
            if budget_exhausted
            else "RE_READ_SAME_WORKFLOW"
        ),
        "poll_after_seconds": 0 if budget_exhausted else poll_interval,
        "remaining_budget_seconds": max(0, round(budget - elapsed, 3)),
    }


def _publication_readiness(
    publication: Mapping[str, Any] | None,
    *,
    observed_at: datetime,
    maximum_age_minutes: float,
    required_scope: str,
) -> dict[str, Any]:
    if not isinstance(publication, Mapping):
        return {"valid": False, "reason": "PUBLICATION_MISSING"}

    generated_raw = publication.get("generated_at")
    try:
        generated = _parse_jakarta(generated_raw, label="publication.generated_at")
    except (ReportContractError, TypeError):
        return {"valid": False, "reason": "PUBLICATION_GENERATED_AT_INVALID"}

    age_minutes = (observed_at - generated).total_seconds() / 60.0
    if age_minutes < 0:
        return {"valid": False, "reason": "PUBLICATION_FROM_FUTURE"}
    if age_minutes > float(maximum_age_minutes):
        return {
            "valid": False,
            "reason": "PUBLICATION_STALE",
            "age_minutes": round(age_minutes, 3),
        }

    integrity = publication.get("publish_integrity")
    integrity_pass = bool(
        integrity == "PASS"
        or (isinstance(integrity, Mapping) and integrity.get("status") == "PASS")
    )
    provenance = publication.get("provenance")
    provenance_valid = bool(
        publication.get("provenance_valid") is True
        or (
            isinstance(provenance, Mapping)
            and provenance.get("valid") is True
        )
    )
    available_scopes = publication.get("available_scopes")
    required_scope_available = bool(
        publication.get("required_scope_available") is True
        or (
            isinstance(available_scopes, (list, tuple, set, frozenset))
            and required_scope in available_scopes
        )
    )
    publication_sha = str(
        publication.get("publication_sha")
        or publication.get("data_publication_sha")
        or publication.get("tree_sha256")
        or ""
    ).strip()

    checks = {
        "authoritative_runtime_snapshot": publication.get("authoritative_runtime_snapshot") is True,
        "publish_integrity_pass": integrity_pass,
        "provenance_valid": provenance_valid,
        "required_scope_available": required_scope_available,
        "publication_sha_present": bool(publication_sha),
        "within_freshness_sla": True,
    }
    valid = all(checks.values())
    return {
        "valid": valid,
        "reason": "PASS" if valid else "PUBLICATION_CONTRACT_FAILED",
        "generated_at": generated.isoformat(),
        "age_minutes": round(age_minutes, 3),
        "publication_sha": publication_sha or None,
        "checks": checks,
    }


def resolve_report_data_readiness(
    *,
    current_acquisition_state: str,
    current_acquisition_id: str,
    current_publication: Mapping[str, Any] | None,
    authoritative_publications: Sequence[Mapping[str, Any]],
    observed_at: str | datetime,
    maximum_age_minutes: float,
    required_scope: str,
    waited_seconds: int = 0,
) -> dict[str, Any]:
    """Resolve report-side freshness without starting a duplicate V6 acquisition.

    CURRENT_ACQUISITION_IN_PROGRESS is an orchestration state, not a data-quality
    verdict. While the same governed acquisition is still running, the report may
    consume the freshest valid authoritative publication within Runtime freshness
    limits and must re-read/recompute affected scopes when that acquisition completes.
    """
    acquisition_id = str(current_acquisition_id or "").strip()
    if not acquisition_id:
        raise ReportContractError("current_acquisition_id is required")
    scope = str(required_scope or "").strip()
    if not scope:
        raise ReportContractError("required_scope is required")
    if maximum_age_minutes < 0:
        raise ReportContractError("maximum_age_minutes must be non-negative")
    if isinstance(waited_seconds, bool) or int(waited_seconds) < 0:
        raise ReportContractError("waited_seconds must be non-negative")

    observed = _parse_jakarta(observed_at, label="observed_at")
    state = _normalize_report_acquisition_state(current_acquisition_state)
    if state == "PUBLICATION_READY":
        readiness_state = "CURRENT_PUBLICATION_READY"
    elif state in _TRANSITIONAL_REPORT_ACQUISITION_STATES:
        readiness_state = "CURRENT_ACQUISITION_IN_PROGRESS"
    elif state in _TERMINAL_FAILURE_REPORT_ACQUISITION_STATES:
        readiness_state = "CURRENT_PUBLICATION_FAILED"
    else:
        readiness_state = "NO_VALID_FRESH_SNAPSHOT"

    current_validation = _publication_readiness(
        current_publication,
        observed_at=observed,
        maximum_age_minutes=maximum_age_minutes,
        required_scope=scope,
    )

    valid_prior: list[tuple[datetime, dict[str, Any], Mapping[str, Any]]] = []
    for candidate in authoritative_publications:
        validation = _publication_readiness(
            candidate,
            observed_at=observed,
            maximum_age_minutes=maximum_age_minutes,
            required_scope=scope,
        )
        if not validation["valid"]:
            continue
        generated = _parse_jakarta(validation["generated_at"], label="publication.generated_at")
        valid_prior.append((generated, validation, candidate))
    valid_prior.sort(key=lambda item: item[0], reverse=True)
    freshest_prior = valid_prior[0] if valid_prior else None

    wait_budget = int(_REPORT_DATA_READINESS_POLICY["maximum_wait_seconds"])
    poll_interval = int(_REPORT_DATA_READINESS_POLICY["poll_interval_seconds"])
    remaining_wait = max(0, wait_budget - int(waited_seconds))

    common = {
        "readiness_state": readiness_state,
        "current_acquisition_id": acquisition_id,
        "required_scope": scope,
        "observed_at": observed.isoformat(),
        "maximum_age_minutes": float(maximum_age_minutes),
        "freshness_ladder": list(_REPORT_DATA_FRESHNESS_LADDER),
        "poll_policy": dict(_REPORT_DATA_READINESS_POLICY),
        "waited_seconds": int(waited_seconds),
        "remaining_wait_seconds": remaining_wait,
        "start_new_acquisition": False,
        "duplicate_acquisition_allowed": False,
        "legacy_fallback_allowed": False,
        "v3_v4_v5_fallback_allowed": False,
        "blanket_degraded": False,
        "current_publication_validation": current_validation,
    }

    if readiness_state == "CURRENT_PUBLICATION_READY" and current_validation["valid"]:
        return {
            **common,
            "status": "PASS",
            "source": "FRESH_CURRENT_PUBLICATION",
            "evidence_class": "FRESH_CURRENT_PUBLICATION",
            "publication": dict(current_publication or {}),
            "publication_validation": current_validation,
            "poll_same_acquisition": False,
            "recompute_on_current_completion": False,
            "next_action": "USE_CURRENT_PUBLICATION",
        }

    if freshest_prior is not None:
        _, validation, publication = freshest_prior
        return {
            **common,
            "status": "PASS",
            "source": "FRESHEST_VALID_AUTHORITATIVE_PUBLICATION_WITHIN_SLA",
            "evidence_class": "FRESHEST_VALID_AUTHORITATIVE_SNAPSHOT",
            "publication": dict(publication),
            "publication_validation": validation,
            "poll_same_acquisition": readiness_state == "CURRENT_ACQUISITION_IN_PROGRESS" and remaining_wait > 0,
            "poll_interval_seconds": poll_interval,
            "recompute_on_current_completion": readiness_state == "CURRENT_ACQUISITION_IN_PROGRESS",
            "next_action": (
                "POLL_SAME_ACQUISITION_AND_USE_AUTHORITATIVE_SNAPSHOT"
                if readiness_state == "CURRENT_ACQUISITION_IN_PROGRESS" and remaining_wait > 0
                else "USE_AUTHORITATIVE_SNAPSHOT"
            ),
        }

    if readiness_state == "CURRENT_ACQUISITION_IN_PROGRESS" and remaining_wait > 0:
        return {
            **common,
            "status": "WAITING",
            "source": None,
            "publication": None,
            "publication_validation": None,
            "poll_same_acquisition": True,
            "poll_interval_seconds": poll_interval,
            "recompute_on_current_completion": True,
            "next_action": "BOUNDED_WAIT_SAME_ACQUISITION",
        }

    return {
        **common,
        "status": "RECOVERY_REQUIRED",
        "source": None,
        "publication": None,
        "publication_validation": None,
        "poll_same_acquisition": False,
        "recompute_on_current_completion": False,
        "next_action": "EXACT_SCOPE_GOVERNED_RECOVERY",
    }


def _ceil_canonical_half_hour(value: datetime) -> datetime:
    local = value.astimezone(_JAKARTA)
    base = local.replace(
        minute=SCHEDULE_POLICY.physical_minute,
        second=0,
        microsecond=0,
    )
    if local <= base:
        return base
    return base + timedelta(minutes=SCHEDULE_POLICY.cadence_minutes)


def _canonical_recovery_deadline(intended_report_slot: datetime) -> datetime:
    return intended_report_slot + timedelta(minutes=SCHEDULE_POLICY.cadence_minutes)


def _final_window_duration(official_deadline: datetime) -> timedelta:
    local = official_deadline.astimezone(_JAKARTA)
    return _FINAL_WINDOW_LATE_NIGHT if local.hour in {0, 1} else _FINAL_WINDOW_STANDARD


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
    """Single Runtime-owned natural occurrence/recovery/final router."""
    intended = _parse_jakarta(intended_report_slot, label="intended_report_slot")
    observed = _parse_jakarta(observed_at, label="observed_at")
    if (
        intended.minute != SCHEDULE_POLICY.physical_minute
        or intended.second != 0
        or intended.microsecond != 0
    ):
        raise ReportContractError("intended_report_slot must be canonical HH:30")

    delta_seconds = (observed - intended).total_seconds()
    if delta_seconds < -_ON_TIME_TOLERANCE_SECONDS:
        raise ReportContractError("observed_at precedes canonical occurrence tolerance")

    recovery_deadline = _canonical_recovery_deadline(intended)
    if abs(delta_seconds) <= _ON_TIME_TOLERANCE_SECONDS:
        occurrence_state = "ON_TIME"
    elif observed <= recovery_deadline:
        occurrence_state = "LATE_RECOVERABLE"
    else:
        occurrence_state = "LATE_EXPIRED"

    deadline = (
        _parse_jakarta(official_deadline, label="official_deadline")
        if official_deadline is not None
        else None
    )
    deadline_active_start = None
    final_trigger_at = None
    first_final_checkpoint = None
    deadline_active = False
    final_active = False
    deadline_locked = False
    if deadline is not None:
        deadline_active_start = _ceil_canonical_half_hour(
            deadline - _DEADLINE_ACTIVE_LOOKBACK
        )
        final_trigger_at = deadline - _final_window_duration(deadline)
        first_final_checkpoint = _ceil_canonical_half_hour(final_trigger_at)
        deadline_locked = intended >= deadline
        deadline_active = deadline_active_start <= intended < deadline
        final_active = first_final_checkpoint <= intended < deadline

    fixed_deep = intended.hour in _DEEP_CHECKPOINT_HOURS
    price_checkpoint = intended.hour == 5

    if deadline_locked:
        base_mode = "SILENT"
    elif final_active:
        base_mode = "FINAL"
    elif deadline_active:
        base_mode = "DEADLINE"
    elif post_all_match_due and fixed_deep:
        base_mode = "POST_ALL_MATCH"
    elif fixed_deep:
        base_mode = "DEEP"
    elif price_checkpoint:
        base_mode = "PRICE"
    elif match_live:
        base_mode = "MATCH"
    else:
        base_mode = "SILENT"

    embedded_obligations: list[str] = []
    if price_checkpoint and base_mode in {"DEADLINE", "FINAL"}:
        embedded_obligations.append("PRICE")

    if match_live and not deadline_locked:
        if base_mode == "FINAL":
            route_mode = "FINAL+MATCH"
        elif base_mode == "DEADLINE":
            route_mode = "DEADLINE+MATCH"
        elif base_mode in {"DEEP", "POST_ALL_MATCH"}:
            route_mode = "FULL+MATCH"
            if base_mode == "POST_ALL_MATCH":
                embedded_obligations.append("POST_ALL_MATCH")
        elif base_mode == "PRICE":
            route_mode = "MATCH"
            embedded_obligations.append("PRICE_COMPACT")
        else:
            route_mode = "MATCH"
    else:
        route_mode = base_mode

    canonical_visible_due = route_mode != "SILENT"
    visible_due = canonical_visible_due and occurrence_state != "LATE_EXPIRED"
    late_catch_up = canonical_visible_due and occurrence_state == "LATE_RECOVERABLE"

    prefetch_state = str(report_prefetch_state or "UNKNOWN").strip().upper()
    if visible_due and prefetch_state in {"STALE", "MISSING", "INCOMPLETE", "MISMATCH"}:
        prefetch_action = "GOVERNED_REFRESH_THEN_CONTINUE"
    else:
        prefetch_action = "NONE"

    return {
        "intended_report_slot": intended.isoformat(),
        "observed_at": observed.isoformat(),
        "dispatch_delta_seconds": delta_seconds,
        "on_time_tolerance_seconds": _ON_TIME_TOLERANCE_SECONDS,
        "recovery_deadline": recovery_deadline.isoformat(),
        "occurrence_state": occurrence_state,
        "late_catch_up": late_catch_up,
        "official_deadline": deadline.isoformat() if deadline is not None else None,
        "deadline_active_start": (
            deadline_active_start.isoformat() if deadline_active_start is not None else None
        ),
        "final_trigger_at": final_trigger_at.isoformat() if final_trigger_at is not None else None,
        "first_final_checkpoint": (
            first_final_checkpoint.isoformat() if first_final_checkpoint is not None else None
        ),
        "deadline_active": deadline_active,
        "final_active": final_active,
        "deadline_locked": deadline_locked,
        "route_mode": route_mode,
        "canonical_visible_occurrence_due": canonical_visible_due,
        "visible_occurrence_due": visible_due,
        "delivery_required": visible_due,
        "historical_delivery_state": (
            "UNDELIVERED"
            if canonical_visible_due and occurrence_state == "LATE_EXPIRED"
            else None
        ),
        "visible_report_count": 1 if visible_due else 0,
        "embedded_obligations": embedded_obligations,
        "v6_degraded": bool(v6_degraded),
        "transport_failed": bool(transport_failed),
        "report_prefetch_state": prefetch_state,
        "report_prefetch_action": prefetch_action,
        "data_slot_report_slot_delivery_independent": True,
        "v6_data_plane_backfill_allowed": False,
        "future_fill_allowed": False,
        "replacement_report_slot_allowed": False,
    }


def evaluate_rolling_natural_acceptance(
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Latest 12 genuine natural occurrences; visible slots require delivery proof."""
    target = 12
    forbidden_markers = (
        "manual",
        "recovery",
        "report_prefetch",
        "ad_hoc",
        "retro",
        "future_fill",
    )
    countable: list[dict[str, Any]] = []
    for raw in occurrences:
        row = dict(raw)
        if row.get("natural") is not True:
            continue
        if str(row.get("schedule_kind") or "") != "chatgpt_scheduler":
            continue
        if any(row.get(marker) is True for marker in forbidden_markers):
            continue
        logical = _parse_jakarta(row.get("logical_slot"), label="logical_slot")
        row["_logical"] = logical
        countable.append(row)

    countable.sort(key=lambda row: row["_logical"])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in countable:
        key = row["_logical"].isoformat()
        grouped.setdefault(key, []).append(row)

    duplicate_logical_slots = sorted(
        key for key, rows in grouped.items() if len(rows) > 1
    )
    unique_rows = [rows[-1] for _, rows in sorted(grouped.items())]
    latest = unique_rows[-target:]

    rendered_window: list[dict[str, Any]] = []
    pass_count = 0
    for row in latest:
        visible_due = row.get("mandatory_visible_report") is True
        core_pass = bool(
            row.get("core_acceptance_pass") is True
            or str(row.get("core_acceptance") or "").strip().upper() == "PASS"
        )
        delivery_pass = True
        if visible_due:
            canonical_receipt = row.get("canonical_report_receipt")
            if canonical_receipt is not None:
                # Receipt validity stays owned by report_delivery. Runtime only
                # consumes its exact same-slot acceptance predicate.
                from .report_delivery import canonical_receipt_acceptance

                delivery_pass = canonical_receipt_acceptance(
                    canonical_receipt,
                    expected_report_slot_id=(
                        str(row.get("report_slot_id") or "").strip() or None
                    ),
                    expected_occurrence_identity=(
                        str(row.get("occurrence_identity") or "").strip() or None
                    ),
                )
            else:
                # Backward-compatible historical rows remain truthful; P0.5 does
                # not synthesize a receipt that was not present at occurrence time.
                delivery_pass = bool(
                    row.get("report_contract_pass") is True
                    and row.get("report_slot_fulfilled") is True
                    and row.get("delivery_proof_valid") is True
                    and row.get("visible_emitted") is True
                    and row.get("status_only") is not True
                )
        accepted = core_pass and delivery_pass
        if accepted:
            pass_count += 1
        public = {key: value for key, value in row.items() if key != "_logical"}
        public["acceptance"] = "PASS" if accepted else "FAIL"
        rendered_window.append(public)

    zero_misses = len(latest) == target
    if zero_misses:
        for left, right in zip(latest, latest[1:]):
            if right["_logical"] - left["_logical"] != timedelta(hours=1):
                zero_misses = False
                break

    production_green = bool(
        len(latest) == target
        and pass_count == target
        and zero_misses
        and not duplicate_logical_slots
    )
    return {
        "window_target": target,
        "countable_natural_count": len(unique_rows),
        "pass_count": pass_count,
        "zero_misses": zero_misses,
        "duplicate_logical_slots": duplicate_logical_slots,
        "latest_window": rendered_window,
        "production_green": production_green,
    }


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
    report_delivered = bool(visible_emitted)
    report_slot_fulfilled = bool(
        report_delivered and report_contract_pass and delivery_proof_valid
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
        action, status, report_blocking, degraded, reason = (
            "READ_V6", "PASS", False, False, "FRESH_V6"
        )
        scoped_direct_fresh_allowed = False
    elif source == "V6_RETRIEVAL_RECOVERY":
        action, status, report_blocking, degraded, reason = (
            "SAME_V6_RETRIEVAL_RECOVERY",
            "RECOVERY_REQUIRED",
            bool(required),
            not bool(required),
            f"RETRIEVAL_{str(retrieval_state or '').strip().upper()}",
        )
        scoped_direct_fresh_allowed = False
    elif source == "DIRECT_FRESH":
        action, status, report_blocking, degraded, reason = (
            "SCOPED_DIRECT_FRESH", "PASS", False, False, "VERIFIED_V6_SCOPE_FAILURE"
        )
        scoped_direct_fresh_allowed = True
    elif source == "LAST_GOOD_NONVOLATILE":
        action, status, report_blocking, degraded, reason = (
            "READ_LAST_GOOD_NONVOLATILE",
            "PASS",
            False,
            False,
            "NONVOLATILE_LAST_GOOD_RECOVERY",
        )
        scoped_direct_fresh_allowed = False
    else:
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
        scope_id for scope_id, result in resolved.items() if result["report_blocking"]
    ]
    degraded_scopes = [
        scope_id for scope_id, result in resolved.items() if result["degraded"]
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
