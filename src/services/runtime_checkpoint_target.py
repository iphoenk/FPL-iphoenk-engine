from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
PRECOMPUTE_ROLE = "PRECOMPUTE_NEXT_CHECKPOINT"
LATE_PRECOMPUTE_ROLE = "LATE_PRECOMPUTE_RECOVERY"
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


def _precompute_target(now_utc: datetime) -> datetime:
    """Resolve the intended logical :30 for a physical :15 scheduler run.

    A modest GitHub scheduler delay through :44 still belongs to the same :30
    checkpoint and is therefore visibly late rather than silently retargeted.
    At :45 or later, the run may only prepare the next logical checkpoint.
    """
    now_utc = now_utc.astimezone(timezone.utc)
    target = now_utc.replace(minute=30, second=0, microsecond=0)
    if now_utc.minute >= 45:
        target += timedelta(hours=1)
    return target


def _primary_target(now_utc: datetime) -> datetime:
    now_utc = now_utc.astimezone(timezone.utc)
    target = now_utc.replace(minute=30, second=0, microsecond=0)
    if now_utc.minute < 30:
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
        target = _precompute_target(generated_at)
        role = PRECOMPUTE_ROLE if generated_at <= target else LATE_PRECOMPUTE_ROLE
    elif event_name == "schedule" and schedule == "30 * * * *":
        role = PRIMARY_FALLBACK_ROLE
        target = _primary_target(generated_at)

    precomputed = role == PRECOMPUTE_ROLE
    generated_before_or_at_target = bool(target is not None and generated_at <= target)

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
