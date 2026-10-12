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


def test_report_time_competition_schedule_uses_explicit_team_alias_not_fuzzy_join():
    by_abbreviation, by_name = report_time_competition_schedule._official_team_indexes(
        {
            "teams": [
                {"id": 15, "name": "Man City", "short_name": "MCI"},
            ]
        }
    )
    provider = {
        "abbreviation": "MNC",
        "displayName": "Manchester City",
        "shortDisplayName": "Manchester City",
        "name": "Manchester City",
    }
    assert report_time_competition_schedule._provider_team_id(
        provider,
        by_abbreviation=by_abbreviation,
        by_name=by_name,
        team_name_aliases={"Manchester City": "Man City"},
    ) == 15

    typo = {
        "abbreviation": "MNX",
        "displayName": "Manchester Cty",
        "name": "Manchester Cty",
    }
    assert report_time_competition_schedule._provider_team_id(
        typo,
        by_abbreviation=by_abbreviation,
        by_name=by_name,
        team_name_aliases={"Manchester City": "Man City"},
    ) is None


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


def test_fixture_display_rows_uses_official_fixture_order_for_rest_days():
    fixtures = [
        {
            "id": 8999,
            "event": 5,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-30T14:00:00Z",
        },
        {
            "id": 9001,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00Z",
        },
    ]
    rows = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(), fixtures=fixtures, planning_gw=6
    )
    assert rows[0]["fixture_id"] == 9001
    assert rows[0]["rest_days"] == "3.0"


def test_fixture_display_rows_expose_readable_identity_wib_venue_and_weather_binding():
    fixtures = [
        {
            "id": 9001,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00Z",
            "started": False,
            "finished": False,
        }
    ]
    weather = [
        {
            "fixture_id": 9001,
            "kickoff": "2026-10-03T14:00:00+00:00",
            "condition": "NORMAL",
            "state": "FORECAST",
            "freshness": "FRESH",
        }
    ]

    rows = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(), fixtures=fixtures, weather_rows=weather
    )

    assert rows == [
        {
            "fixture_id": 9001,
            "match": "Arsenal vs Chelsea",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_away": "H",
            "sides": "Arsenal HOME / Chelsea AWAY",
            "kickoff_wib": "03 Oct 2026, 21:00 WIB",
            "fixture_status": "NOT STARTED",
            "rest_days": "UNAVAILABLE",
            "venue": "Emirates Stadium",
            "venue_status": "VERIFIED",
            "weather": "NORMAL",
            "weather_state": "FORECAST",
            "weather_freshness": "FRESH",
            "weather_fixture_id": 9001,
            "weather_kickoff": "2026-10-03T14:00:00+00:00",
        }
    ]


def test_fixture_display_rows_fail_soft_for_unknown_venue_and_do_not_cross_bind_weather():
    fixtures = [
        {
            "id": 9001,
            "event": 6,
            "team_h": 99,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00Z",
        },
        {
            "id": 9002,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T15:00:00Z",
        },
    ]
    rows = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(),
        fixtures=fixtures,
        weather_rows=[
            {
                "fixture_id": 9001,
                "kickoff": "2026-10-03T14:00:00+00:00",
                "condition": "ADVERSE",
            }
        ],
    )

    assert rows[0]["match"] == "Unknown team vs Chelsea"
    assert rows[0]["venue"] == "VENUE UNAVAILABLE"
    assert rows[0]["venue_status"] == "UNAVAILABLE"
    assert rows[0]["weather"] == "ADVERSE"
    assert rows[1]["weather"] == "UNAVAILABLE"
    assert rows[1]["weather_fixture_id"] is None


def test_fixture_display_rows_preserve_all_ten_readable_fixture_cards(monkeypatch):
    monkeypatch.setattr(
        v12_s05_binding,
        "_venue_maps",
        lambda: ({1: {"team_name": "Arsenal", "venue": "Emirates Stadium"}}, {}),
    )
    fixtures = [
        {
            "id": 100 + index,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": f"2026-10-{index + 1:02d}T14:00:00Z",
        }
        for index in range(10)
    ]
    # Keep all ten target-GW rows, even when the Official FPL fixture
    # collection includes other GWs and rows with no event attribution.
    fixtures.extend([
        {"id": 999, "event": 7, "team_h": 1, "team_a": 2, "kickoff_time": "2026-10-18T14:00:00Z"},
        {"id": 998, "event": None, "team_h": 1, "team_a": 2, "kickoff_time": "2026-10-20T14:00:00Z"},
    ])
    rows = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(), fixtures=fixtures, planning_gw=6
    )
    assert len(rows) == 10
    assert {row["fixture_id"] for row in rows} == set(range(100, 110))
    gw7 = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(), fixtures=fixtures, planning_gw=7
    )
    assert [row["fixture_id"] for row in gw7] == [999]
    assert all(row["match"] == "Arsenal vs Chelsea" for row in rows)
    assert all(row["kickoff_wib"].endswith(" WIB") for row in rows)
    assert all(row["venue"] == "Emirates Stadium" for row in rows)
    assert all(row["fixture_id"] >= 100 for row in rows)


def test_fixture_display_rows_render_fixture_specific_rest_gap_and_both_sides(monkeypatch):
    monkeypatch.setattr(
        v12_s05_binding,
        "_venue_maps",
        lambda: ({1: {"team_name": "Arsenal", "venue": "Emirates Stadium"}}, {}),
    )
    rows = v12_s05_binding.build_fixture_display_rows(
        bootstrap=_bootstrap(),
        fixtures=[{
            "id": 300,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-10-03T14:00:00Z",
        }],
        workload_rows=[{
            "team_id": 1,
            "planning_gw_fixtures": [{
                "fixture_id": 300,
                "rest_from_previous_fixture_hours": 96,
            }],
        }],
    )
    assert rows[0]["sides"] == "Arsenal HOME / Chelsea AWAY"
    assert rows[0]["rest_days"] == "4.0"

def test_s05_weather_fetch_is_scoped_to_planning_gw(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        v12_s05_binding,
        "collect_verified_non_pl_schedule",
        lambda **kwargs: {
            "status": "COMPLETE",
            "authority_complete": True,
            "events": [],
        },
    )

    def fake_weather(*args, **kwargs):
        captured["official_snapshot"] = kwargs["official_snapshot"]
        return {"provider": "open_meteo", "fixtures": []}

    monkeypatch.setattr(
        v12_s05_binding,
        "collect_weather_context",
        fake_weather,
    )
    monkeypatch.setattr(
        v12_s05_binding,
        "load_weather_config",
        lambda: {"forecast_policy": {"max_horizon_days": 7}},
    )

    v12_s05_binding.build_report_time_s05_inputs(
        bootstrap=_bootstrap(),
        fixtures=[
            {
                "id": 9001,
                "event": 6,
                "team_h": 1,
                "team_a": 2,
                "kickoff_time": "2026-10-03T14:00:00+00:00",
            },
            {
                "id": 9002,
                "event": 7,
                "team_h": 2,
                "team_a": 1,
                "kickoff_time": "2026-10-10T14:00:00+00:00",
            },
        ],
        planning_gw=6,
        report_slot="2026-09-28T12:00:00+00:00",
        output_dir=tmp_path / "report",
        runtime_data_root=tmp_path / "runtime",
        private_data_root=None,
    )

    assert [
        row["id"]
        for row in captured["official_snapshot"]["fixtures"]
    ] == [9001]


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


def test_espn_monthly_queries_replace_retired_date_ranges_and_preserve_provenance(monkeypatch):
    """A cross-month window is fetched by month, deduped, and strictly filtered."""
    requests_seen = []

    september = {
        "events": [
            {
                "id": "ucl-sep",
                "date": "2026-09-30T19:00:00Z",
                "competitions": [{
                    "date": "2026-09-30T19:00:00Z",
                    "competitors": [
                        {"homeAway": "away", "team": {"abbreviation": "ARS"}},
                        {"homeAway": "home", "team": {"displayName": "Real Madrid"}},
                    ],
                }],
            }
        ]
    }
    october = {
        "events": [
            september["events"][0],  # Deduped if ESPN repeats an event.
            {
                "id": "ucl-oct",
                "date": "2026-10-14T19:00:00Z",
                "competitions": [{
                    "date": "2026-10-14T19:00:00Z",
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "ARS"}},
                        {"homeAway": "away", "team": {"displayName": "Real Madrid"}},
                    ],
                }],
            },
            {
                "id": "ucl-late",
                "date": "2026-10-31T19:00:00Z",
                "competitions": [{
                    "date": "2026-10-31T19:00:00Z",
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "ARS"}},
                        {"homeAway": "away", "team": {"displayName": "Real Madrid"}},
                    ],
                }],
            },
        ]
    }

    class Response:
        def __init__(self, token):
            self.url = f"https://example.test/scoreboard?dates={token}"
            self.token = token

        def raise_for_status(self):
            return None

        def json(self):
            return september if self.token == "202609" else october

    def fake_get(url, *, params, timeout):
        assert "dates" in params and "-" not in params["dates"]
        assert params["limit"] == "1000"
        assert timeout == 6
        requests_seen.append(params["dates"])
        return Response(params["dates"])

    monkeypatch.setattr(report_time_competition_schedule.requests, "get", fake_get)
    slug, payload, source_url = report_time_competition_schedule._fetch_one(
        provider={"base_url": "https://example.test", "request_timeout_seconds": 6},
        competition_cfg={"slug": "uefa.champions"},
        start_date="20260920",
        end_date="20261018",
    )
    assert slug == "uefa.champions"
    assert requests_seen == ["202609", "202610"]
    assert payload["_retrieval"]["query_granularity"] == "MONTH"
    assert len(payload["events"]) == 3
    assert source_url.endswith("dates=202609")
    rows = report_time_competition_schedule._competition_rows(
        payload=payload,
        competition_cfg={"name": "UEFA Champions League", "category": "CONTINENTAL_CLUB"},
        bootstrap=_bootstrap(),
        floor=datetime(2026, 9, 20, tzinfo=timezone.utc),
        ceiling=datetime(2026, 10, 18, tzinfo=timezone.utc),
        source_url=source_url,
    )
    assert [r["source_native_event_id"] for r in rows] == ["ucl-sep", "ucl-oct"]
    assert rows[0]["source_url"].endswith("dates=202610")  # Deduped last observation.
    assert rows[1]["source_url"].endswith("dates=202610")


def test_espn_month_failure_cannot_claim_complete_schedule(monkeypatch):
    """A missing monthly response cannot be interpreted as zero fixtures."""
    import requests

    calls = []

    class Response:
        def __init__(self, token):
            self.token = token
            self.url = f"https://example.test/scoreboard?dates={token}"

        def raise_for_status(self):
            if self.token == "202610":
                raise requests.HTTPError("HTTP 400")
            
        def json(self):
            return {"events": []}

    def fake_get(url, *, params, timeout):
        calls.append(params["dates"])
        return Response(params["dates"])

    monkeypatch.setattr(report_time_competition_schedule.requests, "get", fake_get)
    result = report_time_competition_schedule.collect_verified_non_pl_schedule(
        bootstrap=_bootstrap(),
        planning_fixtures=[{"kickoff_time": "2026-10-18T14:00:00Z"}],
        report_timestamp="2026-10-11T04:54:00Z",
        config={
            "contract": "REPORT_TIME_COMPETITION_SCHEDULE_V1",
            "provider": {
                "base_url": "https://example.test",
                "lookback_days": 21,
                "max_parallel_requests": 1,
                "request_timeout_seconds": 6,
            },
            "competitions": [{
                "name": "UEFA Champions League",
                "slug": "uefa.champions",
                "category": "CONTINENTAL_CLUB",
            }],
        },
    )
    assert calls == ["202609", "202610"]
    assert result["status"] == "UNAVAILABLE"
    assert result["authority_complete"] is False
    assert result["checks"][0]["status"] == "FAILED"
