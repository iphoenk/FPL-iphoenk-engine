from __future__ import annotations

"""Fail-closed acceptance for natural scheduler occurrence vs audit transport.

This module deliberately does not trigger acquisition, publication, recovery, or
report prefetch. It only evaluates evidence owned by the platform occurrence
and immutable repository execution surfaces.
"""

from datetime import datetime
from typing import Any, Mapping


NATURAL_SCHEDULE_KIND = "chatgpt_scheduler"
TRUTHFUL_TRIGGER_SOURCES = frozenset(
    {
        "GOVERNED_TRIGGER_EVENT",
        "GOVERNED_ISSUE_EVENT",
    }
)
AUDIT_PASS = "PASS"
AUDIT_ROUTING_FAILURE = "FAILED_ORCHESTRATION_TOOL_ROUTING"
AUDIT_CONNECTOR_FAILURE = "FAILED_CONNECTOR"
AUDIT_READBACK_MISMATCH = "FAILED_READ_AFTER_WRITE_MISMATCH"


class OrchestrationAcceptanceError(ValueError):
    pass


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrchestrationAcceptanceError(f"{label} must be an object")
    return value


def _aware(value: Any, label: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _truthy_id(value: Any) -> bool:
    return bool(str(value or "").strip())


def _audit_status(audit: Mapping[str, Any]) -> tuple[str, list[str]]:
    requested = str(audit.get("status") or "UNVERIFIED").strip().upper()
    failures: list[str] = []

    if requested == AUDIT_PASS:
        if audit.get("connector_result_available") is not True:
            failures.append("audit.connector_result_available")
        if audit.get("read_after_write_exact") is not True:
            failures.append("audit.read_after_write_exact")
        return (AUDIT_PASS if not failures else "UNVERIFIED"), failures

    if requested in {
        AUDIT_ROUTING_FAILURE,
        AUDIT_CONNECTOR_FAILURE,
        AUDIT_READBACK_MISMATCH,
    }:
        return requested, failures

    return "UNVERIFIED", ["audit.status"]


def _same_slot(
    occurrence_slot: datetime,
    value: Any,
    *,
    field: str,
    failures: list[str],
) -> None:
    parsed = _aware(value, field)
    if parsed is None or parsed != occurrence_slot:
        failures.append(field)


def _validate_independent_core(
    occurrence: Mapping[str, Any],
    core: Mapping[str, Any],
) -> tuple[list[str], datetime | None]:
    failures: list[str] = []

    occurrence_slot = _aware(occurrence.get("logical_slot"), "natural_occurrence.logical_slot")
    if occurrence_slot is None:
        failures.append("natural_occurrence.logical_slot")

    if occurrence.get("natural") is not True:
        failures.append("natural_occurrence.natural")
    if occurrence.get("occurrence_count") != 1:
        failures.append("natural_occurrence.occurrence_count")
    if not _truthy_id(occurrence.get("occurrence_id")):
        failures.append("natural_occurrence.occurrence_id")
    if str(occurrence.get("schedule_kind") or "") != NATURAL_SCHEDULE_KIND:
        failures.append("natural_occurrence.schedule_kind")

    if occurrence_slot is not None:
        for field in (
            "logical_slot",
            "acquisition_logical_slot",
            "publication_logical_slot",
        ):
            _same_slot(
                occurrence_slot,
                core.get(field),
                field=f"core_execution.{field}",
                failures=failures,
            )

    if str(core.get("schedule_kind") or "") != NATURAL_SCHEDULE_KIND:
        failures.append("core_execution.schedule_kind")

    source = str(core.get("logical_slot_source") or "").strip().upper()
    if source not in TRUTHFUL_TRIGGER_SOURCES:
        failures.append("core_execution.logical_slot_source")
    if source == "CHATGPT_COMMAND":
        failures.append("core_execution.logical_slot_source")

    required_ids = (
        "workflow_run_id",
        "acquisition_run_id",
        "publication_run_id",
        "orchestration_fulfillment_run_id",
        "publication_generation_id",
    )
    identity_values: list[str] = []
    for field in required_ids:
        if not _truthy_id(core.get(field)):
            failures.append(f"core_execution.{field}")
        else:
            identity_values.append(str(core.get(field)).strip())
    if len(identity_values) != len(set(identity_values)):
        failures.append("core_execution.identity_collision")

    if str(core.get("trigger_event_name") or "").strip() != "issues":
        failures.append("core_execution.trigger_event_name")

    required_true = (
        "chatgpt_scheduler_proof",
        "counts_as_completed_operational_slot",
        "authoritative_runtime_snapshot",
        "source_freshness_evaluated",
    )
    for field in required_true:
        if core.get(field) is not True:
            failures.append(f"core_execution.{field}")

    due_set = str(core.get("due_source_set_id") or "").strip()
    evaluated_due_set = str(core.get("source_freshness_due_set_id") or "").strip()
    if not due_set or not evaluated_due_set or due_set != evaluated_due_set:
        failures.append("core_execution.source_freshness_due_set_id")

    required_pass = (
        "publish_integrity",
        "collect",
        "publish",
        "orchestration_fulfillment",
    )
    for field in required_pass:
        if str(core.get(field) or "").strip().upper() != "PASS":
            failures.append(f"core_execution.{field}")

    for field in ("acquisition_count", "publication_count"):
        if core.get(field) != 1:
            failures.append(f"core_execution.{field}")

    forbidden_true = (
        "cross_slot_mix",
        "cross_generation_mix",
        "report_prefetch_satisfied_core",
        "manual_recovery_counted_natural",
        "retro_fill",
        "future_fill",
    )
    for field in forbidden_true:
        if core.get(field) is True:
            failures.append(f"core_execution.{field}")

    return sorted(set(failures)), occurrence_slot


def evaluate_occurrence_acceptance(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate natural occurrence independently from the audit transport result.

    A failed or suppressed ChatGPT connector result never becomes positive core
    evidence. Core PASS is possible only when the independent immutable
    execution proof is complete and coherent for the exact same logical slot.
    """

    payload = _mapping(evidence, "evidence")
    occurrence = _mapping(payload.get("natural_occurrence"), "natural_occurrence")
    audit = _mapping(payload.get("audit_transport"), "audit_transport")
    core = _mapping(payload.get("core_execution"), "core_execution")

    audit_state, audit_failures = _audit_status(audit)
    core_failures, occurrence_slot = _validate_independent_core(occurrence, core)
    core_pass = not core_failures

    report_due = payload.get("visible_report_due") is True
    return {
        "CORE_TRIGGER": "PASS" if occurrence_slot is not None and occurrence.get("natural") is True else "UNVERIFIED",
        "AUDIT_TRANSPORT": audit_state,
        "CORE_EXECUTION": "PASS" if core_pass else "UNVERIFIED",
        "SCHEDULER_PROOF": "PASS" if core_pass else "UNVERIFIED",
        "VISIBLE_REPORT_REQUIREMENT": "REQUIRED" if report_due else "N/A",
        "logical_slot": occurrence.get("logical_slot"),
        "occurrence_id": occurrence.get("occurrence_id"),
        "logical_slot_source": core.get("logical_slot_source"),
        "missing_or_invalid": sorted(set(audit_failures + core_failures)),
        "governance": {
            "audit_transport_is_not_core_execution_proof": True,
            "connector_result_absence_never_fabricates_mutation_success": True,
            "independent_execution_proof_required": True,
            "report_prefetch_cannot_satisfy_core": True,
            "manual_recovery_cannot_count_natural": True,
            "historical_slots_never_backfilled_by_acceptance": True,
        },
    }
