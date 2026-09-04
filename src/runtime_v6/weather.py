from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_weather(row: dict[str, Any], contract: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """Classify weather context without turning it into a direct FPL points coefficient."""
    contract = contract or {}
    legacy = dict(contract.get("legacy_attention_thresholds") or {})
    wind_attention = float(legacy.get("wind_speed_kmh") or 30)
    rain_probability_attention = float(legacy.get("rain_probability_pct") or 60)
    cold_attention = float(legacy.get("temperature_c") or 5)

    temp = _float(row.get("temperature_2m"))
    rain_probability = _float(row.get("precipitation_probability"))
    precipitation = _float(row.get("precipitation")) or 0.0
    rain = _float(row.get("rain")) or 0.0
    showers = _float(row.get("showers")) or 0.0
    wind = _float(row.get("wind_speed_10m")) or 0.0
    gust = _float(row.get("wind_gusts_10m")) or 0.0

    reasons: list[str] = []
    severity = "NORMAL"

    # Intensity-aware upper bands. These are transparent contextual flags only;
    # they never become an automatic xPts multiplier or transfer trigger.
    if wind >= 55 or gust >= 70 or precipitation >= 8 or rain >= 6 or showers >= 8:
        severity = "EXTREME"
    elif wind >= 40 or gust >= 55 or precipitation >= 4 or rain >= 3 or showers >= 4:
        severity = "ADVERSE"
    elif (
        wind >= wind_attention
        or gust >= 40
        or precipitation >= 1
        or rain >= 1
        or showers >= 1
        or (rain_probability is not None and rain_probability >= rain_probability_attention)
        or (temp is not None and temp <= cold_attention)
        or (temp is not None and temp >= 30)
    ):
        severity = "NOTABLE"

    if wind >= wind_attention:
        reasons.append(f"wind_speed_{wind:.1f}kmh")
    if gust >= 40:
        reasons.append(f"wind_gust_{gust:.1f}kmh")
    if rain_probability is not None and rain_probability >= rain_probability_attention:
        reasons.append(f"rain_probability_{rain_probability:.0f}pct")
    if precipitation >= 1:
        reasons.append(f"precipitation_{precipitation:.1f}mm")
    if rain >= 1:
        reasons.append(f"rain_{rain:.1f}mm")
    if showers >= 1:
        reasons.append(f"showers_{showers:.1f}mm")
    if temp is not None and temp <= cold_attention:
        reasons.append(f"cold_{temp:.1f}c")
    if temp is not None and temp >= 30:
        reasons.append(f"heat_{temp:.1f}c")

    return severity, reasons


def _nearest_hourly_weather(location: dict[str, Any], kickoff_iso: str) -> dict[str, Any] | None:
    hourly = dict(location.get("hourly") or {})
    times = list(hourly.get("time") or [])
    if not times:
        return None

    kickoff = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00")).astimezone(LONDON)
    candidates: list[tuple[float, int, datetime]] = []
    for idx, raw in enumerate(times):
        try:
            local_dt = datetime.fromisoformat(str(raw)).replace(tzinfo=LONDON)
        except ValueError:
            continue
        candidates.append((abs((local_dt - kickoff).total_seconds()), idx, local_dt))
    if not candidates:
        return None

    distance_seconds, idx, forecast_time = min(candidates, key=lambda item: item[0])
    if distance_seconds > 3600:
        return None

    fields = (
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation_probability",
        "precipitation",
        "rain",
        "showers",
        "weather_code",
        "wind_speed_10m",
        "wind_gusts_10m",
    )
    row: dict[str, Any] = {
        "forecast_time_local": forecast_time.isoformat(),
        "kickoff_time_local": kickoff.isoformat(),
        "forecast_distance_minutes": round(distance_seconds / 60.0, 1),
        "evidence_state": "FRESH_FORECAST",
    }
    for field in fields:
        values = hourly.get(field)
        row[field] = values[idx] if isinstance(values, list) and idx < len(values) else None
    return row


def enrich_open_meteo_payload(
    source: dict[str, Any],
    payload: dict[str, Any],
    official_payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach next-GW fixture weather using Official FPL as fixture/team authority."""
    out = dict(payload)
    official = dict(official_payload.get("official") or {})
    bootstrap = dict(official.get("bootstrap") or {})
    fixtures = list(official.get("fixtures") or [])
    teams = list(bootstrap.get("teams") or [])
    events = list(bootstrap.get("events") or [])

    team_name_by_id = {int(team["id"]): str(team.get("name") or "") for team in teams if team.get("id") is not None}
    next_event = next((event.get("id") for event in events if event.get("is_next") is True), None)
    next_fixtures = [
        fixture
        for fixture in fixtures
        if fixture.get("kickoff_time") and (next_event is None or fixture.get("event") == next_event)
    ]

    raw = (((out.get("data") or {}).get("epl_venues") or {}).get("json"))
    locations = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    venues = list(source.get("venues") or [])
    location_by_team: dict[str, dict[str, Any]] = {}
    venue_by_team: dict[str, dict[str, Any]] = {}
    for idx, venue in enumerate(venues):
        team = str(venue.get("team") or "")
        if not team:
            continue
        venue_by_team[team] = dict(venue)
        if idx < len(locations) and isinstance(locations[idx], dict):
            location_by_team[team] = locations[idx]

    fixture_weather: list[dict[str, Any]] = []
    unmapped_home_teams: list[str] = []
    unavailable_forecasts: list[int] = []
    contract = dict(source.get("weather_contract") or {})

    for fixture in next_fixtures:
        home_id = fixture.get("team_h")
        away_id = fixture.get("team_a")
        home = team_name_by_id.get(int(home_id)) if home_id is not None else None
        away = team_name_by_id.get(int(away_id)) if away_id is not None else None
        fixture_id = int(fixture.get("id")) if fixture.get("id") is not None else None
        venue = venue_by_team.get(str(home))
        location = location_by_team.get(str(home))
        row: dict[str, Any] = {
            "fixture_id": fixture_id,
            "event": fixture.get("event"),
            "home_team": home,
            "away_team": away,
            "kickoff_time": fixture.get("kickoff_time"),
            "stadium": (venue or {}).get("stadium"),
            "weather_available": False,
        }
        if venue is None or location is None:
            if home:
                unmapped_home_teams.append(home)
            row["reason"] = "VENUE_OR_LOCATION_UNMAPPED"
            fixture_weather.append(row)
            continue

        weather = _nearest_hourly_weather(location, str(fixture["kickoff_time"]))
        if weather is None:
            if fixture_id is not None:
                unavailable_forecasts.append(fixture_id)
            row["reason"] = "FORECAST_OUTSIDE_AVAILABLE_HORIZON"
            fixture_weather.append(row)
            continue

        severity, reasons = classify_weather(weather, contract)
        row.update(weather)
        row.update(
            {
                "weather_available": True,
                "severity": severity,
                "attention_reasons": reasons,
                "direct_xpts_multiplier": False,
                "weather_alone_can_trigger_transfer": False,
            }
        )
        fixture_weather.append(row)

    out["weather"] = {
        "fixture_authority": "official_fpl",
        "weather_provider": "open_meteo",
        "event": next_event,
        "contract": contract,
        "venue_count": len(venues),
        "provider_location_count": len(locations),
        "fixture_count": len(next_fixtures),
        "forecasted_fixture_count": sum(row.get("weather_available") is True for row in fixture_weather),
        "unmapped_home_teams": sorted(set(unmapped_home_teams)),
        "unavailable_forecast_fixture_ids": unavailable_forecasts,
        "fixtures": fixture_weather,
        "attribution": source.get("attribution"),
    }
    out.setdefault("governance", {})["weather_is_context_only"] = True
    out["governance"]["weather_direct_xpts_multiplier"] = False
    out["governance"]["weather_alone_can_trigger_transfer"] = False
    return out
