import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_POLICY = ROOT / "config" / "v6" / "schedule_policy.json"
WATCHDOG_POLICY = ROOT / "config" / "v6" / "scheduler_watchdog.json"
RECOVERY_POLICY = ROOT / "config" / "v6" / "scheduler_recovery.json"


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


def test_recovery_contract_is_explicitly_non_authoritative():
    recovery = _load(RECOVERY_POLICY)
    schedule = _load(SCHEDULE_POLICY)

    assert recovery["recovery_counts_as_scheduler_proof"] is False
    assert recovery["recovery_counts_as_natural_wave3_slot"] is False
    assert recovery["recovery_counts_as_completed_scheduled_slot"] is False
    assert schedule["manual_recovery"]["counts_as_completed_operational_slot"] is False
    assert schedule["manual_recovery"]["counts_as_completed_scheduled_slot"] is False
