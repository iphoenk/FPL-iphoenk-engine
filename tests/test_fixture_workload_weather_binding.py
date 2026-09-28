from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.engines.v12_report_orchestration import build_calendar_workload_context
from src.engines import v12_s05_binding
from src.sources import report_time_competition_schedule
from src.sources import weather_open_meteo


def _bootstrap():
    return {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
        "elements": [
            {"id": 101, "web_name": "Owned", "team": 1},
        ],
    }


def test_report_time_competition_schedule_exact_identity_and_fail_soft(monkeypatch):
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    planning = [
        {
            "id": 9001,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00Z",
        }
    ]
    ucl_payload = {
        "events": [
            {
                "id": "ucl-1",
                "date": "2026-09-30T19:00:00Z",
                "competitions": [
                    {
                        "date": "2026-09-30T19:00:00Z",
                        "venue": {
                            "fullName": "European Ground",
                            "address": {"country": "Spain"},
                        },
                        "status": {"type": {"name": "STATUS_SCHEDULED"}},
                        "competitors": [
                            {
                                "homeAway": "away",
                                "team": {
                                    "abbreviation": "ARS",
                                    "displayName": "Arsenal",
                                },
                            },
                            {
                                "homeAway": "home",
                                "team": {
                                    "abbreviation": "RMA",
                                    "displayName": "Real Madrid",
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }

    def fake_fetch_one(*, provider, competition_cfg, start_date, end_date):
        if competition_cfg["slug"] == "uefa.champions":
            return (
                competition_cfg["slug"],
                ucl_payload,
                "https://example.test/ucl",
            )
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(
        report_time_competition_schedule,
        "_fetch_one",
        fake_fetch_one,
    )
    cfg = {
        "contract": "REPORT_TIME_COMPETITION_SCHEDULE_V1",
        "provider": {
            "base_url": "https://example.test",
            "lookback_days": 21,
            "max_parallel_requests": 2,
        },
        "competitions": [
            {
                "name": "UEFA Champions League",
                "slug": "uefa.champions",
                "category": "CONTINENTAL_CLUB",
            },
            {
                "name": "FA Cup",
                "slug": "eng.fa",
                "category": "DOMESTIC_CUP",
            },
        ],
        "governance": {"context_only": True},
    }
    result = report_time_competition_schedule.collect_verified_non_pl_schedule(
        bootstrap=_bootstrap(),
        planning_fixtures=planning,
        report_timestamp=now.isoformat(),
        config=cfg,
    )
    assert result["status"] == "PARTIAL"
    assert result["event_count"] == 1
    event = result["events"][0]
    assert event["team_id"] == 1
    assert event["competition"] == "UEFA Champions League"
    assert event["competition_category"] == "CONTINENTAL_CLUB"
    assert event["home_away"] == "A"
    assert event["cross_border"] is True
    assert event["travel_context"] == "EUROPEAN_AWAY"
    assert event["verified_source"] == "ESPN_PUBLIC_COMPETITION_SCHEDULE"


def test_report_time_competition_schedule_never_fuzzy_joins_team():
    cfg = {
        "name": "UEFA Champions League",
        "category": "CONTINENTAL_CLUB",
    }
    payload = {
        "events": [
            {
                "id": "bad-join",
                "date": "2026-09-30T19:00:00Z",
                "competitions": [
                    {
                        "date": "2026-09-30T19:00:00Z",
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {
                                    "abbreviation": "ARX",
                                    "displayName": "Arsen",
                                },
                            },
                            {
                                "homeAway": "away",
                                "team": {
                                    "abbreviation": "CHEX",
                                    "displayName": "Chels",
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }
    rows = report_time_competition_schedule._competition_rows(
        payload=payload,
        competition_cfg=cfg,
        bootstrap=_bootstrap(),
        floor=datetime(2026, 9, 28, tzinfo=timezone.utc),
        ceiling=datetime(2026, 10, 3, tzinfo=timezone.utc),
        source_url="https://example.test",
    )
    assert rows == []


def test_weather_can_bind_ephemerally_from_injected_official_snapshot(
    tmp_path,
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(hours=20)
    venue = {
        "team_id": 1,
        "team_name": "Arsenal",
        "venue": "Test Ground",
        "latitude": 51.5,
        "longitude": -0.1,
        "timezone": "Europe/London",
    }
    monkeypatch.setattr(
        weather_open_meteo,
        "_venue_maps",
        lambda: ({1: venue}, {"Arsenal": venue}),
    )

    def fake_forecast(bound_venue, bound_kickoff, cfg):
        return {
            "evidence_kind": "FORECAST",
            "fetched_at": now.isoformat(),
            "provider": "open_meteo",
            "forecast_for": bound_kickoff.isoformat(),
            "evidence_timestamp": bound_kickoff.isoformat(),
            "forecast_confidence": "HIGH",
            "severity": "NORMAL",
            "signals": [],
            "weather": {
                "temperature_c": 15.0,
                "precipitation_probability_pct": 20,
                "precipitation_mm_h": 0.0,
                "wind_speed_kmh": 10.0,
                "wind_gust_kmh": 16.0,
                "weather_code": 1,
            },
        }

    monkeypatch.setattr(
        weather_open_meteo,
        "_weather_for_kickoff",
        fake_forecast,
    )
    payload = weather_open_meteo.collect_weather_context(
        tmp_path,
        official_snapshot={
            "bootstrap": {
                "teams": [
                    {"id": 1, "name": "Arsenal"},
                    {"id": 2, "name": "Chelsea"},
                ]
            },
            "fixtures": [
                {
                    "id": 9001,
                    "event": 6,
                    "team_h": 1,
                    "team_a": 2,
                    "kickoff_time": kickoff.isoformat(),
                    "started": False,
                    "finished": False,
                }
            ],
        },
        persist=False,
    )
    assert payload["available_count"] == 1
    assert payload["fixtures"][0]["freshness"] == "FRESH"
    assert not (tmp_path / "fixture_weather.json").exists()


def test_s05_binding_surfaces_europe_and_weather(monkeypatch, tmp_path):
    report_slot = "2026-09-28T12:00:00+00:00"
    fixtures = [
        {
            "id": 9001,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00+00:00",
        }
    ]
    monkeypatch.setattr(
        v12_s05_binding,
        "collect_verified_non_pl_schedule",
        lambda **kwargs: {
            "status": "COMPLETE",
            "authority_complete": True,
            "events": [
                {
                    "team_id": 1,
                    "player_id": None,
                    "kickoff": "2026-09-30T19:00:00+00:00",
                    "competition": "UEFA Champions League",
                    "competition_category": "CONTINENTAL_CLUB",
                    "home_away": "A",
                    "opponent": "Real Madrid",
                    "venue": "European Ground",
                    "cross_border": True,
                    "long_haul": False,
                    "travel_context": "EUROPEAN_AWAY",
                    "verified": True,
                }
            ],
        },
    )
    monkeypatch.setattr(
        v12_s05_binding,
        "collect_weather_context",
        lambda *args, **kwargs: {
            "provider": "open_meteo",
            "fixtures": [
                {
                    "fixture_id": 9001,
                    "event": 6,
                    "venue": "Test Ground",
                    "kickoff_time": "2026-10-03T14:00:00+00:00",
                    "evidence_state": "FORECAST",
                    "freshness": "FRESH",
                    "fetch_status": "FORECAST_AVAILABLE",
                    "selected_evidence": {
                        "provider": "open_meteo",
                        "severity": "NOTABLE",
                        "signals": ["wind_speed"],
                        "evidence_timestamp": "2026-10-03T14:00:00+00:00",
                        "forecast_confidence": "MEDIUM",
                        "weather": {
                            "temperature_c": 13.0,
                            "precipitation_probability_pct": 40,
                            "precipitation_mm_h": 0.4,
                            "wind_speed_kmh": 24.0,
                            "wind_gust_kmh": 36.0,
                        },
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        v12_s05_binding,
        "load_weather_config",
        lambda: {"forecast_policy": {"max_horizon_days": 7}},
    )

    bound = v12_s05_binding.build_report_time_s05_inputs(
        bootstrap=_bootstrap(),
        fixtures=fixtures,
        planning_gw=6,
        report_slot=report_slot,
        output_dir=tmp_path / "report",
        runtime_data_root=tmp_path / "runtime",
        private_data_root=None,
    )
    assert bound["non_pl_schedule_authority"] is True
    assert len(bound["verified_schedule_events"]) == 1
    assert bound["weather_rows"][0]["fpl_impact"] == "LOW"
    assert bound["weather_forecast_horizon_hours"] == 168.0

    context = build_calendar_workload_context(
        planning_gw=6,
        pl_fixtures=fixtures,
        team_ids=[1, 2],
        relevant_players=[
            {
                "element_id": 101,
                "name": "Owned",
                "team_id": 1,
                "planning_fixture_evidence": [],
            }
        ],
        verified_schedule_events=bound["verified_schedule_events"],
        non_pl_schedule_authority=True,
        report_timestamp=report_slot,
        weather_rows=bound["weather_rows"],
        weather_forecast_horizon_hours=168.0,
    )
    row = context["player_workload"][0]
    assert context["state"] == "COMPLETE"
    assert context["competition_coverage"]["verified_non_pl_schedule_bound"] is True
    assert context["period_flags"]["non_pl_schedule_present"] is True
    assert row["load_state"] == "EUROPE MIDWEEK"
    assert row["non_pl_competitions"] == ["UEFA Champions League"]
    assert row["next_non_pl_event"]["competition"] == "UEFA Champions League"
    assert row["rest_hours_after_next_non_pl_to_pl"] == 67.0
    assert context["weather"][0]["fpl_impact"] == "LOW"


def test_major_international_tournaments_map_to_international():
    for name in (
        "Africa Cup of Nations",
        "AFCON",
        "FIFA World Cup Qualifying",
        "UEFA Nations League",
        "Copa America",
        "AFC Asian Cup",
    ):
        assert v12_s05_binding._category_for_competition(name) == "INTERNATIONAL"
