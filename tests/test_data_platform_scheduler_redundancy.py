from __future__ import annotations

import re
from pathlib import Path

from src.runtime_v6.runtime_control import scheduled_slot_already_completed
from src.runtime_v6.workflow_control import classify_invocation, load_policy, scheduled_cron_kinds


def _policy() -> dict:
    return load_policy(Path("config/v6/schedule_policy.json"))


def test_github_natural_cron_is_disabled_and_former_redundant_crons_are_history_only():
    policy = _policy()
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    clock = Path(".github/workflows/fpl-github-clock.yml").read_text(encoding="utf-8")
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)
    clock_crons = re.findall(r'^\s+- cron: "([^"]+)"$', clock, flags=re.MULTILINE)

    assert policy["scheduled_crons_utc"] == []
    assert policy["natural_schedule_redundancy_attempts_per_hour"] == 0
    assert policy["github_natural_schedule"]["enabled"] is False
    assert policy["github_natural_schedule"]["authority"] == "NONE"
    assert policy["github_natural_schedule"]["workflow"] == "fpl-github-clock.yml"
    assert policy["github_natural_schedule"]["workflow_schedule_triggers_removed"] is True
    assert workflow_crons == []
    assert clock_crons == []
    assert policy["github_natural_schedule"]["former_crons_utc"] == [
        "13 * * * *",
        "28 * * * *",
        "43 * * * *",
        "58 * * * *",
    ]
    assert policy["github_natural_schedule"]["former_crons_are_historical_evidence_only"] is True
    assert policy["governance"]["github_schedule_events_are_removed"] is True

def test_scheduler_migration_boundary_is_explicit():
    policy = _policy()
    scheduler = policy["scheduler_authority"]
    github = policy["github_natural_schedule"]
    assert scheduler["migration_started_at"] == "2026-10-06T11:30:00+07:00"
    assert github["enabled_at"] == scheduler["migration_started_at"]
    assert policy["governance"]["scheduler_migration_boundary_is_explicit"] is True


def test_disabled_github_cron_classifier_fails_closed():
    policy = _policy()
    assert scheduled_cron_kinds(policy) == {}
    assert classify_invocation(
        policy,
        event_name="schedule",
        event={"schedule": "28 * * * *"},
    ) == "schedule_disabled"

def test_disabled_github_schedule_arrival_is_noop_defense_in_depth():
    for minute in (13, 28, 43, 58):
        assert scheduled_slot_already_completed(
            {},
            scheduler_interval_minutes=60,
            event_name="schedule",
            schedule_kind="schedule_disabled",
            schedule_expression=f"{minute} * * * *",
        ) is True


def test_legacy_master_issue_comment_is_no_longer_a_scheduler_ingress():
    policy = _policy()
    event = {
        "comment": {
            "body": "/v6-master-acquire reason=chatgpt_hourly_master logical_slot=2026-09-08T10:00:00+07:00 audit=FPL_MASTER_HOURLY"
        }
    }
    assert classify_invocation(policy, event_name="issue_comment", event=event) == "governed_issue_command_unknown"
    assert policy["scheduler_authority"]["legacy_issue_comment_transport_enabled"] is False
    assert policy["scheduler_authority"]["issue_comment_command"] == ""
    assert "issue_comment:chatgpt_scheduler" not in policy["governance"]["scheduler_health_proof_triggers"]
    assert policy["governance"]["scheduler_health_proof_trigger"] == "issues:FPL_MASTER_SLOT"

def test_chatgpt_issue_title_edit_is_the_scheduler_classifier():
    policy = _policy()
    event = {
        "issue": {
            "title": (
                "FPL_MASTER_SLOT reason=chatgpt_hourly_master "
                "logical_slot=2026-09-08T10:00:00+07:00 "
                "audit=FPL_MASTER_HOURLY observed_at=2026-09-08T10:31:00+07:00"
            )
        }
    }
    assert classify_invocation(policy, event_name="issues", event=event) == "chatgpt_scheduler"
    assert policy["scheduler_authority"]["preferred_transport"] == "ISSUE_TITLE_EDIT"
    assert policy["governance"]["preferred_scheduler_health_proof_trigger"] == "issues:FPL_MASTER_SLOT"
    assert policy["governance"]["issue_title_edit_is_preferred_scheduler_transport"] is True
    assert policy["scheduler_authority"]["issue_title_marker"] == "FPL_MASTER_SLOT"

def test_dedicated_master_comment_transport_is_retired():
    policy = _policy()
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    scheduler = policy["scheduler_authority"]
    assert scheduler["preferred_transport"] == "ISSUE_TITLE_EDIT"
    assert scheduler["dedicated_control_comment_id"] == 5596106114
    assert scheduler["dedicated_control_comment_event"] == "RETIRED"
    assert policy["governance"]["issue_comment_edit_is_preferred_scheduler_transport"] is False
    assert "types: [created]" in workflow
    assert "github.event.comment.id == 5596106114" not in workflow
    assert "/v6-master-acquire" not in workflow

def test_chatgpt_scheduler_contract_is_single_hourly_authority():
    policy = _policy()
    scheduler = policy["scheduler_authority"]
    assert scheduler["name"] == "FPL Master Monitor V12"
    assert scheduler["timezone"] == "Asia/Jakarta"
    assert scheduler["cadence_minutes"] == 60
    assert scheduler["physical_minute"] == 30
    assert scheduler["logical_slot_minute"] == 0
    assert scheduler["required_reason"] == "chatgpt_hourly_master"
    assert scheduler["required_audit"] == "FPL_MASTER_HOURLY"
    assert scheduler["health_epoch"] == "CHATGPT_SCHEDULER_V12_RESTORED_20261007"
    assert scheduler["green_after_consecutive_slots"] == 3

def test_workflow_hydration_is_fail_closed_and_fulfillment_is_explicit():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert "refusing empty-tree acquisition" in workflow
    assert "starting clean" not in workflow
    assert "orchestration-fulfillment:" in workflow
    assert "DATA_SLOT_ALREADY_PUBLISHED_REPORT_CONTINUES" in workflow
    assert "IDEMPOTENT_NOOP_ALREADY_PUBLISHED" not in workflow
    assert "continue_report_pipeline=$CONTINUE_REPORT_PIPELINE" in workflow
    assert "SNAPSHOT_PUBLISHED_VALIDATED" in workflow
    assert "ACQUISITION_COMPLETE_PUBLICATION_NOT_VALIDATED" in workflow


def test_only_ingestion_and_watchdog_are_scheduled_and_recovery_is_manual_only():
    workflows = Path(".github/workflows")
    scheduled_v6 = {
        path.name
        for path in workflows.glob("v6-*.yml")
        if re.search(r"(?m)^\s*schedule\s*:", path.read_text(encoding="utf-8"))
    }
    assert scheduled_v6 == {"v6-scheduler-watchdog.yml"}
    clock = (workflows / "fpl-github-clock.yml").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*schedule\s*:", clock)
    recovery = (workflows / "v6-core-recovery-guard.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in recovery
    assert "schedule:" not in recovery
    assert "workflow_run:" not in recovery

def test_private_repository_runtime_hydration_uses_explicit_read_auth():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert "V6_RUNTIME_READ_TOKEN: ${{ github.token }}" in workflow
    assert "AUTHORIZATION: basic $read_auth" in workflow
    assert workflow.count("AUTHORIZATION: basic $read_auth") >= 3
    assert "persist-credentials: false" in workflow


def test_non_v6_issue_comments_cannot_replace_pending_governed_prefetch():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert "fpl-v6-noncommand-{0}" in workflow
    assert "!startsWith(github.event.comment.body, '/v6-report-prefetch')" in workflow
    assert "!startsWith(github.event.comment.body, '/v6-manual-recovery')" in workflow
    assert "'fpl-v6-hourly-data-ingestion'" in workflow
    assert "cancel-in-progress: false" in workflow
