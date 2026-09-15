from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError
from src.runtime_v6.report_recovery import (
    plan_report_catch_up,
    plan_same_run_recovery,
)


LOGICAL_SLOT = "2026-09-16T04:30:00+07:00"
REPORT_SLOT_ID = "2026-09-16T04:30+07:00|DEEP"


def _same_run(**overrides):
    values = {
        "logical_slot": LOGICAL_SLOT,
        "report_type": "DEEP",
        "report_state": "QA_FAILED",
        "delivered_report_slot_id": None,
        "delivery_proof_valid": False,
        "recovery_action": "RENDER_RECOVERY",
        "attempt_count": 0,
        "max_attempts": 2,
    }
    values.update(overrides)
    return plan_same_run_recovery(**values)


def _catch_up(**overrides):
    values = {
        "logical_slot": LOGICAL_SLOT,
        "report_type": "DEEP",
        "observed_at": "2026-09-16T04:45:00+07:00",
        "report_state": "NOT_STARTED",
        "delivered_report_slot_id": None,
        "delivery_proof_valid": False,
    }
    values.update(overrides)
    return plan_report_catch_up(**values)


def test_qa_failed_retries_immediately_in_same_report_slot_within_budget():
    result = _same_run()

    assert result["report_slot_id"] == REPORT_SLOT_ID
    assert result["recovery_mode"] == "SAME_RUN"
    assert result["retry_now"] is True
    assert result["retry_exhausted"] is False
    assert result["attempt_count"] == 0
    assert result["next_attempt_count"] == 1
    assert result["max_attempts"] == 2
    assert result["next_action"] == "RENDER_RECOVERY"
    assert result["report_required"] is True
    assert result["catch_up_eligible"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["v6_data_plane_mutation_allowed"] is False


def test_delivery_proof_failure_retries_only_delivery_proof_stage_in_same_run():
    result = _same_run(
        report_state="DELIVERED",
        delivered_report_slot_id=REPORT_SLOT_ID,
        delivery_proof_valid=False,
        recovery_action="DELIVERY_PROOF_RECOVERY",
        attempt_count=1,
        max_attempts=3,
    )

    assert result["retry_now"] is True
    assert result["next_attempt_count"] == 2
    assert result["next_action"] == "DELIVERY_PROOF_RECOVERY"
    assert result["report_required"] is True
    assert result["report_delivered"] is False


def test_valid_same_slot_delivery_receipt_suppresses_any_same_run_retry():
    result = _same_run(
        report_state="DELIVERED",
        delivered_report_slot_id=REPORT_SLOT_ID,
        delivery_proof_valid=True,
        recovery_action="DELIVERY_PROOF_RECOVERY",
    )

    assert result["report_delivered"] is True
    assert result["report_required"] is False
    assert result["retry_now"] is False
    assert result["retry_exhausted"] is False
    assert result["next_action"] == "NONE"
    assert result["duplicate"] is True


def test_same_run_retry_budget_exhaustion_never_marks_report_delivered_or_duplicates_it():
    result = _same_run(attempt_count=2, max_attempts=2)

    assert result["retry_now"] is False
    assert result["retry_exhausted"] is True
    assert result["report_required"] is True
    assert result["report_delivered"] is False
    assert result["duplicate"] is False
    assert result["catch_up_eligible"] is True
    assert result["next_action"] == "SCHEDULE_CATCH_UP"


def test_same_run_recovery_rejects_invalid_budget_and_non_recovery_action():
    with pytest.raises(DeliveryIntegrityError):
        _same_run(attempt_count=-1)
    with pytest.raises(DeliveryIntegrityError):
        _same_run(max_attempts=0)
    with pytest.raises(DeliveryIntegrityError):
        _same_run(recovery_action="V3_FALLBACK")


def test_missed_not_started_report_is_caught_up_using_original_logical_slot_identity():
    result = _catch_up(observed_at="2026-09-16T06:10:00+07:00")

    assert result["report_slot_id"] == REPORT_SLOT_ID
    assert result["catch_up_required"] is True
    assert result["start_build"] is True
    assert result["duplicate"] is False
    assert result["next_action"] == "CATCH_UP_BUILD"
    assert result["underlying_reason"] == "DUE_REPORT"
    assert result["observed_at"] == "2026-09-16T06:10:00+07:00"
    assert result["legacy_fallback_allowed"] is False
    assert result["v6_data_plane_mutation_allowed"] is False


def test_failed_report_slot_catch_up_preserves_same_slot_recovery_semantics():
    result = _catch_up(report_state="QA_FAILED")

    assert result["catch_up_required"] is True
    assert result["start_build"] is True
    assert result["next_action"] == "CATCH_UP_SAME_SLOT_RECOVERY"
    assert result["underlying_reason"] == "SAME_SLOT_RECOVERY"
    assert result["report_slot_id"] == REPORT_SLOT_ID


def test_invalid_delivered_state_catch_up_runs_delivery_proof_recovery_not_full_rebuild():
    result = _catch_up(
        report_state="DELIVERED",
        delivered_report_slot_id=REPORT_SLOT_ID,
        delivery_proof_valid=False,
    )

    assert result["catch_up_required"] is True
    assert result["start_build"] is True
    assert result["next_action"] == "CATCH_UP_DELIVERY_PROOF_RECOVERY"
    assert result["underlying_reason"] == "DELIVERY_PROOF_RECOVERY"


def test_active_build_never_starts_parallel_catch_up():
    result = _catch_up(report_state="BUILDING")

    assert result["catch_up_required"] is False
    assert result["start_build"] is False
    assert result["report_required"] is True
    assert result["next_action"] == "WAIT_FOR_ACTIVE_BUILD"
    assert result["underlying_reason"] == "SAME_SLOT_BUILD_IN_PROGRESS"


def test_valid_delivery_proof_prevents_catch_up_and_marks_duplicate_only_for_same_slot():
    delivered = _catch_up(
        report_state="DELIVERED",
        delivered_report_slot_id=REPORT_SLOT_ID,
        delivery_proof_valid=True,
    )

    assert delivered["catch_up_required"] is False
    assert delivered["report_delivered"] is True
    assert delivered["duplicate"] is True
    assert delivered["next_action"] == "NONE"


def test_catch_up_rejects_observation_before_logical_slot_and_never_rekeys_to_observed_time():
    with pytest.raises(DeliveryIntegrityError):
        _catch_up(observed_at="2026-09-16T04:29:59+07:00")

    result = _catch_up(observed_at="2026-09-16T21:30:00+07:00")
    assert result["report_slot_id"] == REPORT_SLOT_ID
    assert "21:30" not in result["report_slot_id"]


def test_catch_up_at_exact_logical_slot_is_regular_due_work_not_a_catch_up():
    result = _catch_up(observed_at=LOGICAL_SLOT)

    assert result["catch_up_required"] is False
    assert result["start_build"] is False
    assert result["next_action"] == "REGULAR_SLOT_DUE"
    assert result["underlying_reason"] == "DUE_REPORT"
