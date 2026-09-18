from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError
from src.runtime_v6.domains.control_plane.orchestration_acceptance import (
    evaluate_occurrence_acceptance,
)
from src.runtime_v6.report_recovery import plan_report_catch_up
from src.runtime_v6.runtime_control import build_operational_slots, build_runtime_control


def _generic_occurrence_fixture() -> dict:
    logical_slot = datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc).isoformat()
    return {
        "natural_occurrence": {
            "occurrence_id": "scheduler-occurrence-generic-001",
            "occurrence_count": 1,
            "natural": True,
            "logical_slot": logical_slot,
            "schedule_kind": "chatgpt_scheduler",
        },
        "audit_transport": {
            "status": "PASS",
            "connector_result_available": True,
            "read_after_write_exact": True,
        },
        "core_execution": {
            "logical_slot": logical_slot,
            "acquisition_logical_slot": logical_slot,
            "publication_logical_slot": logical_slot,
            "schedule_kind": "chatgpt_scheduler",
            "logical_slot_source": "GOVERNED_TRIGGER_EVENT",
            "trigger_event_name": "issues",
            "workflow_run_id": "workflow-run-generic-001",
            "acquisition_run_id": "collect-job-generic-001",
            "publication_run_id": "publish-job-generic-001",
            "orchestration_fulfillment_run_id": "fulfillment-job-generic-001",
            "publication_generation_id": "publication-generation-generic-001",
            "chatgpt_scheduler_proof": True,
            "counts_as_completed_operational_slot": True,
            "authoritative_runtime_snapshot": True,
            "publish_integrity": "PASS",
            "collect": "PASS",
            "publish": "PASS",
            "orchestration_fulfillment": "PASS",
            "acquisition_count": 1,
            "publication_count": 1,
            "due_source_set_id": "due-source-set-generic-001",
            "source_freshness_due_set_id": "due-source-set-generic-001",
            "source_freshness_evaluated": True,
            "cross_slot_mix": False,
            "cross_generation_mix": False,
            "report_prefetch_satisfied_core": False,
            "manual_recovery_counted_natural": False,
            "retro_fill": False,
            "future_fill": False,
        },
    }


def test_01_normal_natural_occurrence_with_exact_issue_mutation_readback_passes():
    result = evaluate_occurrence_acceptance(_generic_occurrence_fixture())

    assert result["AUDIT_TRANSPORT"] == "PASS"
    assert result["CORE_EXECUTION"] == "PASS"
    assert result["SCHEDULER_PROOF"] == "PASS"


def test_02_exact_read_after_write_mismatch_is_audit_failure_not_automatic_core_failure():
    evidence = _generic_occurrence_fixture()
    evidence["audit_transport"] = {
        "status": "FAILED_READ_AFTER_WRITE_MISMATCH",
        "connector_result_available": True,
        "read_after_write_exact": False,
    }

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_READ_AFTER_WRITE_MISMATCH"
    assert result["CORE_EXECUTION"] == "PASS"


def test_03_orchestration_suppressed_before_connector_result_can_use_complete_independent_proof():
    evidence = _generic_occurrence_fixture()
    evidence["audit_transport"] = {
        "status": "FAILED_ORCHESTRATION_TOOL_ROUTING",
        "connector_result_available": False,
        "read_after_write_exact": False,
    }

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_ORCHESTRATION_TOOL_ROUTING"
    assert result["CORE_EXECUTION"] == "PASS"
    assert result["SCHEDULER_PROOF"] == "PASS"


def test_04_explicit_connector_error_remains_separate_when_independent_execution_is_proven():
    evidence = _generic_occurrence_fixture()
    evidence["audit_transport"] = {
        "status": "FAILED_CONNECTOR",
        "connector_result_available": True,
        "read_after_write_exact": False,
    }

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_CONNECTOR"
    assert result["CORE_EXECUTION"] == "PASS"


def test_05_independent_runtime_proof_complete_can_verify_core_without_positive_audit_transport():
    evidence = _generic_occurrence_fixture()
    evidence["audit_transport"] = {
        "status": "FAILED_ORCHESTRATION_TOOL_ROUTING",
        "connector_result_available": False,
        "read_after_write_exact": False,
    }

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_TRIGGER"] == "PASS"
    assert result["CORE_EXECUTION"] == "PASS"
    assert result["missing_or_invalid"] == []


def test_06_independent_runtime_proof_incomplete_fails_closed():
    evidence = _generic_occurrence_fixture()
    evidence["audit_transport"]["status"] = "FAILED_ORCHESTRATION_TOOL_ROUTING"
    evidence["audit_transport"]["connector_result_available"] = False
    evidence["audit_transport"]["read_after_write_exact"] = False
    evidence["core_execution"]["publication_generation_id"] = None

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert result["SCHEDULER_PROOF"] == "UNVERIFIED"
    assert "core_execution.publication_generation_id" in result["missing_or_invalid"]


def test_07_duplicate_natural_occurrence_fails_closed():
    evidence = _generic_occurrence_fixture()
    evidence["natural_occurrence"]["occurrence_count"] = 2

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "natural_occurrence.occurrence_count" in result["missing_or_invalid"]


def test_08_duplicate_acquisition_attempt_fails_closed():
    evidence = _generic_occurrence_fixture()
    evidence["core_execution"]["acquisition_count"] = 2

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.acquisition_count" in result["missing_or_invalid"]


def test_09_report_prefetch_cannot_satisfy_core():
    evidence = _generic_occurrence_fixture()
    evidence["core_execution"]["report_prefetch_satisfied_core"] = True

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.report_prefetch_satisfied_core" in result["missing_or_invalid"]


def test_10_manual_recovery_cannot_count_as_natural():
    evidence = _generic_occurrence_fixture()
    evidence["core_execution"]["manual_recovery_counted_natural"] = True

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.manual_recovery_counted_natural" in result["missing_or_invalid"]


def _natural_control(*, logical_hour_utc: int, run_id: str) -> dict:
    logical_slot = datetime(2030, 1, 1, logical_hour_utc, 0, tzinfo=timezone.utc)
    observed_at = datetime(2030, 1, 1, logical_hour_utc, 30, tzinfo=timezone.utc)
    return build_runtime_control(
        {},
        now=observed_at,
        event_name="issues",
        run_id=run_id,
        schedule_kind="chatgpt_scheduler",
        logical_slot=logical_slot.isoformat(),
    )


def test_11_previous_missing_slot_remains_historical_missing():
    ledger = build_operational_slots({}, _natural_control(logical_hour_utc=6, run_id="run-6"))
    ledger = build_operational_slots(ledger, _natural_control(logical_hour_utc=8, run_id="run-8"))
    missing_before = [row for row in ledger["slots"] if row["fulfilled_by"] == "MISSING"]
    assert len(missing_before) == 1

    ledger = build_operational_slots(ledger, _natural_control(logical_hour_utc=9, run_id="run-9"))
    missing_after = [row for row in ledger["slots"] if row["fulfilled_by"] == "MISSING"]

    assert missing_after == missing_before
    assert missing_after[0]["fulfilled"] is False


def test_12_future_fill_is_rejected():
    evidence = _generic_occurrence_fixture()
    evidence["core_execution"]["future_fill"] = True

    result = evaluate_occurrence_acceptance(evidence)

    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.future_fill" in result["missing_or_invalid"]


def test_13_provenance_source_is_truthful_and_never_claims_chatgpt_command_without_command_proof():
    evidence = _generic_occurrence_fixture()
    passed = evaluate_occurrence_acceptance(evidence)
    assert passed["logical_slot_source"] == "GOVERNED_TRIGGER_EVENT"
    assert passed["CORE_EXECUTION"] == "PASS"

    evidence["core_execution"]["logical_slot_source"] = "CHATGPT_COMMAND"
    failed = evaluate_occurrence_acceptance(evidence)
    assert failed["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.logical_slot_source" in failed["missing_or_invalid"]


def test_14_cross_generation_or_cross_slot_mix_is_rejected():
    generation_mix = _generic_occurrence_fixture()
    generation_mix["core_execution"]["cross_generation_mix"] = True
    generation_result = evaluate_occurrence_acceptance(generation_mix)
    assert generation_result["CORE_EXECUTION"] == "UNVERIFIED"

    slot_mix = _generic_occurrence_fixture()
    slot_mix["core_execution"]["publication_logical_slot"] = datetime(
        2030, 1, 1, 7, 0, tzinfo=timezone.utc
    ).isoformat()
    slot_result = evaluate_occurrence_acceptance(slot_mix)
    assert slot_result["CORE_EXECUTION"] == "UNVERIFIED"
    assert "core_execution.publication_logical_slot" in slot_result["missing_or_invalid"]


def test_15_visible_report_remains_required_during_audit_transport_degradation():
    evidence = _generic_occurrence_fixture()
    evidence["visible_report_due"] = True
    evidence["audit_transport"] = {
        "status": "FAILED_ORCHESTRATION_TOOL_ROUTING",
        "connector_result_available": False,
        "read_after_write_exact": False,
    }
    evidence["core_execution"]["publish"] = "FAIL"

    result = evaluate_occurrence_acceptance(evidence)

    assert result["AUDIT_TRANSPORT"] == "FAILED_ORCHESTRATION_TOOL_ROUTING"
    assert result["CORE_EXECUTION"] == "UNVERIFIED"
    assert result["VISIBLE_REPORT_REQUIREMENT"] == "REQUIRED"


def test_16_missed_report_recovery_uses_original_slot_only_inside_explicit_deadline():
    result = plan_report_catch_up(
        logical_slot="2030-01-01T04:30:00+07:00",
        report_type="DEEP",
        observed_at="2030-01-01T04:45:00+07:00",
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
        catch_up_deadline="2030-01-01T05:00:00+07:00",
    )

    assert result["catch_up_required"] is True
    assert result["next_action"] == "CATCH_UP_BUILD"
    assert result["report_slot_id"] == "2030-01-01T04:30+07:00|DEEP"
    assert result["v6_data_plane_mutation_allowed"] is False


def test_17_missed_report_recovery_without_explicit_deadline_fails_closed():
    with pytest.raises(DeliveryIntegrityError, match="explicit catch_up_deadline"):
        plan_report_catch_up(
            logical_slot="2030-01-01T04:30:00+07:00",
            report_type="DEEP",
            observed_at="2030-01-01T04:45:00+07:00",
            report_state="NOT_STARTED",
            delivered_report_slot_id=None,
            delivery_proof_valid=False,
            catch_up_deadline=None,
        )


def test_18_deadline_active_visible_occurrence_is_required_independently_of_audit_transport():
    evidence = _generic_occurrence_fixture()
    evidence["visible_report_due"] = True
    evidence["visible_report_mode"] = "deadline_mode"
    evidence["audit_transport"] = {
        "status": "FAILED_ORCHESTRATION_TOOL_ROUTING",
        "connector_result_available": False,
        "read_after_write_exact": False,
    }

    result = evaluate_occurrence_acceptance(evidence)

    assert result["VISIBLE_REPORT_MODE"] == "deadline_mode"
    assert result["VISIBLE_REPORT_REQUIREMENT"] == "REQUIRED"
    assert result["CORE_EXECUTION"] == "PASS"
