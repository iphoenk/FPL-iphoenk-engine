from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

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


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _valid_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _verification_rank(level: str, allowed: list[str]) -> int:
    try:
        return allowed.index(level)
    except ValueError:
        return len(allowed) + 1


def _validated_observations(
    bootstrap: dict[str, Any],
    payload: dict[str, Any] | None,
    *,
    now: datetime,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    cfg = load_json_config(CONFIG)
    validation = cfg.get("observation_validation") or {}
    expected_contract = str(validation.get("contract") or "COMPETITIVE_LOAD_OBSERVATIONS_V1")
    body = payload if isinstance(payload, dict) else {}
    raw_rows = body.get("observations") if isinstance(body.get("observations"), list) else []
    canonical_elements = {
        _i(row.get("id"))
        for row in bootstrap.get("elements") or []
        if isinstance(row, dict) and _i(row.get("id")) > 0
    }
    audit: dict[str, Any] = {
        "contract": expected_contract,
        "input_present": bool(body),
        "input_contract_valid": body.get("contract") == expected_contract if body else False,
        "input_rows": len(raw_rows),
        "accepted_rows": 0,
        "rejected_rows": 0,
        "stale_rows": 0,
        "deduplicated_rows": 0,
        "rejection_reasons": {},
        "verification_levels": {},
        "fail_soft": True,
    }
    if not body:
        audit["status"] = "NO_EXTERNAL_OBSERVATIONS"
        return {}, audit
    if body.get("contract") != expected_contract:
        audit["status"] = "INVALID_CONTRACT_REJECTED"
        audit["rejected_rows"] = len(raw_rows)
        audit["rejection_reasons"] = {"INVALID_CONTRACT": len(raw_rows)} if raw_rows else {}
        return {}, audit

    known_competitions = {str(value) for value in cfg.get("known_competitions") or []}
    allowed_levels = [str(value) for value in validation.get("allowed_verification_levels") or []]
    allowed_travel = {str(value) for value in validation.get("allowed_travel_contexts") or []}
    retention = timedelta(hours=_f(validation.get("retention_hours"), 504.0))
    future_tolerance = timedelta(minutes=_f(validation.get("future_tolerance_minutes"), 10.0))
    max_minutes = _f(validation.get("max_minutes"), 130.0)
    max_extra = _f(validation.get("max_extra_time_minutes"), 30.0)
    require_source_url = bool(validation.get("require_source_url", True))

    rejected: Counter[str] = Counter()
    stale = 0
    duplicate_count = 0
    candidates: dict[tuple[int, str, str], dict[str, Any]] = {}

    for raw in raw_rows:
        if not isinstance(raw, dict):
            rejected["ROW_NOT_OBJECT"] += 1
            continue
        if raw.get("verified") is not True:
            rejected["NOT_VERIFIED"] += 1
            continue
        element = _i(raw.get("element"))
        if element <= 0 or element not in canonical_elements:
            rejected["UNKNOWN_ELEMENT"] += 1
            continue
        competition = str(raw.get("competition") or "").strip()
        if competition not in known_competitions or competition == "Premier League":
            rejected["INVALID_OR_NATIVE_COMPETITION"] += 1
            continue
        match_time = _dt(raw.get("match_time"))
        if match_time is None:
            rejected["INVALID_MATCH_TIME"] += 1
            continue
        if match_time > now + future_tolerance:
            rejected["FUTURE_MATCH"] += 1
            continue
        if now - match_time > retention:
            stale += 1
            continue
        source = str(raw.get("source") or "").strip()
        source_url = str(raw.get("source_url") or "").strip()
        if not source:
            rejected["MISSING_SOURCE"] += 1
            continue
        if require_source_url and not _valid_http_url(source_url):
            rejected["INVALID_SOURCE_URL"] += 1
            continue
        level = str(raw.get("verification_level") or "").strip()
        if level not in allowed_levels:
            rejected["INVALID_VERIFICATION_LEVEL"] += 1
            continue
        started = raw.get("started")
        if not isinstance(started, bool):
            rejected["STARTED_NOT_BOOLEAN"] += 1
            continue
        minutes = _f(raw.get("minutes"), -1.0)
        extra_minutes = _f(raw.get("extra_time_minutes"), 0.0)
        if minutes < 0 or minutes > max_minutes:
            rejected["MINUTES_OUT_OF_RANGE"] += 1
            continue
        if extra_minutes < 0 or extra_minutes > max_extra or extra_minutes > minutes:
            rejected["EXTRA_TIME_OUT_OF_RANGE"] += 1
            continue
        if started and minutes <= 0:
            rejected["STARTED_WITH_ZERO_MINUTES"] += 1
            continue
        sub_on = raw.get("sub_on_minute")
        sub_off = raw.get("sub_off_minute")
        if sub_on not in {None, ""} and not (0 <= _f(sub_on, -1.0) <= max_minutes):
            rejected["SUB_ON_OUT_OF_RANGE"] += 1
            continue
        if sub_off not in {None, ""} and not (0 <= _f(sub_off, -1.0) <= max_minutes):
            rejected["SUB_OFF_OUT_OF_RANGE"] += 1
            continue
        travel_context = str(raw.get("travel_context") or "UNKNOWN")
        if travel_context not in allowed_travel:
            rejected["INVALID_TRAVEL_CONTEXT"] += 1
            continue

        item = {
            "element": element,
            "competition": competition,
            "match_time": match_time.isoformat().replace("+00:00", "Z"),
            "venue": raw.get("venue"),
            "started": started,
            "minutes": minutes,
            "sub_on_minute": _f(sub_on) if sub_on not in {None, ""} else None,
            "sub_off_minute": _f(sub_off) if sub_off not in {None, ""} else None,
            "extra_time_minutes": extra_minutes,
            "travel_context": travel_context,
            "international": competition == "International" or bool(raw.get("international")),
            "long_haul": bool(raw.get("long_haul")),
            "source": source,
            "source_url": source_url,
            "verification_level": level,
            "verified": True,
        }
        key = (element, competition, item["match_time"])
        prior = candidates.get(key)
        if prior is not None:
            duplicate_count += 1
            if _verification_rank(level, allowed_levels) >= _verification_rank(
                str(prior.get("verification_level")), allowed_levels
            ):
                continue
        candidates[key] = item

    out: dict[int, list[dict[str, Any]]] = {}
    level_counts: Counter[str] = Counter()
    for item in candidates.values():
        element = int(item["element"])
        clean = {key: value for key, value in item.items() if key != "element"}
        level_counts[str(clean.get("verification_level"))] += 1
        out.setdefault(element, []).append(clean)
    for rows in out.values():
        rows.sort(key=lambda row: _dt(row.get("match_time")) or datetime.min.replace(tzinfo=timezone.utc))

    accepted_count = sum(len(rows) for rows in out.values())
    audit.update(
        {
            "status": "VALIDATED" if accepted_count else "NO_VALID_EXTERNAL_ROWS",
            "accepted_rows": accepted_count,
            "rejected_rows": sum(rejected.values()),
            "stale_rows": stale,
            "deduplicated_rows": duplicate_count,
            "rejection_reasons": dict(sorted(rejected.items())),
            "verification_levels": dict(sorted(level_counts.items())),
        }
    )
    return out, audit


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

    obs_rows, observation_audit = _validated_observations(
        bootstrap,
        verified_observations,
        now=current_time,
    )

    players: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for player in bootstrap.get("elements") or []:
        if not isinstance(player, dict) or player.get("id") is None or player.get("team") is None:
            continue
        element = int(player["id"])
        team_id = int(player["team"])
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
            if t and 0 <= (current_time - t).total_seconds() <= 7 * 86400:
                matches_7 += 1
            if t and 0 <= (current_time - t).total_seconds() <= 14 * 86400:
                matches_14 += 1
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

    external_count = sum(len(rows) for rows in obs_rows.values())
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
        "external_observation_count": external_count,
        "external_player_coverage": len(obs_rows),
        "external_evidence_status": "AVAILABLE" if external_count else "PARTIAL_COMPETITION_COVERAGE",
        "observation_audit": observation_audit,
        "governance": cfg["governance"],
    }
