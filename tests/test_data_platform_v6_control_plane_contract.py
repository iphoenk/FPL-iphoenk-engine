import json
from pathlib import Path

from src.runtime_v6.control_plane_contract import validate_control_plane_contract

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    return json.loads((ROOT / "config" / "v6" / name).read_text(encoding="utf-8"))


def test_current_control_plane_contract_is_consistent():
    failures = validate_control_plane_contract(
        _load("schedule_policy.json"),
        _load("scheduler_watchdog.json"),
        _load("scheduler_recovery.json"),
    )
    assert failures == []


def test_control_plane_contract_rejects_issue_marker_or_authority_drift():
    schedule = _load("schedule_policy.json")
    watchdog = _load("scheduler_watchdog.json")
    recovery = _load("scheduler_recovery.json")

    watchdog["incident"]["control_issue_number"] = 999
    recovery["normal_scheduler_authority"] = "GITHUB_ACTIONS"
    schedule["master_orchestrated"]["issue_title_marker"] = "OTHER_MARKER"

    failures = validate_control_plane_contract(schedule, watchdog, recovery)
    assert any("control issue" in failure.lower() for failure in failures)
    assert any("scheduler authority" in failure.lower() for failure in failures)
    assert any("issue title marker" in failure.lower() for failure in failures)
