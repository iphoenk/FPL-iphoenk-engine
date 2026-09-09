from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.polling import poll_decision
from src.runtime_v6.runtime_control import (
    CHATGPT_GREEN_STREAK,
    CHATGPT_SCHEDULER_AUTHORITY,
    apply_runtime_control,
    build_operational_slots,
    build_runtime_control,
    scheduled_slot_already_completed,
)


def test_same_scheduler_slot_never_polls_twice():
    now = datetime(2026, 9, 8, 3, 31, tzinfo=timezone.utc)
    source = {"id": "example", "requests": [{"id": "one"}]}
    previous = {"polling": {"last_polled_at": "2026-09-08T03:03:00+00:00"}}
    decision = poll_decision(source, previous, now=now, scheduler_interval_minutes=60)
    assert decision["due"] is False
    assert decision["reason"] == "ALREADY_POLLED_THIS_SLOT"
    assert decision["scheduler_slot"] == "2026-09-08T03:00:00+00:00"


def test_new_scheduler_slot_is_due_after_previous_hour():
    now = datetime(2026, 9, 8, 4, 31, tzinfo=timezone.utc)
    source = {"id": "example", "poll_interval_minutes": 60, "requests": [{"id": "one"}]}
    previous = {"polling": {"last_polled_at": "2026-09-08T03:31:00+00:00"}}
    decision = poll_decision(source, previous, now=now, scheduler_interval_minutes=60)
    assert decision["due"] is True
    assert decision["reason"] == "DUE"


def test_removed_github_schedule_is_always_skipped_defense_in_depth():
    assert scheduled_slot_already_completed(
        {},
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 8, 3, 13, tzinfo=timezone.utc),
        event_name="schedule",
        schedule_kind="schedule_disabled",
    ) is True


def test_chatgpt_scheduler_uses_explicit_jakarta_logical_slot():
    control = build_runtime_control(
        {},
        scheduler_interval_minutes=60,
        now=datetime(2026, 9, 8, 3, 31, 15, tzinfo=timezone.utc),
        event_name="issues",
        run_id="chatgpt-1",
        schedule_kind="chatgpt_scheduler",
        logical_slot="2026-09-08T10:00:00+07:00",
    )
    assert control["health"] == "GREEN"
    assert control["scheduler_authority"] == CHATGPT_SCHEDULER_AUTHORITY
    assert control["chatgpt_scheduler"] is True
    assert control["chatgpt_scheduler_proof"] is True
    assert control["scheduled_cycle"] is True
    assert control["github_schedule_event"] is False
    assert control["expected_cycle_at"] == "2026-09-08T03:00:00+00:00"
    assert control["last_chatgpt_scheduler_cycle_at"] == "2026-09-08T03:00:00+00:00"
    assert control["logical_slot_source"] == "CHATGPT_COMMAND"
    assert control["counts_as_completed_scheduled_slot"] is True
    assert control["counts_as_completed_operational_slot"] is True
    assert control["scheduled_slot_uses_nominal_cron"] is False


def test_first_chatgpt_proof_is_allowed_even_if_data_slot_was_already_fulfilled():
    previous = {
        "runtime_control": {
            "last_operational_cycle_at": "2026-09-08T03:00:00+00:00",
            "schedule_kind": "master_orchestrated",
        }
    }
    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        event_name="issues",
        schedule_kind="chatgpt_scheduler",
        logical_slot="2026-09-08T10:00:00+07:00",
    ) is False


def test_second_chatgpt_proof_same_slot_is_skipped():
    previous = {
        "runtime_control": {
            "last_chatgpt_scheduler_cycle_at": "2026-09-08T03:00:00+00:00",
            "last_operational_cycle_at": "2026-09-08T03:00:00+00:00",
            "schedule_kind": "chatgpt_scheduler",
        }
    }
    assert scheduled_slot_already_completed(
        previous,
        scheduler_interval_minutes=60,
        event_name="issues",
        schedule_kind="chatgpt_scheduler",
        logical_slot="2026-09-08T10:00:00+07:00",
    ) is True


def test_chatgpt_gap_is_runtime_control_failure():
    manifest = {"overall": "GREEN", "polling": {"scheduler_interval_minutes": 60}, "paths": {}, "governance": {}}
    previous = {"runtime_control": {"last_chatgpt_scheduler_cycle_at": "2026-09-08T01:00:00+00:00"}}
    updated, control = apply_runtime_control(
        manifest,
        previous,
        now=datetime(2026, 9, 8, 3, 31, tzinfo=timezone.utc),
        event_name="issues",
        schedule_kind="chatgpt_scheduler",
        logical_slot="2026-09-08T10:00:00+07:00",
    )
    assert control["health"] == "RED"
    assert control["missed_cycle"] is True
    assert control["missed_cycle_count"] == 1
    assert updated["overall"] == "GREEN"
    assert updated["data_availability_health"] == "GREEN"
    assert updated["runtime_control_health"] == "RED"
    assert updated["control_failures"] == ["MISSED_CHATGPT_SCHEDULER_SLOT"]
    assert updated["governance"]["chatgpt_scheduler_is_authority"] is True
    assert updated["governance"]["github_natural_scheduler_is_authority"] is False


def test_generic_master_dispatch_is_authoritative_but_not_scheduler_proof():
    manifest = {"overall": "GREEN", "polling": {"scheduler_interval_minutes": 60}, "paths": {}, "governance": {}}
    updated, control = apply_runtime_control(
        manifest,
        {},
        now=datetime(2026, 9, 8, 3, 20, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        schedule_kind="master_orchestrated",
    )
    assert control["health"] == "GREEN"
    assert control["master_orchestrated"] is True
    assert control["chatgpt_scheduler"] is False
    assert control["scheduled_cycle"] is False
    assert control["authoritative_runtime_snapshot"] is True
    assert control["counts_as_completed_operational_slot"] is True
    assert control["counts_as_completed_scheduled_slot"] is False
    assert updated["governance"]["generic_master_dispatch_does_not_count_as_scheduler_health_proof"] is True


def test_manual_recovery_is_non_authoritative():
    manifest = {"overall": "GREEN", "polling": {"scheduler_interval_minutes": 60}, "paths": {}, "governance": {}}
    updated, control = apply_runtime_control(
        manifest,
        {},
        now=datetime(2026, 9, 8, 3, 20, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        schedule_kind="manual_recovery",
    )
    assert control["health"] == "AMBER"
    assert control["manual_recovery"] is True
    assert control["authoritative_runtime_snapshot"] is False
    assert updated["control_failures"] == ["NON_AUTHORITATIVE_MANUAL_RECOVERY"]


def test_production_policy_uses_chatgpt_and_removed_github_crons():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)
    assert policy["scheduler_authority"]["kind"] == "CHATGPT_TASK"
    assert policy["scheduler_authority"]["name"] == "FPL Master Monitor"
    assert policy["scheduler_authority"]["physical_minute"] == 31
    assert policy["scheduler_authority"]["logical_slot_minute"] == 0
    assert policy["github_natural_schedule"]["enabled"] is False
    assert policy["github_natural_schedule"]["authority"] == "NONE"
    assert policy["github_natural_schedule"]["workflow_schedule_triggers_removed"] is True
    assert policy["scheduled_crons_utc"] == []
    assert policy["natural_schedule_redundancy_attempts_per_hour"] == 0
    assert workflow_crons == []
    assert policy["github_natural_schedule"]["former_crons_are_historical_evidence_only"] is True
    assert policy["governance"]["github_schedule_events_are_removed"] is True
    assert policy["governance"]["scheduler_migration_boundary_is_explicit"] is True
    assert policy["governance"]["chatgpt_scheduler_is_only_hourly_authority"] is True
    assert policy["governance"]["scheduler_health_proof_trigger"] == "issue_comment:chatgpt_scheduler"
    assert "workflow_dispatch:" in workflow
    assert "issue_comment:" in workflow
    assert "types: [created, edited]" in workflow
    assert "github.event.comment.id == 5596106114" in workflow
    assert "issues:" in workflow
    assert "github.event.issue.number == 431" in workflow
    assert "/v6-master-acquire" in workflow
    assert "FPL_MASTER_SLOT" in workflow
    assert "python -m src.runtime_v6.workflow_control authorize-issue" in workflow
    assert "python -m src.runtime_v6.workflow_control authorize-issue-edit" in workflow
    assert "python -m src.runtime_v6.collector" in workflow
    assert "python -m src.runtime_v6.runtime_control" in workflow
    assert "python -m src.runtime_v6.workflow_control slot-guard" in workflow
    assert "python -m src.runtime_v6.production_validate preflight" in workflow
    assert "python -m src.runtime_v6.production_validate publishable" in workflow
    assert "  schedule:" not in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow


def _chatgpt_control(hour: int, run_id: str | None = None):
    return build_runtime_control(
        {},
        now=datetime(2026, 9, 8, hour, 31, tzinfo=timezone.utc),
        event_name="issues",
        run_id=run_id or str(hour),
        schedule_kind="chatgpt_scheduler",
        logical_slot=f"2026-09-08T{hour + 7:02d}:00:00+07:00",
    )


def test_ledger_migrates_old_github_history_out_of_current_health():
    legacy = {
        "schema_version": 2,
        "slots": [
            {"slot": "2026-09-08T00:00:00+00:00", "fulfilled_by": "RECOVERY", "fulfilled": True},
            {"slot": "2026-09-08T01:00:00+00:00", "fulfilled_by": "MISSING", "fulfilled": False},
        ],
    }
    ledger = build_operational_slots(legacy, _chatgpt_control(3, "first"))
    assert ledger["schema_version"] == 3
    assert len(ledger["legacy_slots"]) == 2
    assert ledger["legacy_summary"]["health_authority"] == "HISTORICAL_ONLY"
    assert ledger["summary"]["tracked_operational_slots"] == 1
    assert ledger["summary"]["fulfilled_by_chatgpt"] == 1
    assert ledger["summary"]["health"] == "AMBER"
    assert ledger["summary"]["maturity"] == "WARMING_UP"
    assert ledger["summary"]["legacy_github_scheduler_excluded_from_current_health"] is True


def test_six_consecutive_chatgpt_slots_establish_green():
    ledger = {}
    for hour in range(0, CHATGPT_GREEN_STREAK):
        ledger = build_operational_slots(ledger, _chatgpt_control(hour), window_size=48)
    summary = ledger["summary"]
    assert summary["tracked_operational_slots"] == CHATGPT_GREEN_STREAK
    assert summary["fulfilled_by_chatgpt"] == CHATGPT_GREEN_STREAK
    assert summary["chatgpt_fulfillment_ratio"] == 1.0
    assert summary["consecutive_successful_slots"] == CHATGPT_GREEN_STREAK
    assert summary["health"] == "GREEN"
    assert summary["maturity"] == "ESTABLISHED"


def test_missing_chatgpt_slot_is_retrospectively_densified():
    ledger = build_operational_slots({}, _chatgpt_control(0), window_size=48)
    ledger = build_operational_slots(ledger, _chatgpt_control(2), window_size=48)
    assert [row["fulfilled_by"] for row in ledger["slots"]] == ["CHATGPT", "MISSING", "CHATGPT"]
    assert ledger["summary"]["missing_operational_slots"] == 1
    assert ledger["summary"]["chatgpt_fulfillment_ratio"] == 0.6667
    assert ledger["summary"]["health"] == "AMBER"


def test_generic_master_goes_to_auxiliary_and_does_not_green_scheduler():
    ledger = {}
    control = build_runtime_control(
        {},
        now=datetime(2026, 9, 8, 3, 15, tzinfo=timezone.utc),
        event_name="workflow_dispatch",
        run_id="manual-master",
        schedule_kind="master_orchestrated",
    )
    ledger = build_operational_slots(ledger, control)
    assert ledger["slots"] == []
    assert len(ledger["auxiliary_operational_slots"]) == 1
    assert ledger["summary"]["tracked_operational_slots"] == 0
    assert ledger["summary"]["health"] == "AMBER"


def test_report_prefetch_never_creates_scheduler_slot():
    control = build_runtime_control(
        {},
        now=datetime(2026, 9, 8, 3, 30, tzinfo=timezone.utc),
        event_name="issue_comment",
        run_id="prefetch",
        schedule_kind="report_prefetch",
    )
    ledger = build_operational_slots({}, control)
    assert ledger["slots"] == []
    assert ledger["summary"]["tracked_operational_slots"] == 0


def test_chatgpt_ledger_is_bounded_to_48_slots():
    ledger = {}
    for index in range(60):
        day = 8 + index // 24
        hour = index % 24
        control = build_runtime_control(
            {},
            now=datetime(2026, 9, day, hour, 31, tzinfo=timezone.utc),
            event_name="issues",
            run_id=str(index),
            schedule_kind="chatgpt_scheduler",
            logical_slot=datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc).astimezone(timezone.utc).isoformat(),
        )
        ledger = build_operational_slots(ledger, control, window_size=48)
    assert len(ledger["slots"]) == 48
    assert ledger["summary"]["tracked_operational_slots"] == 48
    assert ledger["summary"]["health"] == "GREEN"


def test_v6_ci_never_acquires_or_writes_runtime_branch():
    workflow = Path(".github/workflows/v6-ci.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "python -m src.runtime_v6.collector" not in workflow
    assert "runtime-data-v6" not in workflow
    assert "git push" not in workflow
    assert "contents: read" in workflow
    assert "detect-v6-change:" in workflow
    assert "v6-governance-gate:" in workflow
    assert "Non-V6 PR: V6 governance gate satisfied without running V6 suite" in workflow



def test_operational_ledger_is_extracted_without_duplicate_implementation():
    runtime = Path("src/runtime_v6/runtime_control.py").read_text(encoding="utf-8")
    ledger = Path("src/runtime_v6/operational_ledger.py").read_text(encoding="utf-8")
    assert "from .operational_ledger import build_operational_slots" in runtime
    assert "def build_operational_slots(" not in runtime
    assert "def _densify_chatgpt_rows(" not in runtime
    assert "def build_operational_slots(" in ledger
    assert "scheduler_observability_only" in ledger
