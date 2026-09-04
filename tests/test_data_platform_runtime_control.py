from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.polling import poll_decision
from src.runtime_v6.runtime_control import apply_runtime_control, build_runtime_control


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
    )

    assert control["health"] == "RED"
    assert control["missed_cycle"] is True
    assert control["missed_cycle_count"] == 1
    assert control["expected_cycle_at"] == "2026-09-04T08:00:00+00:00"
    assert control["last_scheduled_cycle_at"] == "2026-09-04T08:00:00+00:00"


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
    )

    assert control["scheduled_cycle"] is False
    assert control["last_scheduled_cycle_at"] == "2026-09-04T06:00:00+00:00"
    assert control["missed_cycle"] is False


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
    )

    assert control["health"] == "RED"
    assert updated["overall"] == "RED"
    assert updated["control_failures"] == ["MISSED_SCHEDULED_CYCLE"]
    assert updated["paths"]["runtime_control"] == "data/v6/health/runtime_control.json"
    assert updated["governance"]["production_ingestion_schedule_only"] is True


def test_production_workflow_is_not_triggered_by_push_or_pull_request():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")

    assert 'cron: "0 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
    assert "python -m src.runtime_v6.collector" in workflow
    assert "python -m src.runtime_v6.runtime_control" in workflow


def test_v6_ci_never_acquires_or_writes_runtime_branch():
    workflow = Path(".github/workflows/v6-ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "python -m src.runtime_v6.collector" not in workflow
    assert "runtime-data-v6" not in workflow
    assert "git push" not in workflow
    assert "contents: read" in workflow
