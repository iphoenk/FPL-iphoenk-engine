from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _provider_dt(value: Any, tz_name: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_venues() -> dict[str, Any]:
    cfg = load_config()
    path = ROOT / str(cfg["venue_registry"])
    return json.loads(path.read_text(encoding="utf-8"))


def _venue_maps() -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    registry = load_venues()
    default_tz = str(registry.get("default_timezone") or "Europe/London")
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for raw in registry.get("venues") or []:
        row = {**raw, "timezone": str(raw.get("timezone") or default_tz)}
        if row.get("team_id") is not None:
            by_id[int(row["team_id"])] = row
        if row.get("team_name"):
            by_name[str(row["team_name"])] = row
    return by_id, by_name


def _resolve_venue(
    team_id: int,
    team_name: str,
    by_id: dict[int, dict[str, Any]],
    by_name: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve venue only when registry identity agrees with current Official identity."""
    row = by_id.get(int(team_id))
    if row is not None:
        if str(row.get("team_name") or "") != str(team_name):
            return None, "VENUE_IDENTITY_MISMATCH"
        return row, None
    row = by_name.get(str(team_name))
    if row is not None and int(row.get("team_id") or -1) == int(team_id):
        return row, None
    return None, "VENUE_UNKNOWN"


def _severity(weather: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify observed intensity, wind and temperature. Probability is never intensity."""

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


def _freshness_hours(kickoff: datetime, now: datetime, cfg: dict[str, Any]) -> float:
    policy = cfg.get("forecast_policy") or {}
    days_to = max(0.0, (kickoff - now).total_seconds() / 86400.0)
    confidence = _forecast_confidence(days_to, cfg)
    mapping = policy.get("freshness_hours") or {}
    return max(0.0, float(mapping.get(confidence) or 0.0))


def _observation_is_fresh(
    observation: dict[str, Any] | None,
    kickoff: datetime,
    now: datetime,
    cfg: dict[str, Any],
) -> bool:
    if not observation or _evidence_kind(observation) != "FORECAST":
        return False
    fetched = _parse_dt(observation.get("fetched_at"))
    forecast_for = _parse_dt(observation.get("forecast_for"))
    if fetched is None or forecast_for is None:
        return False
    if abs((forecast_for - kickoff).total_seconds()) > 60:
        return False
    age_hours = max(0.0, (now - fetched).total_seconds() / 3600.0)
    return age_hours <= _freshness_hours(kickoff, now, cfg)


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
        "evidence_kind": "FORECAST",
        "fetched_at": fetched_at,
        "provider": "open_meteo",
        "forecast_for": kickoff.isoformat(),
        "forecast_issued_at": fetched_at,
        "evidence_timestamp": kickoff.isoformat(),
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
            "evidence_class": "ENVIRONMENTAL_CONTEXT",
        },
    }


def _weather_live_observed(venue: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    api = cfg.get("api") or {}
    tz_name = str(venue.get("timezone") or "Europe/London")
    fields = [str(x) for x in api.get("current_fields") or []]
    params = {
        "latitude": float(venue["latitude"]),
        "longitude": float(venue["longitude"]),
        "current": ",".join(fields),
        "timezone": tz_name,
    }
    response = requests.get(
        str(api["forecast_url"]),
        params=params,
        timeout=float(api.get("request_timeout_seconds") or 10),
    )
    response.raise_for_status()
    current = (response.json() or {}).get("current") or {}
    observed_at = _provider_dt(current.get("time"), tz_name)
    if observed_at is None:
        raise ValueError("current observation timestamp unavailable in weather response")
    weather = {
        "temperature_c": current.get("temperature_2m"),
        "precipitation_probability_pct": None,
        "precipitation_mm_h": current.get("precipitation"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "wind_gust_kmh": current.get("wind_gusts_10m"),
        "weather_code": current.get("weather_code"),
    }
    severity, signals = _severity(weather, cfg)
    return {
        "evidence_kind": "LIVE_OBSERVED",
        "fetched_at": iso_now(),
        "provider": "open_meteo",
        "observed_at": observed_at.isoformat(),
        "evidence_timestamp": observed_at.isoformat(),
        "forecast_for": None,
        "forecast_confidence": None,
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
            "evidence_class": "ENVIRONMENTAL_CONTEXT",
            "observation_mode": "CURRENT",
        },
    }


def _evidence_kind(row: dict[str, Any]) -> str:
    kind = str(row.get("evidence_kind") or "").upper()
    if kind in {"FORECAST", "LIVE_OBSERVED"}:
        return kind
    if row.get("observed_at"):
        return "LIVE_OBSERVED"
    return "FORECAST"


def _closest_to_kickoff(observations: list[dict[str, Any]], kickoff: datetime) -> dict[str, Any] | None:
    candidates: list[tuple[float, datetime, dict[str, Any]]] = []
    for row in observations:
        if _evidence_kind(row) != "LIVE_OBSERVED":
            continue
        observed = _parse_dt(row.get("observed_at") or row.get("evidence_timestamp") or row.get("fetched_at"))
        if observed is None:
            continue
        candidates.append((abs((kickoff - observed).total_seconds()), observed, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return dict(candidates[0][2])


def _latest_of_kind(observations: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    rows = [row for row in observations if _evidence_kind(row) == kind]
    if not rows:
        return None
    rows.sort(key=lambda row: str(row.get("observed_at") or row.get("fetched_at") or ""))
    return dict(rows[-1])


def _select_evidence(
    observations: list[dict[str, Any]],
    kickoff: datetime,
    now: datetime,
    cfg: dict[str, Any],
    *,
    started: bool,
    finished: bool,
) -> tuple[dict[str, Any] | None, str, str, str]:
    """Apply governed precedence without converting forecast probability into intensity."""
    latest_live = _latest_of_kind(observations, "LIVE_OBSERVED")
    closest = _closest_to_kickoff(observations, kickoff)
    forecasts = [row for row in observations if _evidence_kind(row) == "FORECAST"]
    forecasts.sort(key=lambda row: str(row.get("fetched_at") or ""))
    fresh = [row for row in forecasts if _observation_is_fresh(row, kickoff, now, cfg)]

    selected: dict[str, Any] | None = None
    precedence = "UNAVAILABLE"
    freshness = "UNAVAILABLE"
    if started and not finished and latest_live is not None:
        selected = latest_live
        precedence = "LIVE_OBSERVED"
        freshness = "OBSERVED"
    elif closest is not None:
        selected = closest
        precedence = "CLOSEST_TO_KICKOFF_OBSERVATION"
        freshness = "OBSERVED"
    elif fresh:
        selected = dict(fresh[-1])
        precedence = "FRESH_FORECAST"
        freshness = "FRESH"
    elif forecasts:
        selected = dict(forecasts[-1])
        precedence = "STALE_FORECAST"
        freshness = "STALE"

    if finished:
        evidence_state = "POST_MATCH_RECONCILED"
    elif precedence == "LIVE_OBSERVED":
        evidence_state = "LIVE_OBSERVED"
    elif precedence == "CLOSEST_TO_KICKOFF_OBSERVATION":
        evidence_state = "CLOSEST_TO_KICKOFF"
    else:
        evidence_state = "FORECAST"
    return selected, precedence, evidence_state, freshness


def _finalize_row(row: dict[str, Any], keep: int, now: datetime, cfg: dict[str, Any]) -> dict[str, Any]:
    observations = [dict(x) for x in row.pop("_observations", []) if isinstance(x, dict)]
    observations.sort(key=lambda item: str(item.get("fetched_at") or ""))
    observations = observations[-keep:]
    kickoff = row.pop("_kickoff")
    selected, precedence, evidence_state, freshness = _select_evidence(
        observations,
        kickoff,
        now,
        cfg,
        started=bool(row.get("started")),
        finished=bool(row.get("finished")),
    )
    row["current"] = selected
    row["selected_evidence"] = selected
    row["evidence_precedence"] = precedence
    row["evidence_state"] = evidence_state
    row["freshness"] = freshness
    row["latest_forecast"] = _latest_of_kind(observations, "FORECAST")
    row["live_observed"] = _latest_of_kind(observations, "LIVE_OBSERVED")
    row["closest_to_kickoff"] = _closest_to_kickoff(observations, kickoff)
    row["post_match_attribution_ready"] = bool(
        row.get("finished") and selected is not None
    )
    row["observations"] = observations
    return row


def collect_weather_context(data_dir: Path) -> dict[str, Any]:
    started_clock = time.perf_counter()
    cfg = load_config()
    governance = dict(cfg.get("governance") or {})
    forecast_policy = cfg.get("forecast_policy") or {}
    api = cfg.get("api") or {}
    max_days = float(forecast_policy.get("max_horizon_days") or 7)
    keep = max(1, int(forecast_policy.get("retain_observations_per_fixture") or 12))
    post_hours = float(forecast_policy.get("post_match_retention_hours") or 48)
    max_workers = max(1, min(8, int(api.get("max_parallel_requests") or 4)))
    official = read_json(data_dir / "official_snapshot.json", {})
    previous = read_json(data_dir / OUT_NAME, {"fixtures": []})
    prior_by_id = {str(row.get("fixture_id")): row for row in previous.get("fixtures") or []}
    bootstrap = official.get("bootstrap") or {}
    teams = {
        int(row["id"]): str(row.get("name"))
        for row in bootstrap.get("teams") or []
        if row.get("id") is not None
    }
    venues_by_id, venues_by_name = _venue_maps()
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    pending: list[tuple[int, str, dict[str, Any], datetime]] = []
    reused_fresh = 0

    for fixture in official.get("fixtures") or []:
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        age_hours = (now - kickoff).total_seconds() / 3600.0
        days_to = (kickoff - now).total_seconds() / 86400.0
        if days_to > max_days or age_hours > post_hours:
            continue
        fixture_id = str(fixture.get("id"))
        home_id = int(fixture.get("team_h") or -1)
        away_id = int(fixture.get("team_a") or -1)
        home = teams.get(home_id, "Unknown")
        away = teams.get(away_id, "Unknown")
        venue, venue_error = _resolve_venue(home_id, home, venues_by_id, venues_by_name)
        prior = prior_by_id.get(fixture_id) or {}
        observations = [dict(x) for x in prior.get("observations") or [] if isinstance(x, dict)]
        latest_forecast = _latest_of_kind(observations, "FORECAST")
        fixture_started = bool(fixture.get("started"))
        fixture_finished = bool(fixture.get("finished"))
        fetch_status = "NOT_ATTEMPTED"
        error = None

        if venue is None:
            fetch_status = venue_error or "VENUE_UNKNOWN"
        elif fixture_started and not fixture_finished:
            fetch_status = "PENDING_LIVE_OBSERVATION"
        elif fixture_finished or kickoff < now:
            fetch_status = "HISTORICAL_FROM_RETAINED_EVIDENCE"
        elif _observation_is_fresh(latest_forecast, kickoff, now, cfg):
            fetch_status = "REUSED_FRESH_FORECAST"
            reused_fresh += 1
        else:
            fetch_status = "PENDING_FORECAST_REFRESH"

        row = {
            "fixture_id": int(fixture.get("id") or 0),
            "event": fixture.get("event"),
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team": home,
            "away_team": away,
            "kickoff_time": kickoff.isoformat(),
            "started": fixture_started,
            "finished": fixture_finished,
            "venue": (venue or {}).get("venue"),
            "fetch_status": fetch_status,
            "error": error,
            "_observations": observations,
            "_kickoff": kickoff,
        }
        rows.append(row)
        row_index = len(rows) - 1
        if venue is not None and fetch_status == "PENDING_LIVE_OBSERVATION":
            pending.append((row_index, "LIVE_OBSERVED", venue, kickoff))
        elif venue is not None and fetch_status == "PENDING_FORECAST_REFRESH":
            pending.append((row_index, "FORECAST", venue, kickoff))

    if pending:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as pool:
            futures = {}
            for idx, mode, venue, kickoff in pending:
                fn = _weather_live_observed if mode == "LIVE_OBSERVED" else _weather_for_kickoff
                args = (venue, cfg) if mode == "LIVE_OBSERVED" else (venue, kickoff, cfg)
                futures[pool.submit(fn, *args)] = (idx, mode)
            for future in as_completed(futures):
                idx, mode = futures[future]
                row = rows[idx]
                try:
                    row["_observations"].append(future.result())
                    row["fetch_status"] = "LIVE_AVAILABLE" if mode == "LIVE_OBSERVED" else "FORECAST_AVAILABLE"
                    row["error"] = None
                except Exception as exc:
                    row["fetch_status"] = "LIVE_UNAVAILABLE_FALLBACK" if mode == "LIVE_OBSERVED" else "UNAVAILABLE"
                    row["error"] = f"{type(exc).__name__}: {exc}"

    rows = [_finalize_row(row, keep, now, cfg) for row in rows]
    material = [
        row
        for row in rows
        if ((row.get("selected_evidence") or {}).get("severity") in {"NOTABLE", "ADVERSE", "EXTREME"})
    ]
    stale_count = sum(1 for row in rows if row.get("freshness") == "STALE")
    observed_count = sum(1 for row in rows if row.get("freshness") == "OBSERVED")
    payload = {
        "schema_version": 2,
        "model": cfg.get("model_id"),
        "generated_at": iso_now(),
        "provider": "open_meteo",
        "fixture_count": len(rows),
        "available_count": sum(1 for row in rows if row.get("selected_evidence")),
        "observed_count": observed_count,
        "stale_count": stale_count,
        "material_count": len(material),
        "evidence_precedence": list(cfg.get("evidence_precedence") or []),
        "fetch_metrics": {
            "network_fetches": len(pending),
            "reused_fresh": reused_fresh,
            "max_parallel_requests": max_workers,
            "elapsed_ms": round((time.perf_counter() - started_clock) * 1000.0, 3),
        },
        "venue_identity": {
            "registry": load_venues().get("registry"),
            "registry_schema": load_venues().get("schema_version"),
            "official_identity_required": True,
            "unresolved_count": sum(
                1
                for row in rows
                if row.get("fetch_status") in {"VENUE_UNKNOWN", "VENUE_IDENTITY_MISMATCH"}
            ),
        },
        "fixtures": rows,
        "material_fixtures": [
            {
                "fixture_id": row.get("fixture_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "kickoff_time": row.get("kickoff_time"),
                "evidence_precedence": row.get("evidence_precedence"),
                "evidence_state": row.get("evidence_state"),
                "freshness": row.get("freshness"),
                "severity": (row.get("selected_evidence") or {}).get("severity"),
                "signals": (row.get("selected_evidence") or {}).get("signals") or [],
                "weather": (row.get("selected_evidence") or {}).get("weather") or {},
                "forecast_confidence": (row.get("selected_evidence") or {}).get("forecast_confidence"),
            }
            for row in material
        ],
        "governance": governance,
    }
    atomic_json(data_dir / OUT_NAME, payload)
    return payload
