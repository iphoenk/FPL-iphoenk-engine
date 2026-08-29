from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

CONFIG = ROOT / "config" / "intelligence" / "competitive_load.json"
OBSERVATIONS = DATA / "competitive_load_observations.json"
OUT = DATA / "recent_competitive_load.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


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


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


def _team_fixture_rows(official: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    for fixture in official.get("fixtures") or []:
        home = _i(fixture.get("team_h"))
        away = _i(fixture.get("team_a"))
        if home > 0:
            rows.setdefault(home, []).append(fixture)
        if away > 0:
            rows.setdefault(away, []).append(fixture)
    for values in rows.values():
        values.sort(key=lambda row: str(row.get("kickoff_time") or ""))
    return rows


def _player_team_map(official: dict[str, Any]) -> dict[int, dict[str, Any]]:
    bootstrap = official.get("bootstrap") or {}
    team_names = {
        _i(row.get("id")): str(row.get("name") or row.get("short_name") or row.get("id"))
        for row in bootstrap.get("teams") or []
    }
    return {
        _i(row.get("id")): {
            "element": _i(row.get("id")),
            "name": str(row.get("web_name") or row.get("second_name") or row.get("id")),
            "team_id": _i(row.get("team")),
            "team_name": team_names.get(_i(row.get("team"))),
        }
        for row in bootstrap.get("elements") or []
        if _i(row.get("id")) > 0
    }


def _matchstats_map() -> tuple[int | None, dict[int, dict[str, Any]]]:
    payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    gw = _i(payload.get("gw"), 0) or None
    rows: dict[int, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        element = _i(row.get("player_id"))
        if element <= 0:
            continue
        minutes = _f(row.get("minutes_played"))
        start_min = row.get("start_min")
        finish_min = row.get("finish_min")
        rows[element] = {
            "match_id": row.get("match_id"),
            "minutes": minutes,
            "started": minutes > 0 and (_f(start_min, 0.0) <= 1.0),
            "sub_on_minute": _f(start_min) if start_min not in {None, ""} and _f(start_min) > 1 else None,
            "sub_off_minute": _f(finish_min) if finish_min not in {None, ""} and _f(finish_min) < 90 else None,
            "extra_time_minutes": max(0.0, minutes - 90.0),
            "source": payload.get("source_id") or payload.get("source"),
            "source_gw": gw,
        }
    return gw, rows


def _optional_observations() -> dict[int, list[dict[str, Any]]]:
    payload = read_json(OBSERVATIONS, {})
    if payload.get("contract") != "COMPETITIVE_LOAD_OBSERVATIONS_V1":
        return {}
    out: dict[int, list[dict[str, Any]]] = {}
    for row in payload.get("observations") or []:
        if row.get("verified") is not True:
            continue
        element = _i(row.get("element"))
        if element <= 0:
            continue
        item = {
            "competition": row.get("competition"),
            "match_time": row.get("match_time"),
            "venue": row.get("venue"),
            "started": row.get("started"),
            "minutes": row.get("minutes"),
            "sub_on_minute": row.get("sub_on_minute"),
            "sub_off_minute": row.get("sub_off_minute"),
            "extra_time_minutes": row.get("extra_time_minutes") or 0,
            "travel_context": row.get("travel_context"),
            "international": bool(row.get("international")),
            "long_haul": bool(row.get("long_haul")),
            "source": row.get("source"),
            "verified": True,
        }
        out.setdefault(element, []).append(item)
    return out


def _state(rest_hours: float | None, minutes: float | None, extra_time: float, matches_7: int, matches_14: int) -> str:
    cfg = load_config().get("classification") or {}
    if rest_hours is None:
        return "UNKNOWN"
    if extra_time > 0 and rest_hours < _f(cfg.get("extra_time_high_risk_rest_hours"), 96):
        return "HIGH_ROTATION_RISK"
    if (minutes or 0) >= _f(cfg.get("high_rotation_minutes"), 80) and rest_hours < _f(cfg.get("high_rotation_rest_hours"), 72):
        return "HIGH_ROTATION_RISK"
    if rest_hours < _f(cfg.get("congested_rest_hours"), 72) or matches_7 >= _i(cfg.get("congested_matches_7d"), 2) or matches_14 >= _i(cfg.get("congested_matches_14d"), 4):
        return "CONGESTED"
    if rest_hours >= _f(cfg.get("rested_min_hours"), 144) and matches_7 <= 1:
        return "RESTED"
    return "NORMAL"


def _pl_fixture_for_gw(fixtures: list[dict[str, Any]], gw: int | None) -> dict[str, Any] | None:
    if gw is None:
        return None
    return next((row for row in fixtures if _i(row.get("event"), 0) == gw), None)


def _next_fixture(fixtures: list[dict[str, Any]], after: datetime | None) -> dict[str, Any] | None:
    if not after:
        return None
    future = [row for row in fixtures if (_dt(row.get("kickoff_time")) or after) > after]
    return min(future, key=lambda row: _dt(row.get("kickoff_time")) or datetime.max.replace(tzinfo=timezone.utc), default=None)


def _counts(fixtures: list[dict[str, Any]], anchor: datetime | None) -> tuple[int, int]:
    if not anchor:
        return 0, 0
    seven = fourteen = 0
    for fixture in fixtures:
        kickoff = _dt(fixture.get("kickoff_time"))
        if not kickoff or kickoff > anchor:
            continue
        age_h = (anchor - kickoff).total_seconds() / 3600.0
        if age_h <= 7 * 24:
            seven += 1
        if age_h <= 14 * 24:
            fourteen += 1
    return seven, fourteen


def build() -> dict[str, Any]:
    cfg = load_config()
    official = read_json(DATA / "official_snapshot.json", {})
    players = _player_team_map(official)
    fixtures_by_team = _team_fixture_rows(official)
    source_gw, matchstats = _matchstats_map()
    extra = _optional_observations()
    now = datetime.now(timezone.utc)
    player_rows: dict[str, Any] = {}

    for element, identity in players.items():
        team_id = identity["team_id"]
        team_fixtures = fixtures_by_team.get(team_id, [])
        source_fixture = _pl_fixture_for_gw(team_fixtures, source_gw)
        source_time = _dt((source_fixture or {}).get("kickoff_time"))
        stat = matchstats.get(element) or {}
        native_match = None
        if source_fixture and stat:
            home = _i(source_fixture.get("team_h")) == team_id
            native_match = {
                "competition": "Premier League",
                "match_time": source_fixture.get("kickoff_time"),
                "venue": "HOME" if home else "AWAY",
                "started": stat.get("started"),
                "minutes": stat.get("minutes"),
                "sub_on_minute": stat.get("sub_on_minute"),
                "sub_off_minute": stat.get("sub_off_minute"),
                "extra_time_minutes": 0.0,
                "travel_context": "HOME" if home else "DOMESTIC_AWAY",
                "international": False,
                "long_haul": False,
                "source": stat.get("source"),
                "verified": True,
            }

        verified = ([native_match] if native_match else []) + list(extra.get(element) or [])
        verified = [row for row in verified if _dt(row.get("match_time")) and _dt(row.get("match_time")) <= now]
        verified.sort(key=lambda row: _dt(row.get("match_time")) or datetime.min.replace(tzinfo=timezone.utc))
        last = verified[-1] if verified else None
        last_time = _dt((last or {}).get("match_time"))
        next_pl = _next_fixture(team_fixtures, last_time or now)
        next_time = _dt((next_pl or {}).get("kickoff_time"))
        rest_hours = _hours(last_time, next_time)
        matches_7, matches_14 = _counts(team_fixtures, now)
        for row in verified:
            when = _dt(row.get("match_time"))
            if not when or row.get("competition") == "Premier League":
                continue
            age_h = (now - when).total_seconds() / 3600.0
            matches_7 += int(age_h <= 7 * 24)
            matches_14 += int(age_h <= 14 * 24)

        state = _state(rest_hours, _f((last or {}).get("minutes"), 0.0) if last else None, _f((last or {}).get("extra_time_minutes"), 0.0), matches_7, matches_14)
        non_pl_available = any(row.get("competition") != "Premier League" for row in verified)
        player_rows[str(element)] = {
            **identity,
            "state": state,
            "last_competitive_match": last,
            "next_known_pl_fixture": {
                "kickoff_time": (next_pl or {}).get("kickoff_time"),
                "venue": "HOME" if next_pl and _i(next_pl.get("team_h")) == team_id else ("AWAY" if next_pl else None),
            },
            "rest_hours_to_next_known_pl_fixture": rest_hours,
            "matches_in_7_days": matches_7,
            "matches_in_14_days": matches_14,
            "competition_coverage": "PL_PLUS_VERIFIED_EXTERNAL" if non_pl_available else "PL_ONLY_PARTIAL",
            "evidence": {
                "pl_fixture_source": "OFFICIAL_FPL_FIXTURES",
                "player_minutes_source": stat.get("source") if stat else None,
                "non_pl_observations_available": non_pl_available,
                "international_coverage": "AVAILABLE" if any(row.get("international") for row in verified) else "UNAVAILABLE",
                "long_haul_coverage": "AVAILABLE" if any(row.get("long_haul") for row in verified) else "UNAVAILABLE",
                "coach_rotation_tendency": "UNAVAILABLE",
                "travel_distance": "UNAVAILABLE",
            },
            "confidence": "MEDIUM" if last and rest_hours is not None else "LOW",
            "advisory_only": True,
        }

    counts = {state: sum(1 for row in player_rows.values() if row.get("state") == state) for state in cfg.get("states") or []}
    return {
        "schema_version": 1,
        "contract": "COMPETITIVE_LOAD_PRIMITIVE_V1",
        "generated_at": iso_now(),
        "owner": cfg.get("owner"),
        "status": "PARTIAL_COMPETITION_COVERAGE",
        "source_gw": source_gw,
        "players": player_rows,
        "player_count": len(player_rows),
        "state_counts": counts,
        "governance": cfg.get("governance"),
    }


def run() -> dict[str, Any]:
    result = build()
    atomic_json(OUT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
