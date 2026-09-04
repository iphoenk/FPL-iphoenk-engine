from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.polling import poll_decision
from src.runtime_v6.runtime_control import (
    apply_runtime_control,
    build_runtime_control,
    scheduled_slot_already_completed,
)


def test_same_scheduler_slot_never_polls_twice():
    now = datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc)
    source = {"id": "example", "requests": [{"id": "one"}]}
    previous = {
        "polling": {"last_polled_at": datetime(2026, 9, 4, 8, 5, tzinfo=timezone.utc).isoformat()}
    }

    decision = poll_decision(source, previous, now=now, scheduler_interval_minutes=60)

    assert decision["due"] is False
    assert decision["reason"] == "ALREADY_POLLED_THIS_SLOT"
    assert decision["scheduler_slot"] == "2026-09-04T08:00:00+00:00"


def test_new_scheduler_slot_is_due_even_after_runner_jitter():
    now = datetime(2026, 9, 4, 9, 2, tzinfo=timezone.utc)
    source = {"id": "example", "poll_interval_minutes": 60, "requests": [{"id": "one"}]}
    previous = {
        "polling": {"last_polled_at": datetime(2026, 9, 4, 8, 14, tzinfo=timezone.utc).isoformat()}
    }

    decision = poll_decision(source, previous, now=now, scheduler_interval_minutes=60)

    assert decision["due"] is True
    assert decision["reason"] == "DUE"


def test_runtime_control_detects_missed_scheduled_cycle():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T06:00:00+00:00"
        }
    }
    control = build_runtime_control(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 4, 8, 3, tzinfo=timezone.utc),
        event_name="schedule",
        run_id="123",
        schedule_kind="primary",
    )

    assert control["health"] == "RED"
    assert control["missed_cycle"] is True
    assert control["missed_cycle_count"] == 1
    assert control["expected_cycle_at"] == "2026-09-04T08:00:00+00:00"
    assert control["last_scheduled_cycle_at"] == "2026-09-04T08:00:00+00:00"
    assert control["schedule_kind"] == "primary"
    assert control["authoritative_runtime_snapshot"] is True
    assert control["manual_recovery"] is False


def test_manual_cycle_does_not_mask_missing_scheduled_baseline():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T06:00:00+00:00"
        }
    }
    control = build_runtime_control(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 4, 7, 30, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        schedule_kind="manual_recovery",
    )

    assert control["health"] == "AMBER"
    assert control["scheduled_cycle"] is False
    assert control["manual_recovery"] is True
    assert control["authoritative_runtime_snapshot"] is False
    assert control["counts_as_completed_scheduled_slot"] is False
    assert control["last_scheduled_cycle_at"] == "2026-09-04T06:00:00+00:00"
    assert control["missed_cycle"] is False


def test_recovery_schedule_skips_when_primary_already_published_same_slot():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T08:00:00+00:00"
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 4, 8, 35, tzinfo=timezone.utc),
        event_name="schedule",
    ) is True


def test_recovery_schedule_runs_when_current_slot_has_not_been_published():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T07:00:00+00:00"
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 4, 8, 35, tzinfo=timezone.utc),
        event_name="schedule",
    ) is False


def test_manual_refresh_never_counts_as_completed_scheduled_slot():
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T08:00:00+00:00"
        }
    }

    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
    ) is False


def test_runtime_control_escalates_manifest_overall_on_missed_cycle():
    manifest = {
        "overall": "GREEN",
        "polling": {"scheduler_interval_minutes": 60},
        "paths": {},
        "governance": {},
    }
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T06:00:00+00:00"
        }
    }

    updated, control = apply_runtime_control(
        manifest,
        previous,
        now=datetime(2026, 9, 4, 8, 4, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="primary",
    )

    assert control["health"] == "RED"
    assert updated["overall"] == "RED"
    assert updated["control_failures"] == ["MISSED_SCHEDULED_CYCLE"]
    assert updated["paths"]["runtime_control"] == "data/v6/health/runtime_control.json"
    assert updated["governance"]["production_ingestion_schedule_only"] is True
    assert updated["governance"]["production_authoritative_snapshots_require_schedule"] is True
    assert updated["governance"]["scheduled_recovery_is_idempotent"] is True


def test_manual_recovery_is_non_authoritative_and_manifested_amber():
    manifest = {
        "overall": "GREEN",
        "polling": {"scheduler_interval_minutes": 60},
        "paths": {},
        "governance": {},
    }
    previous = {
        "runtime_control": {
            "last_scheduled_cycle_at": "2026-09-04T06:00:00+00:00"
        }
    }

    updated, control = apply_runtime_control(
        manifest,
        previous,
        now=datetime(2026, 9, 4, 8, 20, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        schedule_kind="manual_recovery",
    )

    assert control["health"] == "AMBER"
    assert control["scheduled_cycle"] is False
    assert control["manual_recovery"] is True
    assert control["last_scheduled_cycle_at"] == "2026-09-04T06:00:00+00:00"
    assert updated["overall"] == "AMBER"
    assert updated["control_failures"] == ["NON_AUTHORITATIVE_MANUAL_RECOVERY"]
    assert updated["governance"]["production_ingestion_schedule_only"] is False
    assert updated["governance"]["production_authoritative_snapshots_require_schedule"] is True
    assert updated["governance"]["governed_manual_recovery_enabled"] is True
    assert updated["governance"]["manual_recovery_is_authoritative"] is False


def test_production_workflow_has_off_minute_schedule_and_governed_manual_recovery():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)

    assert workflow_crons == [policy["primary_cron_utc"], policy["recovery_cron_utc"]]
    cron_minutes = [int(cron.split()[0]) for cron in workflow_crons]
    assert len(cron_minutes) == 2
    assert all(10 <= minute <= 59 for minute in cron_minutes)
    assert (cron_minutes[1] - cron_minutes[0]) % 60 == 30
    assert policy["governance"]["avoid_top_of_hour_scheduler_load"] is True
    assert "workflow_dispatch:" in workflow
    assert "Authorize governed manual recovery" in workflow
    assert "RECOVER_V6" in workflow
    assert "schedule_policy.json" in workflow
    assert "manual_recovery" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
    assert "python -m src.runtime_v6.collector" in workflow
    assert "python -m src.runtime_v6.runtime_control" in workflow
    assert "scheduled_slot_already_completed" in workflow
    assert "steps.slot_guard.outputs.skip != 'true'" in workflow
    assert policy["manual_recovery"]["authoritative_runtime_snapshot"] is False
    assert policy["manual_recovery"]["counts_as_completed_scheduled_slot"] is False


def test_v6_ci_never_acquires_or_writes_runtime_branch():
    workflow = Path(".github/workflows/v6-ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "python -m src.runtime_v6.collector" not in workflow
    assert "runtime-data-v6" not in workflow
    assert "git push" not in workflow
    assert "contents: read" in workflow
