from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.polling import poll_decision
from src.runtime_v6.runtime_control import (
    apply_runtime_control,
    build_operational_slots,
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
    assert updated["overall"] == "GREEN"
    assert updated["data_availability_health"] == "GREEN"
    assert updated["runtime_control_health"] == "RED"
    assert updated["control_failures"] == ["MISSED_SCHEDULED_CYCLE"]
    assert updated["paths"]["runtime_control"] == "data/v6/health/runtime_control.json"
    assert updated["governance"]["production_ingestion_schedule_only"] is True
    assert updated["governance"]["production_authoritative_snapshots_require_schedule"] is False
    assert updated["governance"]["production_authoritative_snapshots_require_governed_trigger"] is True
    assert updated["governance"]["scheduled_recovery_is_idempotent"] is True


def test_master_orchestrated_is_authoritative_without_masking_natural_schedule():
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
        now=datetime(2026, 9, 4, 8, 31, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        schedule_kind="master_orchestrated",
    )

    assert control["health"] == "GREEN"
    assert control["scheduled_cycle"] is False
    assert control["master_orchestrated"] is True
    assert control["manual_recovery"] is False
    assert control["authoritative_runtime_snapshot"] is True
    assert control["counts_as_completed_operational_slot"] is True
    assert control["counts_as_completed_scheduled_slot"] is False
    assert control["last_scheduled_cycle_at"] == "2026-09-04T06:00:00+00:00"
    assert control["last_authoritative_cycle_at"] == "2026-09-04T08:00:00+00:00"
    assert updated["overall"] == "GREEN"
    assert updated["control_failures"] == []
    assert updated["governance"]["master_orchestrated_is_authoritative"] is True
    assert updated["governance"]["manual_recovery_is_authoritative"] is False


def test_issue_comment_master_orchestration_is_authoritative():
    manifest = {
        "overall": "GREEN",
        "polling": {"scheduler_interval_minutes": 60},
        "paths": {},
        "governance": {},
    }
    updated, control = apply_runtime_control(
        manifest,
        {},
        now=datetime(2026, 9, 4, 9, 31, tzinfo=timezone.utc),
        event_name="issue_comment",
        schedule_kind="master_orchestrated",
    )

    assert control["health"] == "GREEN"
    assert control["master_orchestrated"] is True
    assert control["scheduled_cycle"] is False
    assert control["authoritative_runtime_snapshot"] is True
    assert updated["control_failures"] == []


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
    assert updated["overall"] == "GREEN"
    assert updated["data_availability_health"] == "GREEN"
    assert updated["runtime_control_health"] == "AMBER"
    assert updated["control_failures"] == ["NON_AUTHORITATIVE_MANUAL_RECOVERY"]
    assert updated["governance"]["production_ingestion_schedule_only"] is False
    assert updated["governance"]["production_authoritative_snapshots_require_schedule"] is False
    assert updated["governance"]["governed_manual_recovery_enabled"] is True
    assert updated["governance"]["manual_recovery_is_authoritative"] is False


def test_production_workflow_has_off_minute_schedule_and_governed_manual_recovery():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)

    assert workflow_crons == [policy["primary_cron_utc"], policy["recovery_cron_utc"]]
    cron_minutes = [int(cron.split()[0]) for cron in workflow_crons]
    assert len(cron_minutes) == 2
    assert all(10 <= minute <= 59 for minute in cron_minutes)
    assert (cron_minutes[1] - cron_minutes[0]) % 60 == 30
    assert policy["governance"]["avoid_top_of_hour_scheduler_load"] is True
    assert "workflow_dispatch:" in workflow
    assert "issue_comment:" in workflow
    assert "V6 Master Orchestrator Trigger" not in workflow
    assert "github.event.issue.number == 431" in workflow
    assert "/v6-master-acquire" in workflow
    assert "python -m src.runtime_v6.workflow_control authorize-dispatch" in workflow
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


def test_operational_slot_ledger_separates_natural_fulfillment_from_master_reliance():
    ledger = {}
    controls = [
        build_runtime_control({}, now=datetime(2026, 9, 7, hour, 23, tzinfo=timezone.utc), event_name="schedule", run_id=str(hour), schedule_kind="primary", schedule_expression="23 * * * *")
        for hour in range(0, 5)
    ]
    controls.append(
        build_runtime_control({}, now=datetime(2026, 9, 7, 5, 7, tzinfo=timezone.utc), event_name="issue_comment", run_id="master", schedule_kind="master_orchestrated")
    )
    for control in controls:
        ledger = build_operational_slots(ledger, control, window_size=48)

    summary = ledger["summary"]
    assert summary["tracked_operational_slots"] == 6
    assert summary["fulfilled_by_primary"] == 5
    assert summary["fulfilled_by_recovery"] == 0
    assert summary["fulfilled_by_master"] == 1
    assert summary["natural_fulfillment_ratio"] == 0.8333
    assert summary["master_reliance_ratio"] == 0.1667
    assert summary["health"] == "AMBER"
    assert summary["data_availability_health_is_separate"] is True
    assert summary["post_fulfillment_skipped_cron_arrivals_observable"] is False


def test_report_prefetch_never_creates_operational_slot_ledger_entry():
    control = build_runtime_control(
        {},
        now=datetime(2026, 9, 7, 12, 30, tzinfo=timezone.utc),
        event_name="issue_comment",
        run_id="prefetch",
        schedule_kind="report_prefetch",
    )
    ledger = build_operational_slots({}, control)
    assert ledger["slots"] == []
    assert ledger["summary"]["tracked_operational_slots"] == 0
    assert ledger["summary"]["maturity"] == "WARMING_UP"


def test_operational_slot_ledger_is_bounded_to_48_slots():
    ledger = {}
    for hour in range(60):
        day = 1 + hour // 24
        clock = hour % 24
        control = build_runtime_control(
            {},
            now=datetime(2026, 9, day, clock, 23, tzinfo=timezone.utc),
            event_name="schedule",
            run_id=str(hour),
            schedule_kind="primary",
            schedule_expression="23 * * * *",
        )
        ledger = build_operational_slots(ledger, control, window_size=48)
    assert len(ledger["slots"]) == 48
    assert ledger["summary"]["tracked_operational_slots"] == 48
    assert ledger["summary"]["health"] == "GREEN"
