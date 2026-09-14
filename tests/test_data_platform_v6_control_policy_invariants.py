import json
from pathlib import Path

from src.runtime_v6.scheduler_watchdog import (
    DEFAULT_CRITICAL_MINUTES,
    DEFAULT_WARNING_MINUTES,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_POLICY = ROOT / "config" / "v6" / "schedule_policy.json"
WATCHDOG_POLICY = ROOT / "config" / "v6" / "scheduler_watchdog.json"
RECOVERY_POLICY = ROOT / "config" / "v6" / "scheduler_recovery.json"
WORKFLOW_ROOT = ROOT / ".github" / "workflows"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_scheduler_control_plane_policies_share_authority_and_control_issue():
    schedule = _load(SCHEDULE_POLICY)
    watchdog = _load(WATCHDOG_POLICY)
    recovery = _load(RECOVERY_POLICY)
    scheduler = schedule["scheduler_authority"]

    assert watchdog["authority"]["core_scheduler"] == scheduler["runtime_authority_id"]
    assert recovery["normal_scheduler_authority"] == scheduler["runtime_authority_id"]
    assert watchdog["incident"]["control_issue_number"] == scheduler["control_issue_number"]
    assert schedule["master_orchestrated"]["control_issue_number"] == scheduler["control_issue_number"]
    assert schedule["report_prefetch"]["control_issue_number"] == scheduler["control_issue_number"]


def test_scheduler_threshold_semantics_are_explicit_and_ordered():
    schedule = _load(SCHEDULE_POLICY)
    watchdog = _load(WATCHDOG_POLICY)
    scheduler = schedule["scheduler_authority"]
    watchdog_schedule = watchdog["schedule"]

    assert watchdog_schedule["proof_fresh_after_minutes"] == scheduler["proof_fresh_after_minutes"]
    assert watchdog_schedule["warning_after_minutes"] > watchdog_schedule["proof_fresh_after_minutes"]
    assert watchdog_schedule["critical_after_minutes"] == scheduler["proof_stale_after_minutes"]
    assert watchdog_schedule["critical_after_minutes"] > watchdog_schedule["warning_after_minutes"]
    assert DEFAULT_WARNING_MINUTES == float(watchdog_schedule["warning_after_minutes"])
    assert DEFAULT_CRITICAL_MINUTES == float(watchdog_schedule["critical_after_minutes"])

    workflow = (WORKFLOW_ROOT / "v6-scheduler-watchdog.yml").read_text(encoding="utf-8")
    assert f'--warning-minutes {watchdog_schedule["warning_after_minutes"]}' in workflow
    assert f'--critical-minutes {watchdog_schedule["critical_after_minutes"]}' in workflow


def test_control_issue_number_is_consistent_in_event_workflows():
    schedule = _load(SCHEDULE_POLICY)
    issue = schedule["scheduler_authority"]["control_issue_number"]

    ingestion = (WORKFLOW_ROOT / "v6-natural-data-ingestion.yml").read_text(encoding="utf-8")
    watchdog = (WORKFLOW_ROOT / "v6-scheduler-watchdog.yml").read_text(encoding="utf-8")
    wave3 = (WORKFLOW_ROOT / "v6-wave3-proof.yml").read_text(encoding="utf-8")

    assert f"github.event.issue.number == {issue}" in ingestion
    assert f"gh issue view {issue}" in watchdog
    assert f"github.event.issue.number == {issue}" in wave3


def test_recovery_contract_is_explicitly_non_authoritative():
    recovery = _load(RECOVERY_POLICY)
    schedule = _load(SCHEDULE_POLICY)

    assert recovery["recovery_counts_as_scheduler_proof"] is False
    assert recovery["recovery_counts_as_natural_wave3_slot"] is False
    assert recovery["recovery_counts_as_completed_scheduled_slot"] is False
    assert schedule["manual_recovery"]["counts_as_completed_operational_slot"] is False
    assert schedule["manual_recovery"]["counts_as_completed_scheduled_slot"] is False
