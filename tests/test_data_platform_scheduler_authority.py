from __future__ import annotations

import json
import re
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
V6_WORKFLOW_GLOB = "v6-*.yml"
SCHEDULE_KEY = re.compile(r"(?m)^\s*schedule\s*:")
ALLOWED_MONITORING_SCHEDULES = {"v6-scheduler-watchdog.yml"}


def test_v6_github_schedule_is_monitor_only_and_never_acquisition_authority() -> None:
    """Only the named read-only watchdog may use cron; V6 acquisition remains ChatGPT-owned."""
    workflows = sorted(WORKFLOW_DIR.glob(V6_WORKFLOW_GLOB))
    assert workflows, "expected at least one V6 workflow"

    scheduled: set[str] = set()
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if SCHEDULE_KEY.search(text):
            scheduled.add(workflow.name)

    assert scheduled == ALLOWED_MONITORING_SCHEDULES, (
        "scheduled V6 workflow set must be exactly the monitoring-only watchdog; got "
        + repr(sorted(scheduled))
    )

    watchdog_path = WORKFLOW_DIR / "v6-scheduler-watchdog.yml"
    watchdog = watchdog_path.read_text(encoding="utf-8")
    watchdog_config = json.loads(Path("config/v6/scheduler_watchdog.json").read_text(encoding="utf-8"))
    schedule_policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))

    assert "cron: '50 * * * *'" in watchdog
    assert "contents: read" in watchdog
    assert "actions: read" in watchdog
    assert "issues: write" in watchdog
    assert "contents: write" not in watchdog
    assert "v6-runtime-publisher" not in watchdog
    assert "RECOVER_V6" not in watchdog
    assert "/v6-master-acquire" not in watchdog
    assert "actions/workflows/v6-natural-data-ingestion.yml/dispatches" not in watchdog

    authority = watchdog_config["authority"]
    assert watchdog_config["role"] == "MONITORING_ONLY"
    assert authority["core_scheduler"] == "CHATGPT_FPL_MASTER_MONITOR"
    assert authority["watchdog_is_scheduler_authority"] is False
    assert authority["watchdog_may_trigger_acquisition"] is False
    assert authority["watchdog_may_dispatch_ingestion"] is False
    assert authority["watchdog_may_publish_runtime"] is False
    assert authority["watchdog_may_advance_scheduler_proof"] is False
    assert authority["watchdog_may_use_v6_publisher_credentials"] is False

    assert schedule_policy["github_natural_schedule"]["enabled"] is False
    assert schedule_policy["governance"]["chatgpt_scheduler_is_only_hourly_authority"] is True


def test_v6_ingestion_uses_single_hourly_master_transport() -> None:
    """Core V6 acquisition is Issue #431 title-driven; report prefetch is comment-driven."""
    workflow = WORKFLOW_DIR / "v6-natural-data-ingestion.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "issue_comment:" in text
    assert "types: [created]" in text
    assert "issues:" in text
    assert "types: [edited]" in text
    assert "workflow_dispatch:" in text
    assert not SCHEDULE_KEY.search(text)
    assert "/v6-master-acquire" not in text
    assert "/v6-report-prefetch" in text
    assert "FPL_MASTER_SLOT" in text
    assert "FPL_REPORT_PREFETCH " not in text
    assert "github.event.issue.number == 431" in text
    assert "authorize-issue-edit" in text
    assert "python -m src.runtime_v6.workflow_control slot-guard" in text
    validator = Path("src/runtime_v6/production_validate.py").read_text(encoding="utf-8")
    assert "single_logical_acquisition_per_scheduler_slot" in validator
