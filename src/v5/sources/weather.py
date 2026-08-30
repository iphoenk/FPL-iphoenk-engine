from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.v5.config_cache import ROOT, load_json_config
from src.v5.intelligence.weather_advisory import classify_weather, forecast_is_fresh, select_evidence
from src.v5.intelligence.weather_research import build_weather_research

CONFIG = "config/intelligence/weather_context.json"


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


def _venues() -> tuple[dict[int, dict[str, Any]], str]:
    cfg = load_json_config(CONFIG)
    path = ROOT / str(cfg["venue_registry"])
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    default_tz = str(payload.get("default_timezone") or "Europe/London")
    by_id = {
        int(row["team_id"]): {**row, "timezone": str(row.get("timezone") or default_tz)}
        for row in payload.get("venues") or []
        if isinstance(row, dict) and row.get("team_id") is not None
    }
    return by_id, str(payload.get("registry") or "UNKNOWN")


def _confidence(kickoff: datetime, now: datetime, cfg: dict[str, Any]) -> str:
    mapping = ((cfg.get("forecast_policy") or {}).get("confidence_by_horizon_days") or {})
    days = max(0, int(max(0.0, (kickoff - now).total_seconds() / 86400.0)))
    max_bucket = max([int(key) for key in mapping] or [0])
    return str(mapping.get(str(min(days, max_bucket))) or "LOW")


def _fetch_forecast(venue: dict[str, Any], kickoff: datetime, now: datetime) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    api = cfg.get("api") or {}
    tz_name = str(venue.get("timezone") or "Europe/London")
    local = kickoff.astimezone(ZoneInfo(tz_name))
    fields = [str(field) for field in api.get("hourly_fields") or []]
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
    index = times.index(target)

    def value(name: str) -> Any:
        values = hourly.get(name) or []
        return values[index] if index < len(values) else None

    classified = classify_weather({
        "source_kind": "FRESH_FORECAST",
        "evidence_state": "FORECAST",
        "weather": {
            "temperature_c": value("temperature_2m"),
            "precipitation_probability_pct": value("precipitation_probability"),
            "precipitation_mm_h": value("precipitation"),
            "wind_speed_kmh": value("wind_speed_10m"),
            "wind_gust_kmh": value("wind_gusts_10m"),
            "weather_code": value("weather_code"),
        },
    })
    return {
        "provider": "open_meteo",
        "fetched_at": now.isoformat(),
        "forecast_for": kickoff.isoformat(),
        "forecast_local_hour": target,
        "forecast_confidence": _confidence(kickoff, now, cfg),
        "source_kind": "FRESH_FORECAST",
        "evidence_state": "FORECAST",
        "freshness": "FRESH",
        "severity": classified["severity"],
        "signals": classified["signals"],
        "weather": classified["weather"],
        "provenance": {
            "source": "Open-Meteo forecast",
            "endpoint": str(api["forecast_url"]),
            "venue": venue.get("venue"),
            "latitude": venue.get("latitude"),
            "longitude": venue.get("longitude"),
            "timezone": tz_name,
            "forecast_provider_is_not_observed_weather": True,
        },
    }


def _prior_fixture_map(previous: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = previous if isinstance(previous, dict) else {}
    return {
        str(row.get("fixture_id")): row
        for row in payload.get("fixtures") or []
        if isinstance(row, dict) and row.get("fixture_id") is not None
    }


def _forecast_snapshots(prior: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = [
        dict(row) for row in prior.get("forecast_snapshots") or []
        if isinstance(row, dict)
    ]
    if not snapshots:
        for row in prior.get("observations") or []:
            if isinstance(row, dict) and str(row.get("evidence_state") or "FORECAST") == "FORECAST":
                snapshots.append(dict(row))
    current = prior.get("current")
    if not snapshots and isinstance(current, dict):
        snapshots.append(dict(current))
    snapshots.sort(key=lambda row: str(row.get("fetched_at") or ""))
    return snapshots


def _health(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "status": "UNAVAILABLE",
            "fixture_count": 0,
            "available_count": 0,
            "stale_count": 0,
            "unresolved_venue_count": 0,
            "observation_gap_count": 0,
        }
    available = [row for row in rows if isinstance(row.get("selected_evidence"), dict)]
    stale = [
        row for row in available
        if str((row.get("selected_evidence") or {}).get("evidence_kind")) == "STALE_FORECAST"
    ]
    unresolved = [row for row in rows if row.get("fetch_status") in {"VENUE_UNKNOWN", "VENUE_IDENTITY_MISMATCH"}]
    observation_gaps = [
        row for row in rows
        if (row.get("started") or row.get("finished"))
        and not isinstance(row.get("live_observation"), dict)
        and not isinstance(row.get("closest_to_kickoff_observation"), dict)
    ]
    if not available:
        status = "UNAVAILABLE"
    elif len(stale) == len(available):
        status = "STALE"
    elif len(available) == len(rows) and not unresolved and not observation_gaps and not stale:
        status = "PASS"
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "fixture_count": len(rows),
        "available_count": len(available),
        "stale_count": len(stale),
        "unresolved_venue_count": len(unresolved),
        "observation_gap_count": len(observation_gaps),
    }


def collect(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    policy = cfg.get("forecast_policy") or {}
    now = datetime.now(timezone.utc)
    teams = {
        int(row["id"]): str(row.get("name") or row.get("short_name") or "")
        for row in bootstrap.get("teams") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    venues, registry_name = _venues()
    prior_by_id = _prior_fixture_map(previous)
    max_days = float(policy.get("max_horizon_days") or 7)
    post_hours = float(policy.get("post_match_retention_hours") or 72)
    keep = max(1, int(policy.get("retain_forecast_snapshots_per_fixture") or 12))
    max_workers = max(1, min(8, int((cfg.get("api") or {}).get("max_parallel_requests") or 4)))
    rows: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any], datetime]] = []

    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        days_to = (kickoff - now).total_seconds() / 86400.0
        age_hours = (now - kickoff).total_seconds() / 3600.0
        if days_to > max_days or age_hours > post_hours:
            continue
        fixture_id = str(fixture.get("id"))
        home_id = int(fixture.get("team_h") or -1)
        home_name = teams.get(home_id, "Unknown")
        away_name = teams.get(int(fixture.get("team_a") or -1), "Unknown")
        venue = venues.get(home_id)
        prior = prior_by_id.get(fixture_id) or {}
        snapshots = _forecast_snapshots(prior)
        live_observation = prior.get("live_observation") if isinstance(prior.get("live_observation"), dict) else None
        closest_observation = prior.get("closest_to_kickoff_observation") if isinstance(prior.get("closest_to_kickoff_observation"), dict) else None
        post_match_reconciliation = prior.get("post_match_reconciliation") if isinstance(prior.get("post_match_reconciliation"), dict) else None
        observed_effects = prior.get("observed_match_effects") if isinstance(prior.get("observed_match_effects"), dict) else {}
        sustainability = prior.get("sustainability") if isinstance(prior.get("sustainability"), dict) else {}
        fetch_status = "NOT_ATTEMPTED"
        error = None

        if venue is None or str(venue.get("team_name") or "") != home_name:
            fetch_status = "VENUE_IDENTITY_MISMATCH" if venue is not None else "VENUE_UNKNOWN"
        elif kickoff <= now:
            fetch_status = "HISTORICAL_RETAINED_EVIDENCE"
        elif snapshots and forecast_is_fresh(snapshots[-1], now=now):
            fetch_status = "REUSED_FRESH_FORECAST"
        else:
            fetch_status = "PENDING_FORECAST_REFRESH"

        row = {
            "fixture_id": int(fixture.get("id") or 0),
            "event": fixture.get("event"),
            "home_team_id": home_id,
            "away_team_id": int(fixture.get("team_a") or -1),
            "home_team": home_name,
            "away_team": away_name,
            "kickoff_time": kickoff.isoformat(),
            "started": bool(fixture.get("started")),
            "finished": bool(fixture.get("finished")),
            "venue": (venue or {}).get("venue"),
            "fetch_status": fetch_status,
            "error": error,
            "forecast_snapshots": snapshots,
            "closest_to_kickoff_observation": closest_observation,
            "live_observation": live_observation,
            "post_match_reconciliation": post_match_reconciliation,
            "observed_match_effects": observed_effects,
            "sustainability": sustainability,
        }
        rows.append(row)
        if fetch_status == "PENDING_FORECAST_REFRESH" and venue is not None:
            pending.append((len(rows) - 1, venue, kickoff))

    network_fetches = 0
    if pending:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as pool:
            futures = {
                pool.submit(_fetch_forecast, venue, kickoff, now): index
                for index, venue, kickoff in pending
            }
            for future in as_completed(futures):
                index = futures[future]
                network_fetches += 1
                try:
                    rows[index]["forecast_snapshots"].append(future.result())
                    rows[index]["fetch_status"] = "AVAILABLE"
                except Exception as exc:
                    rows[index]["fetch_status"] = "UNAVAILABLE"
                    rows[index]["error"] = f"{type(exc).__name__}: {exc}"

    for row in rows:
        snapshots = [
            dict(item) for item in row.get("forecast_snapshots") or []
            if isinstance(item, dict)
        ]
        snapshots.sort(key=lambda item: str(item.get("fetched_at") or ""))
        row["forecast_snapshots"] = snapshots[-keep:]
        selected = select_evidence(
            live_observation=row.get("live_observation"),
            closest_to_kickoff_observation=row.get("closest_to_kickoff_observation"),
            forecast_snapshots=row["forecast_snapshots"],
            now=now,
        )
        if isinstance(selected, dict):
            classified = classify_weather(selected)
            selected = {**selected, "severity": classified["severity"], "signals": classified["signals"], "weather": classified["weather"]}
        row["selected_evidence"] = selected

    health = _health(rows)
    research = build_weather_research(rows)
    return {
        "schema_version": 1,
        "source": "weather_context",
        "model": cfg.get("model_id"),
        "status": "ACTIVE" if health["status"] in {"PASS", "PARTIAL", "STALE"} else "UNAVAILABLE",
        "availability_class": health["status"],
        "weather_context_status": health["status"],
        "generated_at": now.isoformat(),
        "provider": cfg.get("provider_source_id"),
        "venue_registry": registry_name,
        "fixtures": rows,
        "health": health,
        "research": research,
        "observability": {
            "network_requests": network_fetches,
            "retained_fixture_count": len(rows),
            "forecast_provider_only": True,
            "observed_weather_provider_configured": False,
        },
        "governance": {
            **(cfg.get("governance") or {}),
            "network_fetch_owner": "ingestion",
            "forecast_provider_is_not_observed_weather": True,
            "missing_observation_is_not_backfilled_from_forecast": True,
            "decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION",
        },
    }
