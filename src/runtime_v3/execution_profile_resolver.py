from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from src.utils import DATA, ROOT, read_json

POLICY_PATH = ROOT / "config" / "runtime" / "execution_profile_policy.json"
REPORTING_PATH = ROOT / "config" / "intelligence" / "reporting.json"
REPORT_STATE_PATH = DATA / "report_state.json"
COMPLETED_STATUSES = {"COMPLETED", "LATE_RECOVERED"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid checkpoint time: {value}")
    return hour, minute


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_EXECUTION_PROFILE_POLICY_V1":
        raise RuntimeError("unexpected V3 execution profile policy")
    default = payload.get("default") or {}
    modes = payload.get("visible_modes") or {}
    if not default.get("profile") or not default.get("mode") or not isinstance(modes, dict):
        raise RuntimeError("execution profile policy is incomplete")
    for name, spec in modes.items():
        if not isinstance(spec, dict) or not spec.get("profile") or not spec.get("mode"):
            raise RuntimeError(f"invalid execution profile mapping: {name}")
    return payload


@lru_cache(maxsize=1)
def load_reporting_policy() -> dict[str, Any]:
    payload = json.loads(REPORTING_PATH.read_text(encoding="utf-8"))
    checkpoints = payload.get("scheduled_report_checkpoints") or {}
    if checkpoints.get("enabled"):
        ids = [str(row.get("id") or "") for row in checkpoints.get("slots") or []]
        if not ids or any(not value for value in ids) or len(ids) != len(set(ids)):
            raise RuntimeError("scheduled report checkpoints require unique non-empty ids")
    return payload


def _base_mode_key(
    visible_mode: str,
    *,
    deadline_intensive: bool,
    match_window: bool,
    post_deadline_reconciliation: bool,
) -> str | None:
    policy = load_policy()
    modes = policy.get("visible_modes") or {}
    conditions = policy.get("condition_modes") or {}
    if visible_mode == "NORMAL_DEEP_REVIEW":
        return visible_mode
    if deadline_intensive:
        return str(conditions.get("deadline_intensive") or "DEADLINE_DAY")
    if match_window:
        return str(conditions.get("match_window") or "MATCH_MODE")
    if post_deadline_reconciliation:
        return str(conditions.get("post_deadline_reconciliation") or "POST_DEADLINE_RECONCILIATION")
    return visible_mode if visible_mode in modes else None


def _profile_spec(mode_key: str | None) -> dict[str, Any]:
    policy = load_policy()
    default = dict(policy.get("default") or {})
    if mode_key is None:
        return default
    spec = (policy.get("visible_modes") or {}).get(mode_key)
    if not isinstance(spec, dict):
        return default
    return dict(spec)


def overdue_checkpoint_plan(
    now_utc: datetime,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reporting = load_reporting_policy().get("scheduled_report_checkpoints") or {}
    recovery = load_policy().get("checkpoint_recovery") or {}
    if not reporting.get("enabled") or not (load_policy().get("recovery") or {}).get("enabled"):
        return {"required": False, "checkpoint_ids": [], "required_mode": None, "rows": []}

    tz = ZoneInfo(str(reporting.get("timezone") or "Asia/Jakarta"))
    local_now = now_utc.astimezone(timezone.utc).astimezone(tz)
    local_date = local_now.date().isoformat()
    grace = timedelta(minutes=max(1, int(reporting.get("grace_minutes") or 60)))
    history = [row for row in (state or {}).get("checkpoint_history") or [] if isinstance(row, dict)]
    completed = {
        str(row.get("slot_id") or "")
        for row in history
        if row.get("local_date") == local_date and str(row.get("status") or "") in COMPLETED_STATUSES
    }

    rows: list[dict[str, Any]] = []
    for slot in reporting.get("slots") or []:
        slot_id = str(slot.get("id") or "")
        recovery_spec = recovery.get(slot_id) if isinstance(recovery.get(slot_id), dict) else {}
        if not slot_id or slot_id in completed or recovery_spec.get("enabled") is not True:
            continue
        hour, minute = _parse_hhmm(str(slot.get("time") or ""))
        scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local_now <= scheduled + grace:
            continue
        visible_mode = str(recovery_spec.get("visible_mode") or "")
        mode_spec = _profile_spec(visible_mode)
        if not visible_mode or visible_mode not in (load_policy().get("visible_modes") or {}):
            raise RuntimeError(f"checkpoint recovery mode is not registered: {slot_id}:{visible_mode}")
        rows.append({
            "id": slot_id,
            "label": str(slot.get("label") or slot_id),
            "scheduled_local": scheduled.isoformat(),
            "visible_mode": visible_mode,
            "profile": mode_spec.get("profile"),
            "mode": mode_spec.get("mode"),
            "extra": mode_spec.get("extra") or "",
            "rank": int(mode_spec.get("rank") or 0),
        })

    if not rows:
        return {"required": False, "checkpoint_ids": [], "required_mode": None, "rows": []}
    required = max(rows, key=lambda row: (int(row.get("rank") or 0), row.get("scheduled_local") or ""))
    return {
        "required": True,
        "checkpoint_ids": [row["id"] for row in rows],
        "required_mode": required.get("visible_mode"),
        "rows": rows,
    }


def resolve_execution_profile(
    *,
    visible_mode: str,
    deadline_intensive: bool,
    match_window: bool,
    post_deadline_reconciliation: bool,
    now_utc: datetime | None = None,
    report_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    mode_key = _base_mode_key(
        visible_mode,
        deadline_intensive=deadline_intensive,
        match_window=match_window,
        post_deadline_reconciliation=post_deadline_reconciliation,
    )
    selected = _profile_spec(mode_key)
    recovery_plan = overdue_checkpoint_plan(now, report_state)
    recovery_cfg = load_policy().get("recovery") or {}
    allowed_base_modes = {str(value) for value in recovery_cfg.get("allowed_base_modes") or ["daily"]}
    recovery_ids: list[str] = []
    recovery_mode: str | None = None

    if recovery_plan.get("required") and str(selected.get("mode") or "") in allowed_base_modes:
        candidate = _profile_spec(str(recovery_plan.get("required_mode") or ""))
        if int(candidate.get("rank") or 0) > int(selected.get("rank") or 0):
            selected["profile"] = candidate.get("profile")
            selected["extra"] = candidate.get("extra") or ""
        recovery_ids = list(recovery_plan.get("checkpoint_ids") or [])
        recovery_mode = str(recovery_plan.get("required_mode") or "") or None

    return {
        "profile": str(selected.get("profile") or "fast_decision"),
        "mode": str(selected.get("mode") or "daily"),
        "extra": str(selected.get("extra") or ""),
        "selected_mode_key": mode_key or "DEFAULT",
        "recovery_required": bool(recovery_ids),
        "recovery_checkpoint_ids": recovery_ids,
        "recovery_mode": recovery_mode,
        "deferred_recovery": bool(recovery_plan.get("required") and not recovery_ids),
        "deferred_checkpoint_ids": list(recovery_plan.get("checkpoint_ids") or []) if recovery_plan.get("required") and not recovery_ids else [],
    }


def main() -> int:
    result = resolve_execution_profile(
        visible_mode=os.getenv("FPL_VISIBLE_MODE", "SILENT"),
        deadline_intensive=_truthy(os.getenv("FPL_DEADLINE_INTENSIVE")),
        match_window=_truthy(os.getenv("FPL_MATCH_WINDOW")),
        post_deadline_reconciliation=_truthy(os.getenv("FPL_POST_DEADLINE_RECONCILIATION")),
        report_state=read_json(REPORT_STATE_PATH, {}),
    )
    output = os.getenv("GITHUB_OUTPUT")
    lines = [
        f"profile={result['profile']}",
        f"mode={result['mode']}",
        f"extra={result['extra']}",
        f"recovery_required={'true' if result['recovery_required'] else 'false'}",
        f"recovery_checkpoint_ids={','.join(result['recovery_checkpoint_ids'])}",
        f"recovery_mode={result['recovery_mode'] or ''}",
        f"deferred_recovery={'true' if result['deferred_recovery'] else 'false'}",
    ]
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
