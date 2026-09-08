from __future__ import annotations

import re
from pathlib import Path

from src.runtime_v6.runtime_control import scheduled_slot_already_completed
from src.runtime_v6.workflow_control import classify_invocation, load_policy, scheduled_cron_kinds


def _policy() -> dict:
    return load_policy(Path("config/v6/schedule_policy.json"))


def test_github_redundant_crons_are_removed_and_preserved_as_history_only():
    policy = _policy()
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)

    assert policy["scheduled_crons_utc"] == []
    assert policy["natural_schedule_redundancy_attempts_per_hour"] == 0
    assert policy["github_natural_schedule"]["enabled"] is False
    assert policy["github_natural_schedule"]["authority"] == "NONE"
    assert policy["github_natural_schedule"]["workflow_schedule_triggers_removed"] is True
    assert workflow_crons == []
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
    assert scheduler["migration_started_at"] == "2026-09-08T10:35:31+07:00"
    assert scheduler["legacy_history_before"] == scheduler["migration_started_at"]
    assert github["removed_at"] == scheduler["migration_started_at"]
    assert policy["governance"]["scheduler_migration_boundary_is_explicit"] is True


def test_scheduled_cron_classifier_exposes_no_active_github_schedule():
    policy = _policy()
    assert scheduled_cron_kinds(policy) == {}
    for cron in policy["github_natural_schedule"]["former_crons_utc"]:
        assert classify_invocation(policy, event_name="schedule", event={"schedule": cron}) == "schedule_disabled"
    assert classify_invocation(policy, event_name="schedule", event={"schedule": "7 * * * *"}) == "schedule_disabled"


def test_disabled_github_schedule_arrival_is_noop_defense_in_depth():
    for minute in (13, 28, 43, 58):
        assert scheduled_slot_already_completed(
            {},
            scheduler_interval_minutes=60,
            event_name="schedule",
            schedule_kind="schedule_disabled",
            schedule_expression=f"{minute} * * * *",
        ) is True


def test_chatgpt_issue_command_is_the_scheduler_classifier():
    policy = _policy()
    event = {
        "comment": {
            "body": "/v6-master-acquire reason=chatgpt_hourly_master logical_slot=2026-09-08T10:00:00+07:00 audit=FPL_MASTER_HOURLY"
        }
    }
    assert classify_invocation(policy, event_name="issue_comment", event=event) == "chatgpt_scheduler"
    assert policy["scheduler_authority"]["kind"] == "CHATGPT_TASK"
    assert policy["governance"]["scheduler_health_proof_trigger"] == "issue_comment:chatgpt_scheduler"


def test_chatgpt_scheduler_contract_is_single_hourly_authority():
    policy = _policy()
    scheduler = policy["scheduler_authority"]
    assert scheduler["name"] == "FPL Master Monitor"
    assert scheduler["timezone"] == "Asia/Jakarta"
    assert scheduler["cadence_minutes"] == 60
    assert scheduler["physical_minute"] == 31
    assert scheduler["logical_slot_minute"] == 0
    assert scheduler["required_reason"] == "chatgpt_hourly_master"
    assert scheduler["required_audit"] == "FPL_MASTER_HOURLY"
    assert scheduler["health_epoch"] == "CHATGPT_MASTER_V1"
    assert scheduler["green_after_consecutive_slots"] == 6


def test_workflow_hydration_is_fail_closed_and_fulfillment_is_explicit():
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    assert "refusing empty-tree acquisition" in workflow
    assert "starting clean" not in workflow
    assert "orchestration-fulfillment:" in workflow
    assert "IDEMPOTENT_NOOP_ALREADY_PUBLISHED" in workflow
    assert "SNAPSHOT_PUBLISHED_VALIDATED" in workflow
    assert "ACQUISITION_COMPLETE_PUBLICATION_NOT_VALIDATED" in workflow
