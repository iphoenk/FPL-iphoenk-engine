from __future__ import annotations

from src.runtime_v6.registry import load_registry, source_map
from src.runtime_v6.weather import (
    classify_weather,
    enrich_open_meteo_payload,
    load_weather_venues,
    materialize_open_meteo_source,
)


def test_weather_classifier_is_context_only_and_intensity_aware():
    normal, _ = classify_weather(
        {
            "temperature_2m": 18,
            "precipitation_probability": 10,
            "precipitation": 0,
            "rain": 0,
            "showers": 0,
            "wind_speed_10m": 10,
            "wind_gusts_10m": 15,
        }
    )
    adverse, reasons = classify_weather(
        {
            "temperature_2m": 14,
            "precipitation_probability": 90,
            "precipitation": 5,
            "rain": 4,
            "showers": 0,
            "wind_speed_10m": 35,
            "wind_gusts_10m": 48,
        }
    )
    extreme, _ = classify_weather(
        {
            "temperature_2m": 12,
            "precipitation_probability": 95,
            "precipitation": 9,
            "rain": 7,
            "showers": 0,
            "wind_speed_10m": 58,
            "wind_gusts_10m": 72,
        }
    )

    assert normal == "NORMAL"
    assert adverse == "ADVERSE"
    assert any(reason.startswith("rain_") or reason.startswith("precipitation_") for reason in reasons)
    assert extreme == "EXTREME"


def test_open_meteo_fixture_join_uses_official_fpl_authority():
    source = {
        "id": "open_meteo_weather",
        "venue_registry": "config/venues/premier_league_2026_27.json",
        "weather_contract": {
            "legacy_attention_thresholds": {
                "wind_speed_kmh": 30,
                "rain_probability_pct": 60,
                "temperature_c": 5,
            },
            "direct_xpts_multiplier": False,
            "weather_alone_can_trigger_transfer": False,
        },
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0).",
    }
    payload = {
        "health": "GREEN",
        "data": {
            "epl_venues": {
                "json": [
                    {
                        "hourly": {
                            "time": ["2026-09-05T15:00"],
                            "temperature_2m": [14.0],
                            "relative_humidity_2m": [92],
                            "precipitation_probability": [90],
                            "precipitation": [5.0],
                            "rain": [4.0],
                            "showers": [0.0],
                            "weather_code": [63],
                            "wind_speed_10m": [35.0],
                            "wind_gusts_10m": [48.0],
                        }
                    }
                ]
            }
        },
        "governance": {},
    }
    official = {
        "official": {
            "bootstrap": {
                "teams": [
                    {"id": 1, "name": "Arsenal"},
                    {"id": 2, "name": "Chelsea"},
                ],
                "events": [{"id": 3, "is_next": True}],
            },
            "fixtures": [
                {
                    "id": 301,
                    "event": 3,
                    "team_h": 1,
                    "team_a": 2,
                    "kickoff_time": "2026-09-05T14:00:00Z",
                }
            ],
        }
    }

    result = enrich_open_meteo_payload(source, payload, official)
    weather = result["weather"]
    fixture = weather["fixtures"][0]

    assert weather["fixture_authority"] == "official_fpl"
    assert weather["fixture_join_key"] == "official_fpl_team_id"
    assert weather["weather_provider"] == "open_meteo"
    assert weather["venue_registry"] == "config/venues/premier_league_2026_27.json"
    assert weather["event"] == 3
    assert weather["identity_mismatch_home_team_ids"] == []
    assert fixture["fixture_id"] == 301
    assert fixture["home_team_id"] == 1
    assert fixture["away_team_id"] == 2
    assert fixture["stadium"] == "Emirates Stadium"
    assert fixture["weather_available"] is True
    assert fixture["severity"] == "ADVERSE"
    assert fixture["rain"] == 4.0
    assert fixture["wind_gusts_10m"] == 48.0
    assert fixture["direct_xpts_multiplier"] is False
    assert fixture["weather_alone_can_trigger_transfer"] is False
    assert result["governance"]["weather_is_context_only"] is True
    assert result["governance"]["venue_coordinates_are_registry_owned"] is True
    assert result["governance"]["venue_fixture_join_uses_official_team_id"] is True


def test_open_meteo_reuses_canonical_2026_27_venue_registry_once():
    sources = source_map(load_registry())
    weather = sources["open_meteo_weather"]
    static_params = weather["requests"][0]["params"]
    venues = load_weather_venues(weather)
    materialized = materialize_open_meteo_source(weather)
    params = materialized["requests"][0]["params"]

    assert weather["venue_registry"] == "config/venues/premier_league_2026_27.json"
    assert "venues" not in weather
    assert "latitude" not in static_params
    assert "longitude" not in static_params
    assert len(venues) == 20
    assert len({venue["team_id"] for venue in venues}) == 20
    assert len({venue["team"] for venue in venues}) == 20
    assert len(str(params["latitude"]).split(",")) == 20
    assert len(str(params["longitude"]).split(",")) == 20
    assert weather["weather_contract"]["precedence"] == [
        "LIVE_OBSERVED",
        "CLOSEST_TO_KICKOFF_OBSERVATION",
        "FRESH_FORECAST",
        "STALE_FORECAST",
    ]


def test_open_meteo_is_native_v6_acquisition_not_v3_upstream():
    sources = source_map(load_registry())
    weather = sources["open_meteo_weather"]

    assert weather["adapter"] == "open_meteo_weather"
    assert weather["depends_on"] == ["official_fpl"]
    assert weather["requests"][0]["url"] == "https://api.open-meteo.com/v1/forecast"
    assert "v3" not in str(weather).lower()
