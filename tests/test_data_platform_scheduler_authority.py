from __future__ import annotations

import json
import re
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
V6_WORKFLOW_GLOB = "v6-*.yml"
SCHEDULE_KEY = re.compile(r"(?m)^\s*schedule\s*:")
ALLOWED_CONTROL_SCHEDULES = {"v6-natural-data-ingestion.yml", "v6-scheduler-watchdog.yml"}


def test_v6_github_schedules_have_one_natural_authority_plus_monitoring_watchdog() -> None:
    """The ingestion cron is sole natural authority; watchdog is monitoring-only."""
    workflows = sorted(WORKFLOW_DIR.glob(V6_WORKFLOW_GLOB))
    assert workflows, "expected at least one V6 workflow"

    scheduled: set[str] = set()
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if SCHEDULE_KEY.search(text):
            scheduled.add(workflow.name)

    assert scheduled == ALLOWED_CONTROL_SCHEDULES, (
        "scheduled V6 workflow set must be ingestion plus monitoring watchdog; got "
        + repr(sorted(scheduled))
    )

    watchdog = (WORKFLOW_DIR / "v6-scheduler-watchdog.yml").read_text(encoding="utf-8")
    recovery = (WORKFLOW_DIR / "v6-core-recovery-guard.yml").read_text(encoding="utf-8")
    watchdog_config = json.loads(Path("config/v6/scheduler_watchdog.json").read_text(encoding="utf-8"))
    recovery_config = json.loads(Path("config/v6/scheduler_recovery.json").read_text(encoding="utf-8"))
    schedule_policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))

    assert "cron: '50 * * * *'" in watchdog
    assert "contents: read" in watchdog
    assert "actions: read" in watchdog
    assert "issues: write" in watchdog
    assert "contents: write" not in watchdog
    assert "RECOVER_V6" not in watchdog
    assert "actions/workflows/v6-natural-data-ingestion.yml/dispatches" not in watchdog
    assert "python -m src.runtime_v6.domains.control_plane.scheduler_watchdog" in watchdog

    watchdog_authority = watchdog_config["authority"]
    assert watchdog_config["role"] == "MONITORING_ONLY"
    assert watchdog_authority["core_scheduler"] == "GITHUB_FPL_MASTER_SCHEDULER"
    assert watchdog_authority["watchdog_is_scheduler_authority"] is False
    assert watchdog_authority["watchdog_may_trigger_acquisition"] is False
    assert watchdog_authority["watchdog_may_dispatch_ingestion"] is False
    assert watchdog_authority["watchdog_may_publish_runtime"] is False
    assert watchdog_authority["watchdog_may_advance_scheduler_proof"] is False

    assert "schedule:" not in recovery
    assert "cron:" not in recovery
    assert "workflow_dispatch:" in recovery
    assert "contents: read" in recovery
    assert "actions: write" in recovery
    assert "contents: write" not in recovery
    assert "issues: write" not in recovery
    assert "FPL_MASTER_SLOT" not in recovery
    assert "inputs[mode]=manual_recovery" in recovery
    assert "inputs[confirm]=RECOVER_V6" in recovery
    assert "python -m src.runtime_v6.domains.control_plane.scheduler_watchdog" in recovery
    assert "python -m src.runtime_v6.domains.control_plane.scheduler_recovery" in recovery
    assert recovery_config["role"] == "SAFE_RECOVERY_ONLY"
    assert recovery_config["normal_scheduler_authority"] == "GITHUB_FPL_MASTER_SCHEDULER"
    assert recovery_config["recovery_counts_as_scheduler_proof"] is False
    assert recovery_config["recovery_counts_as_natural_wave3_slot"] is False
    assert recovery_config["automatic_schedule_enabled"] is False
    assert recovery_config["invocation_mode"] == "WORKFLOW_DISPATCH_ONLY"
    assert recovery_config["recurring_automated_initiator"] is False

    assert schedule_policy["github_natural_schedule"]["enabled"] is True
    assert schedule_policy["github_control_schedules"]["natural_scheduler_workflow"] == "v6-natural-data-ingestion.yml"
    assert schedule_policy["github_control_schedules"]["recurring_recovery_guard_enabled"] is False
    assert schedule_policy["governance"]["chatgpt_scheduler_is_only_hourly_authority"] is False
    assert schedule_policy["manual_recovery"]["counts_as_completed_operational_slot"] is False
    assert schedule_policy["manual_recovery"]["counts_as_completed_scheduled_slot"] is False


def test_v6_ingestion_uses_single_hourly_github_natural_transport() -> None:
    """Normal core V6 acquisition is schedule-driven; issue transports remain compatibility/recovery only."""
    workflow = WORKFLOW_DIR / "v6-natural-data-ingestion.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "issue_comment:" in text
    assert "types: [created]" in text
    assert "issues:" in text
    assert "types: [edited]" in text
    assert "workflow_dispatch:" in text
    assert SCHEDULE_KEY.search(text)
    for cron in ("13 * * * *", "28 * * * *", "43 * * * *", "58 * * * *"):
        assert f'cron: "{cron}"' in text
    assert "/v6-master-acquire" not in text
    assert "/v6-report-prefetch" in text
    assert "/v6-manual-recovery" in text
    assert "FPL_MASTER_SLOT" in text
    assert "FPL_REPORT_PREFETCH " not in text
    assert "github.event.issue.number == 431" in text
    assert "authorize-issue-edit" in text
    assert "python -m src.runtime_v6.domains.control_plane.workflow_control slot-guard" in text
    validator = Path("src/runtime_v6/domains/publication/production_validate.py").read_text(encoding="utf-8")
    assert "single_logical_acquisition_per_scheduler_slot" in validator
