from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence.weather_advisory import collect_weather_context


def _snapshot():
    return {
        "schema": "snapshot.v1",
        "generated_at": "2026-08-30T12:00:00+00:00",
        "official": {
            "bootstrap": {
                "teams": [
                    {"id": 1, "name": "Arsenal"},
                    {"id": 6, "name": "Chelsea"},
                ]
            },
            "fixtures": [
                {
                    "id": 101,
                    "event": 3,
                    "team_h": 1,
                    "team_a": 6,
                    "kickoff_time": "2026-08-31T15:00:00+00:00",
                    "started": False,
                    "finished": False,
                }
            ],
        },
    }


def _forecast(timestamp: str):
    return {
        "source_kind": "FRESH_FORECAST",
        "evidence_timestamp": timestamp,
        "forecast_for": "2026-08-31T15:00:00+00:00",
        "weather": {
            "temperature_c": 16.0,
            "precipitation_probability_pct": 70,
            "precipitation_mm_h": 2.5,
            "wind_speed_kmh": 18.0,
            "wind_gust_kmh": 28.0,
            "weather_code": 61,
        },
    }


def _previous(timestamp: str):
    return {
        "fixtures": [
            {
                "fixture_id": 101,
                "evidence_history": [_forecast(timestamp)],
            }
        ]
    }


def test_fresh_forecast_is_reused_without_provider_refetch():
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)

    def must_not_fetch(*args, **kwargs):
        raise AssertionError("fresh governed forecast must be reused")

    out = collect_weather_context(
        _snapshot(),
        previous=_previous("2026-08-30T11:00:00+00:00"),
        now=now,
        fetcher=must_not_fetch,
    )

    assert out["provider_fetch_count"] == 0
    assert out["fresh_evidence_reuse_count"] == 1
    assert out["fixtures"][0]["fresh_evidence_reused"] is True
    assert out["fixtures"][0]["evidence_state"] == "FRESH_FORECAST"
    assert out["health"]["status"] == "PASS"
    assert out["governance"]["fresh_forecast_reuse_is_freshness_governed"] is True


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "hourly": {
                "time": ["2026-08-31T16:00"],
                "temperature_2m": [15.0],
                "precipitation_probability": [80],
                "precipitation": [4.0],
                "wind_speed_10m": [22.0],
                "wind_gusts_10m": [36.0],
                "weather_code": [63],
            }
        }


def test_stale_forecast_forces_provider_refresh():
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    calls = []

    def fetcher(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response()

    out = collect_weather_context(
        _snapshot(),
        previous=_previous("2026-08-29T00:00:00+00:00"),
        now=now,
        fetcher=fetcher,
    )

    assert len(calls) == 1
    assert out["provider_fetch_count"] == 1
    assert out["fresh_evidence_reuse_count"] == 0
    assert out["fixtures"][0]["evidence_state"] == "FRESH_FORECAST"
    assert out["governance"]["stale_forecast_triggers_refresh"] is True
