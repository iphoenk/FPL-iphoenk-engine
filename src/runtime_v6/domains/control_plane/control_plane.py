from __future__ import annotations

"""Single Python owner for V6 control-plane identity, roles and thresholds."""

from dataclasses import dataclass
import json
from pathlib import Path

from ...store import ROOT


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
    watchdog_warning_minutes: float
    watchdog_critical_minutes: float
    recovery_cooldown_minutes: float
    governed_event_settle_minutes: float


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"control-plane config unavailable: {path}") from exc


def _positive_number(value, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"control-plane {label} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"control-plane {label} must be positive")
    return parsed


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
    watchdog_schedule = dict(watchdog.get("schedule") or {})

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

    watchdog_warning_minutes = _positive_number(
        watchdog_schedule.get("warning_after_minutes"),
        label="watchdog_warning_minutes",
    )
    watchdog_critical_minutes = _positive_number(
        watchdog_schedule.get("critical_after_minutes"),
        label="watchdog_critical_minutes",
    )
    recovery_cooldown_minutes = _positive_number(
        recovery.get("recovery_cooldown_minutes"),
        label="recovery_cooldown_minutes",
    )
    governed_event_settle_minutes = _positive_number(
        recovery.get("governed_event_settle_minutes"),
        label="governed_event_settle_minutes",
    )

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
    if watchdog_critical_minutes <= watchdog_warning_minutes:
        raise ValueError("control-plane watchdog critical threshold must exceed warning threshold")

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
        watchdog_warning_minutes=watchdog_warning_minutes,
        watchdog_critical_minutes=watchdog_critical_minutes,
        recovery_cooldown_minutes=recovery_cooldown_minutes,
        governed_event_settle_minutes=governed_event_settle_minutes,
    )


CONTROL_PLANE = load_control_plane_contract()
