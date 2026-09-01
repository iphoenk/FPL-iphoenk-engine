from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
PRECOMPUTE_ROLE = "PRECOMPUTE_NEXT_CHECKPOINT"
PRIMARY_FALLBACK_ROLE = "PRIMARY_FALLBACK_CURRENT_CHECKPOINT"
UNSCOPED_ROLE = "ADAPTIVE_OR_MANUAL_REFRESH"


def _event_schedule(env: dict[str, str] | None = None) -> str:
    env = env or os.environ
    explicit = str(env.get("V4_SCHEDULE_EXPR") or "").strip()
    if explicit:
        return explicit
    event_path = str(env.get("GITHUB_EVENT_PATH") or "").strip()
    if not event_path:
        return ""
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("schedule") or "").strip()


def _normal_visible_mode(target_utc: datetime) -> str:
    local = target_utc.astimezone(WIB)
    clock = local.strftime("%H:%M")
    return {
        "04:30": "NORMAL_DEEP_REVIEW",
        "12:30": "NORMAL_MIDDAY",
        "21:30": "NORMAL_NIGHT",
    }.get(clock, "DYNAMIC_CHECKPOINT")


def _target_at_minute(now_utc: datetime, minute: int, *, upcoming: bool) -> datetime:
    now_utc = now_utc.astimezone(timezone.utc)
    target = now_utc.replace(minute=minute, second=0, microsecond=0)
    if upcoming:
        if now_utc >= target:
            target += timedelta(hours=1)
    elif now_utc.minute < minute:
        target -= timedelta(hours=1)
    return target


def resolve_runtime_checkpoint_metadata(
    generated_at: datetime,
    *,
    event_name: str | None = None,
    schedule_expr: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at.astimezone(timezone.utc)
    event_name = str(event_name or os.getenv("GITHUB_EVENT_NAME") or "").strip()
    schedule = str(schedule_expr if schedule_expr is not None else _event_schedule()).strip()

    role = UNSCOPED_ROLE
    target: datetime | None = None
    if event_name == "schedule" and schedule == "15 * * * *":
        role = PRECOMPUTE_ROLE
        target = _target_at_minute(generated_at, 30, upcoming=True)
    elif event_name == "schedule" and schedule == "30 * * * *":
        role = PRIMARY_FALLBACK_ROLE
        target = _target_at_minute(generated_at, 30, upcoming=False)

    precomputed = role == PRECOMPUTE_ROLE
    generated_before_or_at_target = bool(target is not None and generated_at <= target)
    if precomputed and (target is None or not generated_before_or_at_target):
        raise RuntimeError("V4 precompute must target a future/current logical :30 checkpoint")

    return {
        "snapshot_role": role,
        "target_checkpoint": target.isoformat() if target else None,
        "target_checkpoint_local": target.astimezone(WIB).isoformat() if target else None,
        "target_visible_mode": _normal_visible_mode(target) if target else None,
        "precomputed": precomputed,
        "generated_before_or_at_target": generated_before_or_at_target,
        "materialization_complete": True,
        "publication_proof": "PRESENCE_ON_RUNTIME_BRANCH",
        "schedule_expression": schedule or None,
        "timezone_authority": "Asia/Jakarta",
    }
