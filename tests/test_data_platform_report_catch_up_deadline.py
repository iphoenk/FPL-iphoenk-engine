from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError
from src.runtime_v6.report_recovery import plan_report_catch_up


SLOT = "2026-09-16T04:30:00+07:00"
DEADLINE = "2026-09-16T05:00:00+07:00"


def _plan(*, observed_at: str, deadline: str = DEADLINE):
    return plan_report_catch_up(
        logical_slot=SLOT,
        report_type="DEEP",
        observed_at=observed_at,
        catch_up_deadline=deadline,
        report_state="NOT_STARTED",
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )


def test_delayed_report_inside_catch_up_window_builds_original_slot():
    result = _plan(observed_at="2026-09-16T04:45:00+07:00")

    assert result["report_slot_id"] == "2026-09-16T04:30+07:00|DEEP"
    assert result["catch_up_deadline"] == DEADLINE
    assert result["catch_up_window_open"] is True
    assert result["catch_up_required"] is True
    assert result["start_build"] is True
    assert result["next_action"] == "CATCH_UP_BUILD"
    assert result["legacy_fallback_allowed"] is False
    assert result["v6_data_plane_mutation_allowed"] is False


def test_delayed_report_after_catch_up_deadline_is_noop():
    result = _plan(observed_at="2026-09-16T05:00:01+07:00")

    assert result["report_slot_id"] == "2026-09-16T04:30+07:00|DEEP"
    assert result["catch_up_deadline"] == DEADLINE
    assert result["catch_up_window_open"] is False
    assert result["catch_up_required"] is False
    assert result["start_build"] is False
    assert result["next_action"] == "CATCH_UP_WINDOW_EXPIRED"
    assert result["report_delivered"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["v6_data_plane_mutation_allowed"] is False


def test_catch_up_deadline_must_not_precede_logical_slot():
    with pytest.raises(DeliveryIntegrityError):
        _plan(
            observed_at="2026-09-16T04:45:00+07:00",
            deadline="2026-09-16T04:29:59+07:00",
        )


def test_catch_up_deadline_must_be_timezone_aware():
    with pytest.raises(DeliveryIntegrityError):
        _plan(
            observed_at="2026-09-16T04:45:00+07:00",
            deadline="2026-09-16T05:00:00",
        )
