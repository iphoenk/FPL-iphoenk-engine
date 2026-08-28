from __future__ import annotations

from datetime import datetime
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/xmins_v3.json"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _official_events(fixtures: list[dict[str, Any]], team_id: int) -> list[dict[str, Any]]:
    rows = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        if team_id not in {int(fixture.get("team_h") or -1), int(fixture.get("team_a") or -1)}:
            continue
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        rows.append(
            {
                "kickoff": kickoff,
                "kickoff_time": kickoff.isoformat(),
                "competition_class": "PREMIER_LEAGUE",
                "source": "official_fpl_fixtures",
                "event": fixture.get("event"),
            }
        )
    return rows


def _external_events(schedule: dict[str, Any], team_id: int) -> list[dict[str, Any]]:
    rows = []
    fixtures = schedule.get("cross_competition_fixtures") if isinstance(schedule.get("cross_competition_fixtures"), list) else []
    for item in fixtures:
        if not isinstance(item, dict) or item.get("fpl_team_id") is None:
            continue
        if int(item.get("fpl_team_id")) != team_id:
            continue
        kickoff = _parse_dt(item.get("kickoff_time"))
        if kickoff is None:
            continue
        rows.append(
            {
                "kickoff": kickoff,
                "kickoff_time": kickoff.isoformat(),
                "competition_class": str(item.get("competition_class") or "OTHER"),
                "source": str(item.get("source") or "api_football"),
                "event": item.get("fixture_id"),
            }
        )
    return rows


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_kickoff: dict[str, dict[str, Any]] = {}
    for row in events:
        key = row["kickoff"].isoformat()
        existing = by_kickoff.get(key)
        if existing is None or row.get("source") == "official_fpl_fixtures":
            by_kickoff[key] = row
    return sorted(by_kickoff.values(), key=lambda row: row["kickoff"])


def fixture_rest_context(
    official_fixtures: list[dict[str, Any]],
    schedule: dict[str, Any],
    team_id: int,
    target_kickoff: Any,
) -> dict[str, Any]:
    target = _parse_dt(target_kickoff)
    if target is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "TARGET_KICKOFF_UNAVAILABLE",
            "team_id": team_id,
            "point_in_time_relative_to_fixture": True,
        }

    events = _dedupe_events(_official_events(official_fixtures, team_id) + _external_events(schedule, team_id))
    before = [row for row in events if row["kickoff"] < target]
    after = [row for row in events if row["kickoff"] > target]
    previous = before[-1] if before else None
    following = after[0] if after else None
    rest_before = (target - previous["kickoff"]).total_seconds() / 86400.0 if previous else None
    rest_after = (following["kickoff"] - target).total_seconds() / 86400.0 if following else None
    adjacent = [value for value in (rest_before, rest_after) if value is not None and value >= 0]
    if not adjacent:
        return {
            "status": "UNAVAILABLE",
            "reason": "NO_ADJACENT_FIXTURE_EVIDENCE",
            "team_id": team_id,
            "target_kickoff": target.isoformat(),
            "point_in_time_relative_to_fixture": True,
        }

    return {
        "status": "ACTIVE",
        "team_id": team_id,
        "target_kickoff": target.isoformat(),
        "rest_days_before": round(rest_before, 3) if rest_before is not None else None,
        "rest_days_after": round(rest_after, 3) if rest_after is not None else None,
        "minimum_adjacent_rest_days": round(min(adjacent), 3),
        "previous_event_class": previous.get("competition_class") if previous else None,
        "next_event_class": following.get("competition_class") if following else None,
        "previous_event_source": previous.get("source") if previous else None,
        "next_event_source": following.get("source") if following else None,
        "point_in_time_relative_to_fixture": True,
        "global_calendar_minimum_used": False,
    }


def resolve_fixture_congestion(
    official_fixtures: list[dict[str, Any]],
    schedule: dict[str, Any],
    team_id: int,
    target_kickoff: Any,
    rotation_risk: Any,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("fixture_congestion") or {}
    context = fixture_rest_context(official_fixtures, schedule, team_id, target_kickoff)
    enabled = bool(cfg.get("enabled", False))
    risk = max(0.0, min(1.0, _f(rotation_risk)))
    minimum_risk = max(0.0, min(1.0, _f(cfg.get("minimum_rotation_risk"), 0.05)))
    result = {
        "model": cfg.get("model"),
        "calibration_status": cfg.get("calibration_status"),
        "promotion_requires_settled_backtest": bool(cfg.get("promotion_requires_settled_backtest", True)),
        "enabled": enabled,
        "rotation_risk": round(risk, 4),
        "rest_context": context,
        "factor": 1.0,
        "severity": "NONE",
        "applied": False,
        "reason": None,
    }
    if not enabled:
        result["reason"] = "DISABLED_BY_CONFIG"
        return result
    if context.get("status") != "ACTIVE":
        result["reason"] = str(context.get("reason") or "REST_CONTEXT_UNAVAILABLE")
        return result
    if risk < minimum_risk:
        result["reason"] = "ROTATION_RISK_BELOW_THRESHOLD"
        return result

    thresholds = cfg.get("rest_thresholds_days") or {}
    weights = cfg.get("severity_weights") or {}
    rest_days = _f(context.get("minimum_adjacent_rest_days"), 99.0)
    severe_below = _f(thresholds.get("severe_below"), 2.5)
    elevated_below = max(severe_below, _f(thresholds.get("elevated_below"), 3.5))
    if rest_days < severe_below:
        severity = "SEVERE"
        severity_weight = max(0.0, _f(weights.get("severe"), 1.0))
    elif rest_days < elevated_below:
        severity = "ELEVATED"
        severity_weight = max(0.0, _f(weights.get("elevated"), 0.5))
    else:
        result["reason"] = "REST_ABOVE_CONGESTION_THRESHOLD"
        return result

    max_penalty = max(0.0, min(0.5, _f(cfg.get("max_role_weighted_start_penalty"), 0.08)))
    penalty = min(max_penalty, max_penalty * severity_weight * risk)
    result.update(
        {
            "factor": round(max(0.5, 1.0 - penalty), 6),
            "severity": severity,
            "applied": penalty > 0,
            "penalty": round(penalty, 6),
            "reason": "ROLE_WEIGHTED_FIXTURE_CONGESTION" if penalty > 0 else "ZERO_PENALTY",
        }
    )
    return result
