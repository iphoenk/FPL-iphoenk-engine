from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.utils import ROOT, atomic_json, iso_now, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "weather_context.json"
OUT_NAME = "fixture_weather.json"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_venues() -> dict[str, Any]:
    cfg = load_config()
    path = ROOT / str(cfg["venue_registry"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _venue_map() -> dict[str, dict[str, Any]]:
    registry = load_venues()
    default_tz = str(registry.get("default_timezone") or "Europe/London")
    return {
        str(row["team_name"]): {**row, "timezone": str(row.get("timezone") or default_tz)}
        for row in registry.get("venues") or []
        if row.get("team_name")
    }


def _severity(weather: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, list[str]]:
    def triggered(level: dict[str, Any]) -> list[str]:
        out: list[str] = []
        wind = float(weather.get("wind_speed_kmh") or 0.0)
        gust = float(weather.get("wind_gust_kmh") or 0.0)
        precip = float(weather.get("precipitation_mm_h") or 0.0)
        temp = weather.get("temperature_c")
        if wind >= float(level.get("wind_speed_kmh") or 1e9):
            out.append("wind_speed")
        if gust >= float(level.get("wind_gust_kmh") or 1e9):
            out.append("wind_gust")
        if precip >= float(level.get("precipitation_mm_h") or 1e9):
            out.append("precipitation_intensity")
        if temp is not None and float(temp) <= float(level.get("cold_c") if level.get("cold_c") is not None else -1e9):
            out.append("cold")
        if temp is not None and float(temp) >= float(level.get("heat_c") if level.get("heat_c") is not None else 1e9):
            out.append("heat")
        return out

    bands = cfg.get("severity") or {}
    for label in ("EXTREME", "ADVERSE", "NOTABLE"):
        signals = triggered(bands.get(label) or {})
        if signals:
            return label, signals
    return "NORMAL", []


def _forecast_confidence(days_to_kickoff: float, cfg: dict[str, Any]) -> str:
    mapping = ((cfg.get("forecast_policy") or {}).get("confidence_by_horizon_days") or {})
    bucket = max(0, min(int(days_to_kickoff), max([int(k) for k in mapping] or [0])))
    return str(mapping.get(str(bucket)) or "LOW")


def _weather_for_kickoff(venue: dict[str, Any], kickoff: datetime, cfg: dict[str, Any]) -> dict[str, Any]:
    api = cfg.get("api") or {}
    tz_name = str(venue.get("timezone") or "Europe/London")
    local = kickoff.astimezone(ZoneInfo(tz_name))
    fields = [str(x) for x in api.get("hourly_fields") or []]
    params = {
        "latitude": float(venue["latitude"]),
        "longitude": float(venue["longitude"]),
        "hourly": ",".join(fields),
        "timezone": tz_name,
        "start_date": local.date().isoformat(),
        "end_date": local.date().isoformat(),
    }
    response = requests.get(
        str(api["forecast_url"]),
        params=params,
        timeout=float(api.get("request_timeout_seconds") or 10),
    )
    response.raise_for_status()
    hourly = (response.json() or {}).get("hourly") or {}
    times = list(hourly.get("time") or [])
    target = local.strftime("%Y-%m-%dT%H:00")
    if target not in times:
        raise ValueError("kickoff hour unavailable in weather response")
    idx = times.index(target)

    def value(name: str):
        values = hourly.get(name) or []
        return values[idx] if idx < len(values) else None

    weather = {
        "temperature_c": value("temperature_2m"),
        "precipitation_probability_pct": value("precipitation_probability"),
        "precipitation_mm_h": value("precipitation"),
        "wind_speed_kmh": value("wind_speed_10m"),
        "wind_gust_kmh": value("wind_gusts_10m"),
        "weather_code": value("weather_code"),
    }
    severity, signals = _severity(weather, cfg)
    fetched_at = iso_now()
    days_to = max(0.0, (kickoff - datetime.now(timezone.utc)).total_seconds() / 86400.0)
    return {
        "fetched_at": fetched_at,
        "provider": "open_meteo",
        "forecast_for": kickoff.isoformat(),
        "forecast_local_hour": target,
        "forecast_confidence": _forecast_confidence(days_to, cfg),
        "severity": severity,
        "signals": signals,
        "weather": weather,
        "provenance": {
            "source": "Open-Meteo",
            "endpoint": str(api["forecast_url"]),
            "venue": venue.get("venue"),
            "latitude": venue.get("latitude"),
            "longitude": venue.get("longitude"),
            "timezone": tz_name,
        },
    }


def _closest_to_kickoff(observations: list[dict[str, Any]], kickoff: datetime) -> dict[str, Any] | None:
    candidates = []
    for row in observations:
        fetched = _parse_dt(row.get("fetched_at"))
        if fetched is None:
            continue
        candidates.append((abs((kickoff - fetched).total_seconds()), fetched, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return dict(candidates[0][2])


def collect_weather_context(data_dir: Path) -> dict[str, Any]:
    cfg = load_config()
    governance = dict(cfg.get("governance") or {})
    forecast_policy = cfg.get("forecast_policy") or {}
    max_days = float(forecast_policy.get("max_horizon_days") or 7)
    keep = max(1, int(forecast_policy.get("retain_observations_per_fixture") or 8))
    post_hours = float(forecast_policy.get("post_match_retention_hours") or 48)
    official = read_json(data_dir / "official_snapshot.json", {})
    previous = read_json(data_dir / OUT_NAME, {"fixtures": []})
    prior_by_id = {str(row.get("fixture_id")): row for row in previous.get("fixtures") or []}
    bootstrap = official.get("bootstrap") or {}
    teams = {int(row["id"]): str(row.get("name")) for row in bootstrap.get("teams") or [] if row.get("id") is not None}
    venues = _venue_map()
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []

    for fixture in official.get("fixtures") or []:
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        age_hours = (now - kickoff).total_seconds() / 3600.0
        days_to = (kickoff - now).total_seconds() / 86400.0
        if days_to > max_days or age_hours > post_hours:
            continue
        fixture_id = str(fixture.get("id"))
        home = teams.get(int(fixture.get("team_h") or -1), "Unknown")
        away = teams.get(int(fixture.get("team_a") or -1), "Unknown")
        venue = venues.get(home)
        prior = prior_by_id.get(fixture_id) or {}
        observations = [dict(x) for x in prior.get("observations") or [] if isinstance(x, dict)]
        fetch_status = "NOT_ATTEMPTED"
        error = None
        if venue is None:
            fetch_status = "VENUE_UNKNOWN"
        elif kickoff >= now:
            try:
                observation = _weather_for_kickoff(venue, kickoff, cfg)
                observations.append(observation)
                fetch_status = "AVAILABLE"
            except Exception as exc:
                fetch_status = "UNAVAILABLE"
                error = f"{type(exc).__name__}: {exc}"
        else:
            fetch_status = "HISTORICAL_FROM_RETAINED_OBSERVATION"

        observations.sort(key=lambda row: str(row.get("fetched_at") or ""))
        observations = observations[-keep:]
        closest = _closest_to_kickoff(observations, kickoff)
        current = observations[-1] if observations else None
        rows.append({
            "fixture_id": int(fixture.get("id") or 0),
            "event": fixture.get("event"),
            "home_team": home,
            "away_team": away,
            "kickoff_time": kickoff.isoformat(),
            "started": bool(fixture.get("started")),
            "finished": bool(fixture.get("finished")),
            "venue": (venue or {}).get("venue"),
            "fetch_status": fetch_status,
            "error": error,
            "current": current,
            "closest_to_kickoff": closest,
            "post_match_attribution_ready": bool((fixture.get("started") or fixture.get("finished")) and closest),
            "observations": observations,
        })

    material = [
        row for row in rows
        if ((row.get("current") or {}).get("severity") in {"NOTABLE", "ADVERSE", "EXTREME"})
    ]
    payload = {
        "schema_version": 1,
        "model": cfg.get("model_id"),
        "generated_at": iso_now(),
        "provider": "open_meteo",
        "fixture_count": len(rows),
        "available_count": sum(1 for row in rows if row.get("current")),
        "material_count": len(material),
        "fixtures": rows,
        "material_fixtures": [
            {
                "fixture_id": row.get("fixture_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "kickoff_time": row.get("kickoff_time"),
                "severity": (row.get("current") or {}).get("severity"),
                "signals": (row.get("current") or {}).get("signals") or [],
                "weather": (row.get("current") or {}).get("weather") or {},
                "forecast_confidence": (row.get("current") or {}).get("forecast_confidence"),
            }
            for row in material
        ],
        "governance": governance,
    }
    atomic_json(data_dir / OUT_NAME, payload)
    return payload
