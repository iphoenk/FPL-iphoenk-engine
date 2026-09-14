from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
V6_WORKFLOW_GLOB = "v6-*.yml"
SCHEDULE_KEY = re.compile(r"(?m)^\s*schedule\s*:")


def test_v6_workflows_have_no_github_schedule_trigger() -> None:
    """V6 scheduling authority belongs to ChatGPT FPL Master, never GitHub cron."""
    workflows = sorted(WORKFLOW_DIR.glob(V6_WORKFLOW_GLOB))
    assert workflows, "expected at least one V6 workflow"

    offenders: list[str] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if SCHEDULE_KEY.search(text):
            offenders.append(str(workflow))

    assert offenders == [], (
        "V6 GitHub workflows must remain executor-only; remove on.schedule/cron from: "
        + ", ".join(offenders)
    )


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
