from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from src.runtime_v6.domains.control_plane.orchestration_acceptance import (
    evaluate_occurrence_acceptance,
)


def _generic_occurrence_fixture() -> dict:
    logical_slot = datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc).isoformat()
    return {
        "natural_occurrence": {
            "occurrence_id": "scheduler-occurrence-generic-001",
            "natural": True,
            "logical_slot": logical_slot,
            "schedule_kind": "chatgpt_scheduler",
        },
        "audit_transport": {
            "status": "FAILED_ORCHESTRATION_TOOL_ROUTING",
            "connector_result_available": False,
            "read_after_write_exact": False,
        },
        "core_execution": {
            "logical_slot": logical_slot,
            "schedule_kind": "chatgpt_scheduler",
            "logical_slot_source": "GOVERNED_ISSUE_EVENT",
            "workflow_run_id": "workflow-run-generic-001",
            "acquisition_run_id": "acquisition-run-generic-001",
            "publication_generation_id": "publication-generic-001",
            "chatgpt_scheduler_proof": True,
            "counts_as_completed_operational_slot": True,
            "authoritative_runtime_snapshot": True,
            "publish_integrity": "PASS",
            "collect": "PASS",
            "publish": "PASS",
            "orchestration_fulfillment": "PASS",
            "acquisition_count": 1,
            "publication_count": 1,
            "source_freshness_evaluated": True,
            "cross_slot_mix": False,
            "cross_generation_mix": False,
            "report_prefetch_satisfied_core": False,
            "manual_recovery_counted_natural": False,
            "retro_fill": False,
            "future_fill": False,
        },
    }


def test_natural_occurrence_can_be_core_verified_when_audit_transport_result_is_suppressed():
    evidence = _generic_occurrence_fixture()

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_ORCHESTRATION_TOOL_ROUTING"
    assert result["CORE_EXECUTION"] == "PASS"
    assert result["SCHEDULER_PROOF"] == "PASS"
    assert result["logical_slot"] == evidence["natural_occurrence"]["logical_slot"]


def test_suppressed_audit_transport_still_fails_closed_when_independent_proof_is_incomplete():
    evidence = deepcopy(_generic_occurrence_fixture())
    evidence["core_execution"]["publication_generation_id"] = None

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_ORCHESTRATION_TOOL_ROUTING"
    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert result["SCHEDULER_PROOF"] == "UNVERIFIED"
    assert "publication_generation_id" in result["missing_or_invalid"]
