from __future__ import annotations

"""Single Python owner for V6 control-plane identity and role configuration."""

from dataclasses import dataclass
import json
from pathlib import Path

from .store import ROOT


@dataclass(frozen=True)
class ControlPlaneContract:
    runtime_branch: str
    control_issue_number: int
    issue_title_marker: str
    required_reason: str
    required_audit: str
    report_prefetch_command: str
    scheduler_authority_id: str
    watchdog_role: str
    recovery_role: str


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"control-plane config unavailable: {path}") from exc


def load_control_plane_contract(
    *,
    schedule_policy_path: Path | None = None,
    watchdog_path: Path | None = None,
    recovery_path: Path | None = None,
) -> ControlPlaneContract:
    schedule = _read_json(
        schedule_policy_path or ROOT / "config" / "v6" / "schedule_policy.json"
    )
    watchdog = _read_json(
        watchdog_path or ROOT / "config" / "v6" / "scheduler_watchdog.json"
    )
    recovery = _read_json(
        recovery_path or ROOT / "config" / "v6" / "scheduler_recovery.json"
    )
    scheduler = dict(schedule.get("scheduler_authority") or {})
    prefetch = dict(schedule.get("report_prefetch") or {})

    runtime_branch = str(schedule.get("runtime_branch") or "").strip()
    issue_title_marker = str(scheduler.get("issue_title_marker") or "").strip()
    required_reason = str(scheduler.get("required_reason") or "").strip()
    required_audit = str(scheduler.get("required_audit") or "").strip()
    report_prefetch_command = str(prefetch.get("issue_comment_command") or "").strip()
    scheduler_authority_id = str(scheduler.get("runtime_authority_id") or "").strip()
    watchdog_role = str(watchdog.get("role") or "").strip()
    recovery_role = str(recovery.get("role") or "").strip()
    try:
        control_issue_number = int(scheduler.get("control_issue_number"))
    except (TypeError, ValueError) as exc:
        raise ValueError("control-plane control_issue_number must be an integer") from exc

    required = {
        "runtime_branch": runtime_branch,
        "issue_title_marker": issue_title_marker,
        "required_reason": required_reason,
        "required_audit": required_audit,
        "report_prefetch_command": report_prefetch_command,
        "scheduler_authority_id": scheduler_authority_id,
        "watchdog_role": watchdog_role,
        "recovery_role": recovery_role,
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        raise ValueError("control-plane required field missing: " + ",".join(missing))
    if control_issue_number <= 0:
        raise ValueError("control-plane control_issue_number must be positive")

    return ControlPlaneContract(
        runtime_branch=runtime_branch,
        control_issue_number=control_issue_number,
        issue_title_marker=issue_title_marker,
        required_reason=required_reason,
        required_audit=required_audit,
        report_prefetch_command=report_prefetch_command,
        scheduler_authority_id=scheduler_authority_id,
        watchdog_role=watchdog_role,
        recovery_role=recovery_role,
    )


CONTROL_PLANE = load_control_plane_contract()
