from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.runtime_control import (
    build_runtime_control,
    nominal_schedule_time,
    scheduled_invocation_slot,
    scheduled_slot_already_completed,
)


def test_delayed_natural_cron_resolves_nominal_slot_and_remains_authoritative():
    now = datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc)

    assert nominal_schedule_time(now, "30 * * * *") == datetime(
        2026, 9, 5, 12, 30, tzinfo=timezone.utc
    )
    assert scheduled_invocation_slot(now, 60, "30 * * * *") == datetime(
        2026, 9, 5, 12, 0, tzinfo=timezone.utc
    )

    control = build_runtime_control(
        {"runtime_control": {"last_operational_cycle_at": "2026-09-05T11:00:00+00:00"}},
        scheduler_interval_minutes=60,
        now=now,
        event_name="schedule",
        schedule_kind="chatgpt_scheduler",
        schedule_expression="30 * * * *",
    )

    assert control["health"] == "GREEN"
    assert control["github_schedule_event"] is True
    assert control["chatgpt_scheduler"] is True
    assert control["authoritative_runtime_snapshot"] is True
    assert control["counts_as_completed_operational_slot"] is True
    assert control["counts_as_completed_scheduled_slot"] is True
    assert control["expected_cycle_at"] == "2026-09-05T12:00:00+00:00"
    assert control["nominal_schedule_at"] == "2026-09-05T12:30:00+00:00"
    assert control["scheduled_slot_uses_nominal_cron"] is True

def test_schedule_disabled_event_is_always_noop_even_without_prior_slot():
    assert scheduled_slot_already_completed(
        {},
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 5, 13, 13, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="schedule_disabled",
        schedule_expression="13 * * * *",
    ) is True


def test_schedule_disabled_event_is_noop_with_prior_operational_slot():
    previous = {
        "runtime_control": {
            "last_operational_cycle_at": "2026-09-05T12:00:00+00:00",
            "last_chatgpt_scheduler_cycle_at": "2026-09-05T12:00:00+00:00",
        }
    }
    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 5, 13, 58, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="schedule_disabled",
        schedule_expression="58 * * * *",
    ) is True


def test_unsupported_cron_helper_fails_safe_to_wall_clock_slot():
    now = datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc)
    assert nominal_schedule_time(now, "*/15 * * * *") is None
    assert scheduled_invocation_slot(now, 60, "*/15 * * * *") == datetime(
        2026, 9, 5, 13, 0, tzinfo=timezone.utc
    )
