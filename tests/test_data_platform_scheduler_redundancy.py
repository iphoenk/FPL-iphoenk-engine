from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.runtime_control import build_runtime_control, scheduled_slot_already_completed
from src.runtime_v6.workflow_control import classify_invocation, load_policy, scheduled_cron_kinds


def _policy() -> dict:
    return load_policy(Path("config/v6/schedule_policy.json"))


def test_redundant_scheduler_workflow_exactly_matches_policy():
    policy = _policy()
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)
    expected = [str(entry["cron"]) for entry in policy["scheduled_crons_utc"]]

    assert workflow_crons == expected
    assert len(workflow_crons) == 4
    assert policy["natural_schedule_redundancy_attempts_per_hour"] == 4
    assert policy["governance"]["natural_scheduler_redundancy_enabled"] is True
    assert policy["governance"]["redundant_schedule_arrivals_share_one_logical_hourly_slot"] is True


def test_redundant_scheduler_attempts_are_evenly_spaced_and_off_top_of_hour():
    crons = list(scheduled_cron_kinds(_policy()))
    minutes = [int(cron.split()[0]) for cron in crons]

    assert minutes == [13, 28, 43, 58]
    assert all(10 <= minute <= 59 for minute in minutes)
    assert [b - a for a, b in zip(minutes, minutes[1:])] == [15, 15, 15]


def test_every_redundant_scheduler_expression_is_governed_and_classified():
    policy = _policy()
    scheduled = scheduled_cron_kinds(policy)

    assert scheduled == {
        "13 * * * *": "primary",
        "28 * * * *": "recovery",
        "43 * * * *": "recovery",
        "58 * * * *": "recovery",
    }
    for cron, expected_kind in scheduled.items():
        assert classify_invocation(policy, event_name="schedule", event={"schedule": cron}) == expected_kind
    assert classify_invocation(policy, event_name="schedule", event={"schedule": "7 * * * *"}) == "scheduled_unknown"


def test_delayed_recovery_uses_nominal_cron_hour_for_logical_slot():
    control = build_runtime_control(
        {},
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 8, 0, 4, tzinfo=timezone.utc),
        event_name="schedule",
        run_id="late-recovery",
        schedule_kind="recovery",
        schedule_expression="58 * * * *",
    )

    assert control["nominal_schedule_at"] == "2026-09-07T23:58:00+00:00"
    assert control["expected_cycle_at"] == "2026-09-07T23:00:00+00:00"
    assert control["scheduled_slot_uses_nominal_cron"] is True
    assert control["authoritative_runtime_snapshot"] is True


def test_redundant_arrival_is_noop_after_same_logical_slot_is_published():
    previous = {
        "runtime_control": {
            "last_operational_cycle_at": "2026-09-07T23:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-07T23:00:00+00:00",
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 8, 0, 4, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="58 * * * *",
    ) is True


def test_redundant_arrival_runs_when_nominal_logical_slot_is_missing():
    previous = {
        "runtime_control": {
            "last_operational_cycle_at": "2026-09-07T22:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-07T22:00:00+00:00",
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 8, 0, 4, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="recovery",
        schedule_expression="58 * * * *",
    ) is False
