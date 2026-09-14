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
    assert watchdog["core_scheduler_authority"] == schedule["scheduler"]["authority"]
    assert recovery["core_scheduler_authority"] == schedule["scheduler"]["authority"]
    assert watchdog["control_issue_number"] == schedule["scheduler"]["control_issue_number"]


def test_scheduler_threshold_semantics_are_explicit_and_ordered():
    schedule = _load(SCHEDULE_POLICY)
    watchdog = _load(WATCHDOG_POLICY)
    assert watchdog["proof_fresh_after_minutes"] == schedule["scheduler"]["proof_fresh_after_minutes"]
    assert watchdog["warning_minutes"] > watchdog["proof_fresh_after_minutes"]
    assert watchdog["critical_minutes"] == schedule["scheduler"]["proof_stale_after_minutes"]
    assert watchdog["critical_minutes"] > watchdog["warning_minutes"]


def test_recovery_contract_is_explicitly_non_authoritative():
    recovery = _load(RECOVERY_POLICY)
    assert recovery["counts_as_scheduler_proof"] is False
    assert recovery["counts_as_natural_slot"] is False
    assert recovery["counts_as_completed_scheduled_slot"] is False
