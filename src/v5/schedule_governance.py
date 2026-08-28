from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_time_schedule_governance.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("master_evaluation"), dict):
        raise RuntimeError("invalid V5 time schedule governance registry")
    return data


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clock_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _final_lead_minutes(deadline_local: datetime, cfg: dict[str, Any]) -> int:
    rule = ((cfg.get("deadline_day") or {}).get("final_review") or {})
    start = _clock_minutes(str(rule.get("early_deadline_start", "00:00")))
    end = _clock_minutes(str(rule.get("early_deadline_end", "01:59")))
    value = deadline_local.hour * 60 + deadline_local.minute
    if start <= value <= end:
        return int(rule.get("early_lead_minutes", 180))
    return int(rule.get("default_lead_minutes", 90))


def _same_minute(a: datetime, b: datetime) -> bool:
    return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)


def _normal_checkpoint(now_local: datetime, cfg: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    key = now_local.strftime("%H:%M")
    row = (cfg.get("normal_schedule") or {}).get(key)
    if isinstance(row, dict):
        return str(row.get("mode") or ""), row
    return None, {}


def _source_status_contract(cfg: dict[str, Any], observations: dict[str, Any] | None) -> dict[str, str]:
    deadline = cfg.get("deadline_day") or {}
    allowed = {str(value) for value in deadline.get("named_source_statuses") or []}
    supplied = observations if isinstance(observations, dict) else {}
    out: dict[str, str] = {}
    for tier in (deadline.get("source_tiers") or {}).values():
        for source in tier or []:
            raw = supplied.get(str(source))
            if isinstance(raw, dict):
                status = str(raw.get("status") or "UNAVAILABLE")
            elif raw is not None:
                status = str(raw)
            else:
                status = "UNAVAILABLE"
            out[str(source)] = status if status in allowed else "UNAVAILABLE"
    return out


def resolve_schedule(
    context: dict[str, Any],
    *,
    now: datetime | str | None = None,
    official_deadline_time: datetime | str | None = None,
    live_match_active: bool = False,
    runtime_age_minutes: float | None = None,
    material_native_state_may_have_changed: bool = False,
    price_actionable: bool = False,
    permitted_emergency: bool = False,
    source_observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    tz = ZoneInfo(str(cfg.get("timezone") or "Asia/Jakarta"))
    current = _parse_dt(now) or datetime.now(timezone.utc)
    now_local = current.astimezone(tz)
    deadline = _parse_dt(official_deadline_time or context.get("deadline_time"))
    deadline_local = deadline.astimezone(tz) if deadline else None
    minutes_to_deadline = (deadline_local - now_local).total_seconds() / 60.0 if deadline_local else None

    master = cfg.get("master_evaluation") or {}
    master_minute = int(master.get("minute", 30))
    hourly_checkpoint = now_local.minute == master_minute
    normal_mode, normal_row = _normal_checkpoint(now_local, cfg)

    deadline_cfg = cfg.get("deadline_day") or {}
    deadline_lead = int(deadline_cfg.get("lead_minutes", 1440))
    inside_deadline_day = bool(
        minutes_to_deadline is not None
        and 0.0 <= minutes_to_deadline <= float(deadline_lead)
    )
    deadline_boundary = bool(minutes_to_deadline is not None and abs(minutes_to_deadline) < 1.0)

    final_target = None
    final_due = False
    if deadline_local:
        final_target = deadline_local - timedelta(minutes=_final_lead_minutes(deadline_local, cfg))
        final_due = inside_deadline_day and _same_minute(now_local, final_target)

    scoring_gw = context.get("scoring_gw")
    gameweek_active = bool(context.get("is_live_event")) or str(context.get("phase") or "") in {"LIVE", "POST_DEADLINE"}
    match_due = bool(hourly_checkpoint and live_match_active and scoring_gw is not None and gameweek_active)

    candidate_modes: list[str] = []
    if final_due:
        candidate_modes.append("DEADLINE_DAY_FINAL_REVIEW")
    if inside_deadline_day and hourly_checkpoint:
        candidate_modes.append("DEADLINE_DAY")
    if match_due:
        candidate_modes.append("MATCH_MODE")
    if normal_mode:
        candidate_modes.append(normal_mode)
    if price_actionable:
        candidate_modes.append("CRITICAL_PRICE_ALERT")
    if permitted_emergency:
        candidate_modes.append("PERMITTED_EMERGENCY")

    priority = [str(value) for value in cfg.get("mode_priority") or []]
    active_mode = next((mode for mode in priority if mode in candidate_modes), "INTERNAL_ONLY")
    visible = active_mode != "INTERNAL_ONLY"

    force_full = False
    payload_path = None
    price_radar_required = False
    if active_mode in {"DEADLINE_DAY", "DEADLINE_DAY_FINAL_REVIEW"}:
        force_full = bool(deadline_cfg.get("force_full_report", True))
        payload_path = "data/deep_review_payload.json" if active_mode == "DEADLINE_DAY_FINAL_REVIEW" else "data/decision_brief.json"
        price_radar_required = True
    elif normal_mode and normal_mode in candidate_modes:
        force_full = bool(normal_row.get("force_full_report", False))
        payload_path = normal_row.get("payload")
        price_radar_required = bool(normal_row.get("price_radar_required", False))
    elif active_mode == "MATCH_MODE":
        payload_path = "data/decision_brief.json"
        price_radar_required = bool(normal_mode)
    elif active_mode in {"CRITICAL_PRICE_ALERT", "PERMITTED_EMERGENCY"}:
        payload_path = "data/decision_brief.json"
        price_radar_required = active_mode == "CRITICAL_PRICE_ALERT"

    refresh_reasons: list[str] = []
    direct_cfg = deadline_cfg.get("direct_official_refresh") or {}
    if inside_deadline_day:
        threshold = float(direct_cfg.get("runtime_age_threshold_minutes", 30))
        if runtime_age_minutes is not None and float(runtime_age_minutes) > threshold:
            refresh_reasons.append("RUNTIME_BRIDGE_OLDER_THAN_30_MINUTES")
        if bool(material_native_state_may_have_changed) and bool(direct_cfg.get("refresh_on_material_native_state_risk", True)):
            refresh_reasons.append("MATERIAL_NATIVE_STATE_MAY_HAVE_CHANGED")

    fresh_source_sweep = bool(
        active_mode in {"DEADLINE_DAY", "DEADLINE_DAY_FINAL_REVIEW"}
        and deadline_cfg.get("fresh_source_sweep_required", True)
    )
    source_statuses = _source_status_contract(cfg, source_observations) if fresh_source_sweep else {}

    lower_priority = [mode for mode in candidate_modes if mode != active_mode]
    comparator_triggers: list[str] = []
    if active_mode == "NORMAL_DEEP_REVIEW":
        comparator_triggers.append("normal_deep_review_0430")
    if active_mode in {"DEADLINE_DAY", "DEADLINE_DAY_FINAL_REVIEW"}:
        comparator_triggers.append("deadline_day_checkpoint")
    if active_mode == "MATCH_MODE":
        comparator_triggers.append("material_live_performance_if_triggered")

    transition_after_emit = "POST_DEADLINE_RECONCILIATION" if deadline_boundary else None
    post_deadline_reconciliation = bool(
        minutes_to_deadline is not None
        and minutes_to_deadline < 0
        and str(context.get("phase") or "") != "PRE_DEADLINE"
    )

    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "model": cfg.get("model_id"),
        "timezone": str(cfg.get("timezone") or "Asia/Jakarta"),
        "evaluated_at": current.astimezone(timezone.utc).isoformat(),
        "local_evaluated_at": now_local.isoformat(),
        "hourly_checkpoint": hourly_checkpoint,
        "official_deadline_time": deadline.astimezone(timezone.utc).isoformat() if deadline else None,
        "local_deadline_time": deadline_local.isoformat() if deadline_local else None,
        "minutes_to_deadline": round(minutes_to_deadline, 3) if minutes_to_deadline is not None else None,
        "deadline_day_active": inside_deadline_day,
        "final_review_target": final_target.isoformat() if final_target else None,
        "final_review_due": final_due,
        "deadline_boundary": deadline_boundary,
        "active_mode": active_mode,
        "candidate_modes": candidate_modes,
        "merged_lower_priority_modes": lower_priority,
        "visible_authorized": visible,
        "force_full_report": force_full,
        "report_payload": payload_path,
        "price_radar_required": price_radar_required,
        "no_material_change_text": deadline_cfg.get("no_material_change_text") if active_mode in {"DEADLINE_DAY", "DEADLINE_DAY_FINAL_REVIEW"} else None,
        "fresh_source_sweep_required": fresh_source_sweep,
        "source_statuses": source_statuses,
        "direct_official_refresh_required": bool(refresh_reasons),
        "direct_official_refresh_reasons": refresh_reasons,
        "direct_official_native_fact_authority": direct_cfg.get("native_fact_authority"),
        "record_runtime_divergence": bool(direct_cfg.get("record_runtime_divergence", True)),
        "match_mode_active": active_mode == "MATCH_MODE",
        "live_match_active": bool(live_match_active),
        "comparator_triggers": comparator_triggers,
        "post_deadline_reconciliation_required": post_deadline_reconciliation,
        "transition_after_emit": transition_after_emit,
        "silent_reason": None if visible else "NO_GOVERNED_VISIBLE_MODE_ACTIVE",
    }
