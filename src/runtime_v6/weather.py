from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
LONDON = ZoneInfo("Europe/London")


def load_weather_venues(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve weather venues from the repo-wide canonical venue registry."""
    registry_ref = str(source.get("venue_registry") or "").strip()
    if not registry_ref:
        raise ValueError("Open-Meteo source requires venue_registry")
    path = ROOT / registry_ref
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("governance") or {}).get("coordinates_are_registry_owned") is not True:
        raise ValueError("weather venue coordinates must be registry-owned")

    default_tz = str(payload.get("default_timezone") or "Europe/London")
    venues: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for raw in payload.get("venues") or []:
        team_id = int(raw["team_id"])
        team_name = str(raw.get("team_name") or "").strip()
        if not team_name or team_id in seen_ids or team_name in seen_names:
            raise ValueError("invalid or duplicate weather venue identity")
        seen_ids.add(team_id)
        seen_names.add(team_name)
        venues.append(
            {
                "team_id": team_id,
                "team": team_name,
                "stadium": str(raw.get("venue") or "").strip(),
                "latitude": float(raw["latitude"]),
                "longitude": float(raw["longitude"]),
                "timezone": str(raw.get("timezone") or default_tz),
            }
        )
    if not venues:
        raise ValueError("weather venue registry is empty")
    return venues


def materialize_open_meteo_source(source: dict[str, Any]) -> dict[str, Any]:
    """Inject multi-location coordinates from the shared venue SSoT at runtime."""
    out = deepcopy(source)
    venues = load_weather_venues(source)
    requests = []
    for request in out.get("requests") or []:
        row = deepcopy(request)
        if str(row.get("id")) == "epl_venues":
            params = dict(row.get("params") or {})
            params["latitude"] = ",".join(str(venue["latitude"]) for venue in venues)
            params["longitude"] = ",".join(str(venue["longitude"]) for venue in venues)
            row["params"] = params
        requests.append(row)
    out["requests"] = requests
    return out


def _nearest_hourly_weather(location: dict[str, Any], kickoff_iso: str) -> dict[str, Any] | None:
    """Select the provider hour closest to kickoff without interpreting its impact."""
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
    }
    for field in fields:
        values = hourly.get(field)
        row[field] = values[idx] if isinstance(values, list) and idx < len(values) else None
    return row


def normalize_open_meteo_payload(
    source: dict[str, Any],
    payload: dict[str, Any],
    official_payload: dict[str, Any],
) -> dict[str, Any]:
    """Normalize provider weather facts against Official FPL fixture/team identities.

    V6 deliberately does not classify weather severity, generate attention reasons,
    infer football impact, or create any decision/xPts semantics. Those belong to
    downstream consumers.
    """
    out = dict(payload)
    official = dict(official_payload.get("official") or {})
    bootstrap = dict(official.get("bootstrap") or {})
    fixtures = list(official.get("fixtures") or [])
    teams = list(bootstrap.get("teams") or [])
    events = list(bootstrap.get("events") or [])

    team_name_by_id = {
        int(team["id"]): str(team.get("name") or "")
        for team in teams
        if team.get("id") is not None
    }
    next_event = next((event.get("id") for event in events if event.get("is_next") is True), None)
    next_fixtures = [
        fixture
        for fixture in fixtures
        if fixture.get("kickoff_time") and (next_event is None or fixture.get("event") == next_event)
    ]

    raw = (((out.get("data") or {}).get("epl_venues") or {}).get("json"))
    locations = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    venues = load_weather_venues(source)
    location_by_team_id: dict[int, dict[str, Any]] = {}
    venue_by_team_id: dict[int, dict[str, Any]] = {}
    for idx, venue in enumerate(venues):
        team_id = venue.get("team_id")
        if team_id is None:
            continue
        canonical_team_id = int(team_id)
        venue_by_team_id[canonical_team_id] = dict(venue)
        if idx < len(locations) and isinstance(locations[idx], dict):
            location_by_team_id[canonical_team_id] = locations[idx]

    fixture_weather: list[dict[str, Any]] = []
    unmapped_home_teams: list[str] = []
    identity_mismatch_home_team_ids: list[int] = []
    unavailable_forecasts: list[int] = []

    for fixture in next_fixtures:
        home_id_raw = fixture.get("team_h")
        away_id_raw = fixture.get("team_a")
        home_id = int(home_id_raw) if home_id_raw is not None else None
        away_id = int(away_id_raw) if away_id_raw is not None else None
        home = team_name_by_id.get(home_id) if home_id is not None else None
        away = team_name_by_id.get(away_id) if away_id is not None else None
        fixture_id = int(fixture.get("id")) if fixture.get("id") is not None else None
        venue = venue_by_team_id.get(home_id) if home_id is not None else None
        location = location_by_team_id.get(home_id) if home_id is not None else None
        row: dict[str, Any] = {
            "fixture_id": fixture_id,
            "event": fixture.get("event"),
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team": home,
            "away_team": away,
            "kickoff_time": fixture.get("kickoff_time"),
            "stadium": (venue or {}).get("stadium"),
            "weather_available": False,
        }
        if venue is None or location is None:
            if home:
                unmapped_home_teams.append(home)
            row["normalization_status"] = "VENUE_OR_LOCATION_UNMAPPED"
            fixture_weather.append(row)
            continue

        registry_team_name = str(venue.get("team") or "")
        if not home or registry_team_name != home:
            if home_id is not None:
                identity_mismatch_home_team_ids.append(home_id)
            row["normalization_status"] = "VENUE_IDENTITY_MISMATCH"
            fixture_weather.append(row)
            continue

        weather = _nearest_hourly_weather(location, str(fixture["kickoff_time"]))
        if weather is None:
            if fixture_id is not None:
                unavailable_forecasts.append(fixture_id)
            row["normalization_status"] = "FORECAST_OUTSIDE_AVAILABLE_HORIZON"
            fixture_weather.append(row)
            continue

        row.update(weather)
        row.update(
            {
                "weather_available": True,
                "normalization_status": "NORMALIZED_PROVIDER_FORECAST",
            }
        )
        fixture_weather.append(row)

    out["weather"] = {
        "semantic_class": "NORMALIZED_FACT",
        "fixture_authority": "official_fpl",
        "fixture_join_key": "official_fpl_team_id",
        "weather_provider": "open_meteo",
        "event": next_event,
        "venue_registry": source.get("venue_registry"),
        "venue_count": len(venues),
        "provider_location_count": len(locations),
        "fixture_count": len(next_fixtures),
        "forecasted_fixture_count": sum(row.get("weather_available") is True for row in fixture_weather),
        "unmapped_home_teams": sorted(set(unmapped_home_teams)),
        "identity_mismatch_home_team_ids": sorted(set(identity_mismatch_home_team_ids)),
        "unavailable_forecast_fixture_ids": unavailable_forecasts,
        "fixtures": fixture_weather,
        "attribution": source.get("attribution"),
    }
    out.setdefault("governance", {})["weather_normalization_only"] = True
    out["governance"]["weather_classification_authority"] = "NONE"
    out["governance"]["weather_impact_authority"] = "NONE"
    out["governance"]["weather_decision_authority"] = "NONE"
    out["governance"]["venue_coordinates_are_registry_owned"] = True
    out["governance"]["venue_fixture_join_uses_official_team_id"] = True
    return out
