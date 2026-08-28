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


def _within_hourly_checkpoint_window(now: datetime, checkpoint_minute: int, window: int) -> bool:
    current = now.minute
    delta = abs(current - checkpoint_minute)
    return min(delta, 60 - delta) <= window


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
    post_deadline_reconciliation: bool = False,
) -> dict:
    """Resolve one governed Master Monitor checkpoint.

    `run_mode` is a caller hint only. Official deadline/live state has authority over the
    operating mode so an hourly scheduled invocation cannot accidentally miss Deadline Day
    or Match Mode just because the workflow called the generic daily orchestration path.
    """
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

    deadline_rule = registry.get("deadline_day") or {}
    deadline_lead = float(deadline_rule.get("lead_minutes", 1440))
    in_deadline_day = bool(
        minutes_to_deadline is not None
        and 0 <= minutes_to_deadline <= deadline_lead
    )
    is_final_review = bool(
        in_deadline_day
        and final_target
        and abs((now_local - final_target).total_seconds() / 60.0) <= final_window
    )

    master_minute = int(registry.get("master_hourly_minute", 30))
    master_window = int(registry.get("master_checkpoint_window_minutes", 20))
    is_master_checkpoint = _within_hourly_checkpoint_window(now_local, master_minute, master_window)

    # Collision priority: Deadline Final > Deadline > Match > normal scheduled > silent hourly.
    if post_deadline_reconciliation:
        policy_id = "POST_DEADLINE_RECONCILIATION"
    elif is_final_review:
        policy_id = "FINAL_DEADLINE_REVIEW"
    elif in_deadline_day:
        policy_id = "DEADLINE_MONITOR"
    elif is_live:
        policy_id = "MATCHDAY_LIVE"
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
        policy_id = scheduled or "INTERNAL_HOURLY_SILENT"

    selected = _policy(registry, policy_id)
    visible_output = bool(selected.get("visible_output"))
    deadline_full_report = policy_id in {"DEADLINE_MONITOR", "FINAL_DEADLINE_REVIEW"}

    return {
        "policy_id": policy_id,
        "label": selected.get("label"),
        "operating_mode": selected.get("operating_mode"),
        "requested_run_mode": run_mode,
        "run_mode": run_mode,
        "as_of": now.isoformat(),
        "local_as_of": now_local.isoformat(),
        "timezone": timezone_name,
        "deadline_time": deadline_dt.isoformat() if deadline_dt else None,
        "minutes_to_deadline": round(minutes_to_deadline, 1) if minutes_to_deadline is not None else None,
        "deadline_day_active": in_deadline_day,
        "is_final_review": policy_id == "FINAL_DEADLINE_REVIEW",
        "post_final_emergency_only": False,
        "post_deadline_reconciliation": policy_id == "POST_DEADLINE_RECONCILIATION",
        "is_live_match": bool(is_live),
        "is_master_hourly_checkpoint": is_master_checkpoint,
        "visible_output_authorized": visible_output,
        "full_visible_report_required": bool(selected.get("full_report_required")),
        "no_material_change_must_still_report": bool(selected.get("no_material_change_must_still_report")),
        "fresh_source_sweep_required": bool(selected.get("fresh_source_sweep_required")),
        "direct_official_refresh_max_age_minutes": selected.get("direct_official_refresh_max_age_minutes"),
        "price_radar_required": bool(selected.get("price_radar_required")),
        "duplicate_report_forbidden": True,
        "deadline_report_continues_after_final_review": bool(deadline_rule.get("continue_after_final_review", True)) if deadline_full_report else False,
        "is_simulation": bool(simulated),
        "max_snapshot_age_minutes": int(selected.get("max_snapshot_age_minutes", 90)),
        "recommended_refresh_minutes": int(selected.get("recommended_refresh_minutes", 60)),
        "payload": selected.get("payload"),
        "roster_contract": dict(selected.get("roster_contract") or {}),
        "report_scope": list(selected.get("report_scope") or []),
        "registry": registry.get("registry"),
        "registry_schema_version": registry.get("schema_version"),
    }
