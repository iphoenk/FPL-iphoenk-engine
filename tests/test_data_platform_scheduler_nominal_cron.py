from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.runtime_control import (
    build_runtime_control,
    nominal_schedule_time,
    scheduled_invocation_slot,
    scheduled_slot_already_completed,
)


def test_legacy_delayed_cron_helper_still_resolves_nominal_slot_but_is_not_authority():
    now = datetime(2026, 9, 5, 13, 3, tzinfo=timezone.utc)

    assert nominal_schedule_time(now, "53 * * * *") == datetime(
        2026, 9, 5, 12, 53, tzinfo=timezone.utc
    )
    assert scheduled_invocation_slot(now, 60, "53 * * * *") == datetime(
        2026, 9, 5, 12, 0, tzinfo=timezone.utc
    )

    control = build_runtime_control(
        {"runtime_control": {"last_github_scheduled_cycle_at": "2026-09-05T11:00:00+00:00"}},
        scheduler_interval_minutes=60,
        now=now,
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="53 * * * *",
    )

    assert control["health"] == "AMBER"
    assert control["github_schedule_event"] is True
    assert control["chatgpt_scheduler"] is False
    assert control["authoritative_runtime_snapshot"] is False
    assert control["counts_as_completed_operational_slot"] is False
    assert control["counts_as_completed_scheduled_slot"] is False
    assert control["expected_cycle_at"] is None
    assert control["nominal_schedule_at"] == "2026-09-05T12:53:00+00:00"
    assert control["scheduled_slot_uses_nominal_cron"] is False


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
