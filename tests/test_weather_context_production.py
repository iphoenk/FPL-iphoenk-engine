from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.engines import framework_health_service
from src.engines.weather_context import build_attribution, build_weather_context, build_weather_health
from src.sources.weather_open_meteo import _select_evidence, _severity

ROOT = Path(__file__).resolve().parents[1]


def _cfg() -> dict:
    return json.loads((ROOT / "config" / "intelligence" / "weather_context.json").read_text(encoding="utf-8"))


def _weather_observation(*, severity: str = "ADVERSE") -> dict:
    return {
        "evidence_kind": "LIVE_OBSERVED",
        "fetched_at": "2026-08-30T15:01:00+00:00",
        "observed_at": "2026-08-30T15:00:00+00:00",
        "evidence_timestamp": "2026-08-30T15:00:00+00:00",
        "severity": severity,
        "signals": ["precipitation_intensity"],
        "weather": {
            "temperature_c": 16.0,
            "precipitation_probability_pct": None,
            "precipitation_mm_h": 5.0,
            "wind_speed_kmh": 12.0,
            "wind_gust_kmh": 20.0,
            "weather_code": 63,
        },
    }


def test_precipitation_probability_is_not_precipitation_intensity() -> None:
    cfg = _cfg()
    severity, signals = _severity(
        {
            "temperature_c": 15.0,
            "precipitation_probability_pct": 100,
            "precipitation_mm_h": 0.0,
            "wind_speed_kmh": 0.0,
            "wind_gust_kmh": 0.0,
            "weather_code": 61,
        },
        cfg,
    )
    assert severity == "NORMAL"
    assert "precipitation_intensity" not in signals
    assert cfg["governance"]["rain_probability_is_not_rain_intensity"] is True


def test_live_observation_supersedes_forecast() -> None:
    cfg = _cfg()
    kickoff = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)
    now = kickoff + timedelta(minutes=25)
    forecast = {
        "evidence_kind": "FORECAST",
        "fetched_at": (kickoff - timedelta(hours=1)).isoformat(),
        "forecast_for": kickoff.isoformat(),
        "evidence_timestamp": kickoff.isoformat(),
        "severity": "NORMAL",
        "signals": [],
        "weather": {"precipitation_probability_pct": 80, "precipitation_mm_h": 0.0},
    }
    live = {
        **_weather_observation(),
        "observed_at": (kickoff + timedelta(minutes=20)).isoformat(),
        "evidence_timestamp": (kickoff + timedelta(minutes=20)).isoformat(),
        "fetched_at": (kickoff + timedelta(minutes=21)).isoformat(),
    }
    selected, precedence, state, freshness = _select_evidence(
        [forecast, live], kickoff, now, cfg, started=True, finished=False
    )
    assert selected == live
    assert precedence == "LIVE_OBSERVED"
    assert state == "LIVE_OBSERVED"
    assert freshness == "OBSERVED"


def test_isolated_incident_does_not_establish_weather_causality() -> None:
    result = build_attribution(
        [
            {
                "fixture_id": 1,
                "incident_type": "SLIP_LOSS_OF_FOOTING",
                "evidence_class": "OBSERVED_MATCH_EVIDENCE",
                "observed_at": "2026-08-30T15:10:00+00:00",
                "source": "verified_match_report",
            }
        ],
        _cfg(),
    )
    assert result["pattern_confidence"] == "LOW"
    assert result["relationship_label"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert result["causality_claimed"] is False
    assert result["incidents"][0]["attribution_confidence"] == "LOW"
    assert result["incidents"][0]["causality_claimed"] is False
    assert result["sustainability"]["automatic_future_projection_increase"] is False


def test_repeated_incidents_may_raise_advisory_but_never_causality() -> None:
    incidents = [
        {
            "fixture_id": 1,
            "incident_type": "MISCONTROL",
            "evidence_class": "OBSERVED_MATCH_EVIDENCE",
            "observed_at": f"2026-08-30T15:{10 + index:02d}:00+00:00",
            "source": "verified_match_report",
        }
        for index in range(3)
    ]
    result = build_attribution(incidents, _cfg())
    assert result["pattern_confidence"] == "MATERIAL_ADVISORY"
    assert result["repeated_patterns"] == ["MISCONTROL"]
    assert result["relationship_label"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert result["causality_claimed"] is False


def test_weather_has_no_direct_projection_or_decision_mutation_path() -> None:
    cfg = _cfg()
    governance = cfg["governance"]
    forbidden = {
        "may_directly_change_xpts",
        "may_directly_change_xmins",
        "may_directly_change_starting_xi",
        "may_directly_change_bench_order",
        "may_directly_change_captaincy",
        "may_directly_change_vice_captaincy",
        "may_directly_change_transfer_decision",
        "may_directly_change_hit_decision",
        "may_directly_change_chip_decision",
        "may_directly_change_watchlist_membership",
    }
    assert all(governance[key] is False for key in forbidden)

    services = json.loads((ROOT / "config" / "v3_service_registry.json").read_text(encoding="utf-8"))["services"]
    assert "weather_context" in services["prediction"]["depends_on"]
    weather_artifacts = {"fixture_weather.json", "weather_context.json", "weather_context_health.json"}
    assert weather_artifacts.isdisjoint(set(services["prediction"]["inputs"]))
    assert weather_artifacts.isdisjoint(set(services["lineup_governance"]["inputs"]))
    assert weather_artifacts.isdisjoint(set(services["watchlist"]["inputs"]))
    assert services["weather_context"]["artifacts"] == ["weather_context.json", "weather_context_health.json"]


def test_post_match_attribution_remains_possible_contributing_factor() -> None:
    selected = _weather_observation()
    weather = {
        "provider": "open_meteo",
        "fixtures": [
            {
                "fixture_id": 101,
                "event": 2,
                "home_team_id": 1,
                "away_team_id": 2,
                "home_team": "Home",
                "away_team": "Away",
                "kickoff_time": "2026-08-30T15:00:00+00:00",
                "venue": "Ground",
                "started": True,
                "finished": True,
                "selected_evidence": selected,
                "current": selected,
                "evidence_state": "POST_MATCH_RECONCILED",
                "evidence_precedence": "CLOSEST_TO_KICKOFF_OBSERVATION",
                "freshness": "OBSERVED",
            }
        ],
    }
    incidents = {
        "incidents": [
            {
                "fixture_id": 101,
                "incident_type": "SLIP_LOSS_OF_FOOTING",
                "evidence_class": "OBSERVED_MATCH_EVIDENCE",
                "observed_at": "2026-08-30T15:20:00+00:00",
                "player": "Defender",
                "team": "Away",
                "description": "Loss of footing before the goal",
                "source": "verified_match_report",
                "football_event": {
                    "event_type": "GOAL",
                    "player": "Bruno",
                    "verified": True,
                },
                "alternative_explanations": ["defender_balance"],
            }
        ]
    }
    context, health = build_weather_context(weather, {"teams": {}}, {"players": {}}, incidents, _cfg())
    fixture = context["fixtures"][0]
    attribution = fixture["attribution"]
    incident = attribution["incidents"][0]
    assert fixture["post_match_reconciled"] is True
    assert fixture["evidence_state"] == "POST_MATCH_RECONCILED"
    assert health["status"] == "PASS"
    assert attribution["relationship_label"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert attribution["causality_claimed"] is False
    assert incident["evidence_class"] == "OBSERVED_MATCH_EVIDENCE"
    assert incident["football_event"]["evidence_class"] == "FACT"
    assert incident["relationship_to_weather"] == "POSSIBLE_CONTRIBUTING_FACTOR"
    assert "defender_balance" in incident["alternative_explanations"]
    assert attribution["sustainability"]["automatic_future_projection_increase"] is False


def test_weather_context_health_statuses_and_framework_propagation(tmp_path, monkeypatch) -> None:
    fresh = {
        "fixture_id": 1,
        "selected_evidence": _weather_observation(severity="NORMAL"),
        "freshness": "OBSERVED",
    }
    stale = {
        "fixture_id": 2,
        "selected_evidence": {
            "evidence_kind": "FORECAST",
            "severity": "NORMAL",
            "signals": [],
            "weather": {},
        },
        "freshness": "STALE",
    }
    missing = {"fixture_id": 3, "selected_evidence": None, "freshness": "UNAVAILABLE"}

    pass_health = build_weather_health({"fixtures": [fresh]})
    stale_health = build_weather_health({"fixtures": [stale]})
    unavailable_health = build_weather_health({"fixtures": [missing]})
    partial_health = build_weather_health({"fixtures": [fresh, missing]})
    assert pass_health["status"] == "PASS" and pass_health["tactical_context_complete"] is True
    assert stale_health["status"] == "STALE" and stale_health["tactical_context_complete"] is False
    assert unavailable_health["status"] == "UNAVAILABLE" and unavailable_health["tactical_context_complete"] is False
    assert partial_health["status"] == "PARTIAL" and partial_health["tactical_context_complete"] is False

    monkeypatch.setattr(framework_health_service, "DATA", tmp_path)
    (tmp_path / "weather_context_health.json").write_text(json.dumps(partial_health), encoding="utf-8")
    propagated = framework_health_service._weather_context_health()
    assert propagated["status"] == "PARTIAL"
    assert propagated["tactical_context_complete"] is False
    assert propagated["decision_blocking"] is False
    assert set(propagated["allowed_statuses"]) == {"PASS", "PARTIAL", "STALE", "UNAVAILABLE"}


def test_weather_domain_and_publish_contract_are_canonical() -> None:
    domains = json.loads((ROOT / "config" / "runtime" / "execution_domains.json").read_text(encoding="utf-8"))
    publish = json.loads((ROOT / "config" / "runtime" / "runtime_publish_registry.json").read_text(encoding="utf-8"))
    contracts = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text(encoding="utf-8"))

    assert domains["domain_count"] == 11
    assert domains["canonical_phases"]["ENRICH"] == ["football_context", "market_context"]
    assert "weather_context" in domains["domains"]["football_context"]["capabilities"]
    assert "weather_context" not in domains["domains"]
    assert domains["domains"]["prediction"]["depends_on"] == ["football_context"]
    assert domains["policy"]["weather_context_does_not_add_process_startup_boundary"] is True
    assert {"weather_context.json", "weather_context_health.json"} <= set(publish["hydrate_paths"])
    assert {"weather_context.json", "weather_context_health.json"} <= set(publish["publish_paths"])
    assert contracts["contracts"]["fixture_weather.json"]["equals"]["schema_version"] == 2
    assert contracts["contracts"]["fixture_weather.json"]["equals"]["model"] == "weather_context_governed_v2"
