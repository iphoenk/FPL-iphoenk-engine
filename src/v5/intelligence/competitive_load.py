from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_competitive_load.json"


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _classify(rest_hours: float | None, minutes: float | None, extra_time: float, matches_7: int, matches_14: int) -> str:
    cfg = load_json_config(CONFIG)["classification"]
    if rest_hours is None:
        return "UNKNOWN"
    if extra_time > 0 and rest_hours < float(cfg["extra_time_high_risk_rest_hours"]):
        return "HIGH_ROTATION_RISK"
    if (minutes or 0) >= float(cfg["high_rotation_minutes"]) and rest_hours < float(cfg["high_rotation_rest_hours"]):
        return "HIGH_ROTATION_RISK"
    if rest_hours < float(cfg["congested_rest_hours"]) or matches_7 >= int(cfg["congested_matches_7d"]) or matches_14 >= int(cfg["congested_matches_14d"]):
        return "CONGESTED"
    if rest_hours >= float(cfg["rested_min_hours"]) and matches_7 <= 1:
        return "RESTED"
    return "NORMAL"


def build_competitive_load(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    *,
    planning_gw: int,
    match_stats: dict[str, Any] | None = None,
    verified_observations: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    team_fixtures: dict[int, list[dict[str, Any]]] = {}
    for row in fixtures:
        if not isinstance(row, dict):
            continue
        for key in ("team_h", "team_a"):
            if row.get(key) is not None:
                team_fixtures.setdefault(int(row[key]), []).append(row)
    for rows in team_fixtures.values():
        rows.sort(key=lambda x: str(x.get("kickoff_time") or ""))

    stats_payload = match_stats if isinstance(match_stats, dict) else {}
    stats_rows = stats_payload.get("rows") if isinstance(stats_payload.get("rows"), list) else []
    latest_stats: dict[int, dict[str, Any]] = {}
    for row in stats_rows:
        try:
            element = int(row.get("player_id"))
        except (TypeError, ValueError):
            continue
        latest_stats[element] = row

    obs_payload = verified_observations if isinstance(verified_observations, dict) else {}
    obs_rows: dict[int, list[dict[str, Any]]] = {}
    if obs_payload.get("contract") == "COMPETITIVE_LOAD_OBSERVATIONS_V1":
        for row in obs_payload.get("observations") or []:
            if not isinstance(row, dict) or row.get("verified") is not True:
                continue
            try:
                element = int(row.get("element"))
            except (TypeError, ValueError):
                continue
            obs_rows.setdefault(element, []).append(row)

    players: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for player in bootstrap.get("elements") or []:
        if not isinstance(player, dict) or player.get("id") is None or player.get("team") is None:
            continue
        element = int(player["id"]); team_id = int(player["team"])
        rows = team_fixtures.get(team_id, [])
        target = next((r for r in rows if int(r.get("event") or -1) == planning_gw), None)
        target_time = _dt((target or {}).get("kickoff_time"))
        past = [r for r in rows if _dt(r.get("kickoff_time")) and _dt(r.get("kickoff_time")) <= current_time]
        recent_times = [_dt(r.get("kickoff_time")) for r in past]
        recent_times = [t for t in recent_times if t is not None]
        stat = latest_stats.get(element) or {}
        native_last_time = max(recent_times, default=None)
        verified = [r for r in obs_rows.get(element, []) if _dt(r.get("match_time")) and _dt(r.get("match_time")) <= current_time]
        verified.sort(key=lambda x: _dt(x.get("match_time")) or datetime.min.replace(tzinfo=timezone.utc))
        external_last = verified[-1] if verified else None
        external_time = _dt((external_last or {}).get("match_time"))
        last_time = max([x for x in (native_last_time, external_time) if x is not None], default=None)
        rest_hours = round((target_time - last_time).total_seconds() / 3600.0, 2) if target_time and last_time else None
        minutes = _f((external_last or {}).get("minutes"), _f(stat.get("minutes_played"), 0.0)) if last_time else None
        extra_time = _f((external_last or {}).get("extra_time_minutes"), 0.0)
        matches_7 = sum(1 for t in recent_times if 0 <= (current_time - t).total_seconds() <= 7 * 86400)
        matches_14 = sum(1 for t in recent_times if 0 <= (current_time - t).total_seconds() <= 14 * 86400)
        for row in verified:
            t = _dt(row.get("match_time"))
            if t and 0 <= (current_time - t).total_seconds() <= 7 * 86400: matches_7 += 1
            if t and 0 <= (current_time - t).total_seconds() <= 14 * 86400: matches_14 += 1
        state = _classify(rest_hours, minutes, extra_time, matches_7, matches_14)
        counts[state] = counts.get(state, 0) + 1
        players[str(element)] = {
            "element": element,
            "team_id": team_id,
            "planning_gw": planning_gw,
            "next_pl_kickoff": (target or {}).get("kickoff_time"),
            "last_verified_competitive_match": last_time.isoformat() if last_time else None,
            "rest_hours": rest_hours,
            "last_match_minutes": minutes,
            "extra_time_minutes": extra_time,
            "matches_7d": matches_7,
            "matches_14d": matches_14,
            "state": state,
            "verified_non_pl_observation_count": len(verified),
            "non_pl_evidence_state": "AVAILABLE" if verified else "UNAVAILABLE",
            "international_evidence": any(bool(r.get("international")) for r in verified),
            "long_haul_evidence": any(bool(r.get("long_haul")) for r in verified),
            "travel_context": (external_last or {}).get("travel_context") if external_last else None,
        }
    return {
        "schema_version": 1,
        "contract": cfg["contract"],
        "owner": cfg["owner"],
        "generated_at": current_time.isoformat(),
        "status": "ACTIVE",
        "planning_gw": planning_gw,
        "players": players,
        "player_count": len(players),
        "state_counts": counts,
        "governance": cfg["governance"],
    }
