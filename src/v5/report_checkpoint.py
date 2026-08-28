from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _checkpoint_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = str(value).split(":", 1)
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid report checkpoint time: {value}")
    return hour, minute


def resolve_report_checkpoint(
    now_utc: datetime,
    previous_state: dict[str, Any] | None,
    checkpoint_cfg: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = checkpoint_cfg if isinstance(checkpoint_cfg, dict) else {}
    state = dict(previous_state or {})
    history = [dict(row) for row in state.get("checkpoint_history") or [] if isinstance(row, dict)]
    if not bool(cfg.get("enabled", False)):
        checkpoint = {
            "schema": "v5_report_checkpoint_v1",
            "enabled": False,
            "current": {"kind": "ROUTINE", "label": "Report rutin"},
            "completeness": "NOT_APPLICABLE",
            "missed_due": [],
            "today": [],
        }
        return checkpoint, state

    timezone_name = str(cfg.get("timezone") or "Asia/Jakarta")
    zone = ZoneInfo(timezone_name)
    current_utc = now_utc
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    current_utc = current_utc.astimezone(timezone.utc)
    local_now = current_utc.astimezone(zone)
    local_date = local_now.date().isoformat()
    grace = timedelta(minutes=max(1, int(cfg.get("grace_minutes") or 60)))
    retain_days = max(1, int(cfg.get("history_days") or 14))
    cutoff = (local_now.date() - timedelta(days=retain_days)).isoformat()
    history = [row for row in history if str(row.get("local_date") or "") >= cutoff]

    slots = list(cfg.get("slots") or [])
    ids = [str(row.get("id") or "") for row in slots if isinstance(row, dict)]
    if not slots or len(ids) != len(slots) or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("V5 report checkpoint config requires unique non-empty slot ids")

    completed_today = {
        str(row.get("slot_id"))
        for row in history
        if row.get("local_date") == local_date and row.get("status") == "COMPLETED"
    }
    scheduled_rows: list[dict[str, Any]] = []
    for row in slots:
        hour, minute = _checkpoint_hhmm(str(row.get("time") or ""))
        scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        scheduled_rows.append({
            "id": str(row["id"]),
            "label": str(row.get("label") or row["id"]),
            "scheduled": scheduled,
        })
    scheduled_rows.sort(key=lambda row: row["scheduled"])

    due_slot: dict[str, Any] | None = None
    missed_due: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for row in scheduled_rows:
        slot_id = row["id"]
        scheduled = row["scheduled"]
        completed = slot_id in completed_today
        if completed:
            slot_state = "COMPLETED"
        elif local_now < scheduled:
            slot_state = "PENDING"
        elif local_now <= scheduled + grace:
            slot_state = "DUE"
            if due_slot is None:
                due_slot = row
        else:
            slot_state = "MISSED"
            missed_due.append({
                "id": slot_id,
                "label": row["label"],
                "scheduled_local": scheduled.isoformat(),
            })
        timeline.append({
            "id": slot_id,
            "label": row["label"],
            "scheduled_local": scheduled.isoformat(),
            "state": slot_state,
        })

    if due_slot is not None:
        slot_id = str(due_slot["id"])
        if slot_id not in completed_today:
            history.append({
                "slot_id": slot_id,
                "label": due_slot["label"],
                "local_date": local_date,
                "scheduled_local": due_slot["scheduled"].isoformat(),
                "generated_at_utc": current_utc.isoformat(),
                "generated_local": local_now.isoformat(),
                "status": "COMPLETED",
                "timeliness": "ON_TIME_WINDOW",
            })
            completed_today.add(slot_id)
            for item in timeline:
                if item["id"] == slot_id:
                    item["state"] = "COMPLETED"
                    break
        current = {
            "kind": "SCHEDULED_CHECKPOINT",
            "id": slot_id,
            "label": due_slot["label"],
            "scheduled_local": due_slot["scheduled"].isoformat(),
            "generated_local": local_now.isoformat(),
            "timeliness": "ON_TIME_WINDOW",
        }
    else:
        current = {
            "kind": "ROUTINE",
            "label": "Report rutin di luar checkpoint utama",
            "generated_local": local_now.isoformat(),
        }

    checkpoint = {
        "schema": "v5_report_checkpoint_v1",
        "enabled": True,
        "timezone": timezone_name,
        "current": current,
        "completeness": "ATTENTION_REQUIRED" if missed_due else "OK",
        "missed_due": missed_due,
        "today": timeline,
        "silent_missing_forbidden": bool(cfg.get("silent_missing_forbidden", True)),
    }
    state["checkpoint_history"] = history[-100:]
    state["last_checkpoint"] = checkpoint
    return checkpoint, state
