from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.utils import CONFIG, parse_dt, read_json, utcnow

REGISTRY = CONFIG / "checkpoint_policy_registry.json"


def _clock_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _within_clock_window(now: datetime, clock: str, window: int) -> bool:
    target = _clock_minutes(clock)
    current = now.hour * 60 + now.minute
    delta = abs(current - target)
    return min(delta, 1440 - delta) <= window


def _policy(registry: dict, policy_id: str) -> dict:
    row = dict((registry.get("policies") or {}).get(policy_id) or {})
    if not row:
        raise RuntimeError(f"checkpoint policy missing: {policy_id}")
    return row


def _final_lead_minutes(deadline_local: datetime, registry: dict) -> int:
    rule = registry.get("final_review") or {}
    start = _clock_minutes(str(rule.get("early_morning_deadline_start", "00:00")))
    end = _clock_minutes(str(rule.get("early_morning_deadline_end", "01:59")))
    deadline_minute = deadline_local.hour * 60 + deadline_local.minute
    if start <= deadline_minute <= end:
        return int(rule.get("early_morning_lead_minutes", 180))
    return int(rule.get("default_lead_minutes", 90))


def resolve_checkpoint(
    run_mode: str,
    deadline: str | None,
    is_live: bool = False,
    as_of: datetime | str | None = None,
    simulated: bool = False,
    registry: dict | None = None,
) -> dict:
    registry = registry or read_json(REGISTRY, {})
    timezone_name = str(registry.get("timezone") or "Asia/Jakarta")
    tz = ZoneInfo(timezone_name)
    if isinstance(as_of, str):
        now = parse_dt(as_of)
    else:
        now = as_of
    now = now or utcnow()
    if now.tzinfo is None:
        raise RuntimeError("checkpoint as_of must be timezone-aware")
    now_local = now.astimezone(tz)
    deadline_dt = parse_dt(deadline)
    deadline_local = deadline_dt.astimezone(tz) if deadline_dt else None
    minutes_to_deadline = None
    final_target = None
    final_window = int((registry.get("final_review") or {}).get("window_minutes", 20))

    if deadline_local:
        minutes_to_deadline = (deadline_local - now_local).total_seconds() / 60.0
        final_target = deadline_local - timedelta(minutes=_final_lead_minutes(deadline_local, registry))

    if is_live or run_mode == "live":
        policy_id = "MATCHDAY_LIVE"
    elif final_target and abs((now_local - final_target).total_seconds() / 60.0) <= final_window:
        policy_id = "FINAL_DEADLINE_REVIEW"
    elif final_target and final_target + timedelta(minutes=final_window) < now_local < deadline_local:
        policy_id = "POST_FINAL_EMERGENCY_ONLY"
    else:
        scheduled_window = int(registry.get("scheduled_window_minutes", 20))
        scheduled = next(
            (
                policy_id
                for policy_id in ("DEEP_REVIEW_0430", "MIDDAY_TACTICAL_1230", "NIGHT_TACTICAL_PRICE_2130")
                if _within_clock_window(now_local, str(_policy(registry, policy_id).get("local_time")), scheduled_window)
            ),
            None,
        )
        if scheduled:
            policy_id = scheduled
        elif run_mode == "deadline" and minutes_to_deadline is not None and 0 < minutes_to_deadline <= 1440:
            policy_id = "DEADLINE_MONITOR"
        else:
            policy_id = "REGULAR_MONITOR"

    selected = _policy(registry, policy_id)
    return {
        "policy_id": policy_id,
        "label": selected.get("label"),
        "run_mode": run_mode,
        "as_of": now.isoformat(),
        "local_as_of": now_local.isoformat(),
        "timezone": timezone_name,
        "deadline_time": deadline_dt.isoformat() if deadline_dt else None,
        "minutes_to_deadline": round(minutes_to_deadline, 1) if minutes_to_deadline is not None else None,
        "is_final_review": policy_id == "FINAL_DEADLINE_REVIEW",
        "post_final_emergency_only": policy_id == "POST_FINAL_EMERGENCY_ONLY",
        "is_simulation": bool(simulated),
        "max_snapshot_age_minutes": int(selected.get("max_snapshot_age_minutes", 90)),
        "recommended_refresh_minutes": int(selected.get("recommended_refresh_minutes", 60)),
        "report_scope": list(selected.get("report_scope") or []),
        "registry": registry.get("registry"),
        "registry_schema_version": registry.get("schema_version"),
    }
