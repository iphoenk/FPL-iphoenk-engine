from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.utils import CONFIG, parse_dt, read_json, utcnow

REGISTRY = CONFIG / "checkpoint_policy_registry.json"


def _clock_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _within_clock_late_window(now: datetime, clock: str, window: int) -> bool:
    """Accept a checkpoint at its target minute or shortly after it.

    GitHub scheduled runs can start late. We deliberately do not accept an early run,
    otherwise 04:10 could accidentally satisfy a 04:30 visible checkpoint.
    """
    target = _clock_minutes(clock)
    current = now.hour * 60 + now.minute
    delta = (current - target) % 1440
    return 0 <= delta <= window


def _within_hourly_checkpoint_late_window(now: datetime, checkpoint_minute: int, window: int) -> bool:
    delta = (now.minute - checkpoint_minute) % 60
    return 0 <= delta <= window


def _within_datetime_late_window(now: datetime, target: datetime, window: int) -> bool:
    delta = (now - target).total_seconds() / 60.0
    return 0 <= delta <= window


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


def _normal_scheduled_policy(now_local: datetime, registry: dict) -> str | None:
    scheduled_window = int(registry.get("scheduled_window_minutes", 20))
    return next(
        (
            policy_id
            for policy_id in ("DEEP_REVIEW_0430", "MIDDAY_TACTICAL_1230", "NIGHT_TACTICAL_PRICE_2130")
            if _within_clock_late_window(
                now_local,
                str(_policy(registry, policy_id).get("local_time")),
                scheduled_window,
            )
        ),
        None,
    )


def _merge_unique(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _merge_policy_contracts(registry: dict, primary_id: str, absorbed_ids: list[str]) -> dict:
    primary = _policy(registry, primary_id)
    absorbed = [_policy(registry, policy_id) for policy_id in absorbed_ids]
    scopes = _merge_unique(
        list(primary.get("report_scope") or []),
        *[list(row.get("report_scope") or []) for row in absorbed],
    )
    roster = dict(primary.get("roster_contract") or {})
    for row in absorbed:
        for key, value in (row.get("roster_contract") or {}).items():
            roster[key] = max(int(roster.get(key) or 0), int(value or 0))
    payloads = _merge_unique(
        [str(primary.get("payload"))] if primary.get("payload") else [],
        *[[str(row.get("payload"))] if row.get("payload") else [] for row in absorbed],
    )
    max_ages = [int(primary.get("max_snapshot_age_minutes", 90))] + [
        int(row.get("max_snapshot_age_minutes", 90)) for row in absorbed
    ]
    refreshes = [int(primary.get("recommended_refresh_minutes", 60))] + [
        int(row.get("recommended_refresh_minutes", 60)) for row in absorbed
    ]
    return {
        "report_scope": scopes,
        "roster_contract": roster,
        "payloads": payloads,
        "max_snapshot_age_minutes": min(max_ages),
        "recommended_refresh_minutes": min(refreshes),
        "price_radar_required": any(bool(row.get("price_radar_required")) for row in [primary, *absorbed]),
        "fresh_source_sweep_required": any(bool(row.get("fresh_source_sweep_required")) for row in [primary, *absorbed]),
        "full_report_required": any(bool(row.get("full_report_required")) for row in [primary, *absorbed]),
        "no_material_change_must_still_report": any(
            bool(row.get("no_material_change_must_still_report")) for row in [primary, *absorbed]
        ),
        "direct_official_refresh_max_age_minutes": min(
            [
                int(row["direct_official_refresh_max_age_minutes"])
                for row in [primary, *absorbed]
                if row.get("direct_official_refresh_max_age_minutes") is not None
            ],
            default=None,
        ),
    }


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

    Official deadline/live state has authority over the caller hint. Routine Deadline Day
    reports are only authorized at the governed :30 checkpoint, while an additional timing
    probe may catch an exact Final Review that falls at :00 (for example 17:00 for an 18:30
    deadline) without emitting an extra ordinary Deadline Day report.
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
        and _within_datetime_late_window(now_local, final_target, final_window)
    )

    master_minute = int(registry.get("master_hourly_minute", 30))
    master_window = int(registry.get("master_checkpoint_window_minutes", 20))
    is_master_checkpoint = _within_hourly_checkpoint_late_window(now_local, master_minute, master_window)
    scheduled_policy = _normal_scheduled_policy(now_local, registry)

    absorbed_policy_ids: list[str] = []
    if post_deadline_reconciliation:
        policy_id = "POST_DEADLINE_RECONCILIATION"
    elif is_final_review:
        policy_id = "FINAL_DEADLINE_REVIEW"
        if is_live:
            absorbed_policy_ids.append("MATCHDAY_LIVE")
        if scheduled_policy:
            absorbed_policy_ids.append(scheduled_policy)
    elif in_deadline_day and is_master_checkpoint:
        policy_id = "DEADLINE_MONITOR"
        if is_live:
            absorbed_policy_ids.append("MATCHDAY_LIVE")
        if scheduled_policy:
            absorbed_policy_ids.append(scheduled_policy)
    elif in_deadline_day:
        # A :00 timing probe inside T-24h remains silent unless it is the exact Final Review.
        policy_id = "INTERNAL_HOURLY_SILENT"
    elif is_live and is_master_checkpoint:
        policy_id = "MATCHDAY_LIVE"
        if scheduled_policy:
            absorbed_policy_ids.append(scheduled_policy)
    elif scheduled_policy:
        policy_id = scheduled_policy
    else:
        policy_id = "INTERNAL_HOURLY_SILENT"

    selected = _policy(registry, policy_id)
    merged = _merge_policy_contracts(registry, policy_id, absorbed_policy_ids)
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
        "final_review_target_local": final_target.isoformat() if final_target else None,
        "post_final_emergency_only": False,
        "post_deadline_reconciliation": policy_id == "POST_DEADLINE_RECONCILIATION",
        "is_live_match": bool(is_live),
        "is_master_hourly_checkpoint": is_master_checkpoint,
        "timing_probe_only": bool(in_deadline_day and not is_master_checkpoint and not is_final_review),
        "visible_output_authorized": visible_output,
        "full_visible_report_required": merged["full_report_required"],
        "no_material_change_must_still_report": merged["no_material_change_must_still_report"],
        "fresh_source_sweep_required": merged["fresh_source_sweep_required"],
        "direct_official_refresh_max_age_minutes": merged["direct_official_refresh_max_age_minutes"],
        "price_radar_required": merged["price_radar_required"],
        "duplicate_report_forbidden": True,
        "absorbed_policy_ids": absorbed_policy_ids,
        "collision_merged": bool(absorbed_policy_ids),
        "deadline_report_continues_after_final_review": bool(deadline_rule.get("continue_after_final_review", True)) if deadline_full_report else False,
        "is_simulation": bool(simulated),
        "max_snapshot_age_minutes": merged["max_snapshot_age_minutes"],
        "recommended_refresh_minutes": merged["recommended_refresh_minutes"],
        "payload": merged["payloads"][0] if merged["payloads"] else None,
        "payloads": merged["payloads"],
        "roster_contract": merged["roster_contract"],
        "report_scope": merged["report_scope"],
        "registry": registry.get("registry"),
        "registry_schema_version": registry.get("schema_version"),
    }
