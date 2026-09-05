from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.runtime_control import (
    build_runtime_control,
    nominal_schedule_time,
    scheduled_invocation_slot,
    scheduled_slot_already_completed,
)


def test_delayed_recovery_crossing_hour_belongs_to_previous_nominal_slot():
    now = datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc)

    assert nominal_schedule_time(now, "53 * * * *") == datetime(
        2026, 9, 5, 12, 53, tzinfo=timezone.utc
    )
    assert scheduled_invocation_slot(now, 60, "53 * * * *") == datetime(
        2026, 9, 5, 12, 0, tzinfo=timezone.utc
    )

    control = build_runtime_control(
        {"runtime_control": {"last_scheduled_cycle_at": "2026-09-05T11:00:00+00:00"}},
        scheduler_interval_minutes=60,
        now=now,
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="53 * * * *",
    )

    assert control["health"] == "GREEN"
    assert control["missed_cycle_count"] == 0
    assert control["expected_cycle_at"] == "2026-09-05T12:00:00+00:00"
    assert control["nominal_schedule_at"] == "2026-09-05T12:53:00+00:00"
    assert control["schedule_lag_seconds"] == 600.0
    assert control["scheduled_slot_uses_nominal_cron"] is True


def test_delayed_primary_is_not_skipped_after_previous_hour_recovery():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-05T12:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-05T12:00:00+00:00",
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 5, 13, 54, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="primary",
        schedule_expression="23 * * * *",
    ) is False


def test_delayed_recovery_is_skipped_when_same_hour_primary_is_already_authoritative():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-05T13:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-05T13:00:00+00:00",
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 5, 13, 58, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="53 * * * *",
    ) is True


def test_older_delayed_recovery_never_regresses_newer_authoritative_slot():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-05T13:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-05T13:00:00+00:00",
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="53 * * * *",
    ) is True


def test_unsupported_cron_fails_safe_to_wall_clock_slot():
    now = datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc)

    assert nominal_schedule_time(now, "*/15 * * * *") is None
    assert scheduled_invocation_slot(now, 60, "*/15 * * * *") == datetime(
        2026, 9, 5, 13, 0, tzinfo=timezone.utc
    )
