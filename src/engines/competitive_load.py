from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

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


def _valid_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


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


def _verification_rank(level: str, allowed: list[str]) -> int:
    try:
        return allowed.index(level)
    except ValueError:
        return len(allowed) + 1


def _validated_optional_observations(
    canonical_elements: set[int] | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    cfg = load_config()
    validation = cfg.get("observation_validation") or {}
    expected_contract = str(validation.get("contract") or "COMPETITIVE_LOAD_OBSERVATIONS_V1")
    payload = read_json(OBSERVATIONS, {})
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    audit: dict[str, Any] = {
        "contract": expected_contract,
        "input_present": bool(payload),
        "input_contract_valid": payload.get("contract") == expected_contract if payload else False,
        "input_rows": len(payload.get("observations") or []) if isinstance(payload, dict) else 0,
        "accepted_rows": 0,
        "rejected_rows": 0,
        "stale_rows": 0,
        "deduplicated_rows": 0,
        "rejection_reasons": {},
        "verification_levels": {},
        "fail_soft": True,
    }
    if not payload:
        audit["status"] = "NO_EXTERNAL_OBSERVATIONS"
        return {}, audit
    if payload.get("contract") != expected_contract:
        audit["status"] = "INVALID_CONTRACT_REJECTED"
        audit["rejected_rows"] = audit["input_rows"]
        audit["rejection_reasons"] = {"INVALID_CONTRACT": audit["input_rows"]}
        return {}, audit

    known_competitions = set(str(value) for value in cfg.get("known_competitions") or [])
    allowed_levels = [str(value) for value in validation.get("allowed_verification_levels") or []]
    allowed_travel = set(str(value) for value in validation.get("allowed_travel_contexts") or [])
    retention = timedelta(hours=_f(validation.get("retention_hours"), 504.0))
    future_tolerance = timedelta(minutes=_f(validation.get("future_tolerance_minutes"), 10.0))
    max_minutes = _f(validation.get("max_minutes"), 130.0)
    max_extra = _f(validation.get("max_extra_time_minutes"), 30.0)
    require_source_url = bool(validation.get("require_source_url", True))

    rejected = Counter()
    stale = 0
    candidates: dict[tuple[int, str, str], dict[str, Any]] = {}
    duplicate_count = 0

    for raw in payload.get("observations") or []:
        if not isinstance(raw, dict):
            rejected["ROW_NOT_OBJECT"] += 1
            continue
        if raw.get("verified") is not True:
            rejected["NOT_VERIFIED"] += 1
            continue
        element = _i(raw.get("element"))
        if element <= 0 or (canonical_elements is not None and element not in canonical_elements):
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

        international = competition == "International" or bool(raw.get("international"))
        long_haul = bool(raw.get("long_haul"))
        item = {
            "competition": competition,
            "match_time": match_time.isoformat().replace("+00:00", "Z"),
            "venue": raw.get("venue"),
            "started": started,
            "minutes": minutes,
            "sub_on_minute": _f(sub_on) if sub_on not in {None, ""} else None,
            "sub_off_minute": _f(sub_off) if sub_off not in {None, ""} else None,
            "extra_time_minutes": extra_minutes,
            "travel_context": travel_context,
            "international": international,
            "long_haul": long_haul,
            "source": source,
            "source_url": source_url,
            "verification_level": level,
            "verified": True,
        }
        key = (element, competition, item["match_time"])
        prior = candidates.get(key)
        if prior is not None:
            duplicate_count += 1
            if _verification_rank(level, allowed_levels) >= _verification_rank(str(prior.get("verification_level")), allowed_levels):
                continue
        candidates[key] = item | {"element": element}

    out: dict[int, list[dict[str, Any]]] = {}
    level_counts = Counter()
    for item in candidates.values():
        element = int(item.pop("element"))
        level_counts[str(item.get("verification_level"))] += 1
        out.setdefault(element, []).append(item)
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
    now = datetime.now(timezone.utc)
    extra, observation_audit = _validated_optional_observations(set(players), now=now)
    player_rows: dict[str, Any] = {}

    for element, identity in players.items():
        team_id = identity["team_id"]
        team_fixtures = fixtures_by_team.get(team_id, [])
        source_fixture = _pl_fixture_for_gw(team_fixtures, source_gw)
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
                "source_url": None,
                "verification_level": "PREMIER_LEAGUE_OR_OFFICIAL_FPL",
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

        state = _state(
            rest_hours,
            _f((last or {}).get("minutes"), 0.0) if last else None,
            _f((last or {}).get("extra_time_minutes"), 0.0),
            matches_7,
            matches_14,
        )
        non_pl_available = any(row.get("competition") != "Premier League" for row in verified)
        international_available = any(row.get("international") for row in verified)
        long_haul_available = any(row.get("long_haul") for row in verified)
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
                "international_coverage": "AVAILABLE" if international_available else "UNAVAILABLE",
                "long_haul_coverage": "AVAILABLE" if long_haul_available else "UNAVAILABLE",
                "coach_rotation_tendency": "UNAVAILABLE",
                "travel_distance": "UNAVAILABLE",
            },
            "confidence": "MEDIUM" if last and rest_hours is not None else "LOW",
            "advisory_only": True,
        }

    counts = {
        state: sum(1 for row in player_rows.values() if row.get("state") == state)
        for state in cfg.get("states") or []
    }
    external_players = sum(
        1 for row in player_rows.values() if row.get("competition_coverage") == "PL_PLUS_VERIFIED_EXTERNAL"
    )
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
        "external_observation_count": int(observation_audit.get("accepted_rows") or 0),
        "external_player_coverage": external_players,
        "observation_audit": observation_audit,
        "governance": cfg.get("governance"),
    }


def run() -> dict[str, Any]:
    result = build()
    atomic_json(OUT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
