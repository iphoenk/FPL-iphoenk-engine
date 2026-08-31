from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import src.sources.manager as manager
from src.sources.base import SourceResult, SourceSpec
from src.sources.manager import _disagreement_states, _reconcile_observations
from src.sources.observations import ChallengerObservation

NOW = "2026-08-26T21:00:00+00:00"


def test_available_observation_cannot_have_missing_value():
    with pytest.raises(ValueError):
        ChallengerObservation(
            source_id="fffix",
            capability="price_prediction",
            value=None,
            source_url="https://www.fantasyfootballfix.com/",
            fetched_at=NOW,
            observed_at=NOW,
            ttl_seconds=1800,
            parser_version="test-v1",
            subject={"player": "Example"},
        )


def _prior_row(observed_at: str, ttl: int) -> dict:
    return ChallengerObservation(
        source_id="fffix",
        capability="price_prediction",
        value={"player": "Bowen", "direction": "RISE"},
        source_url="https://www.fantasyfootballfix.com/",
        fetched_at=observed_at,
        observed_at=observed_at,
        ttl_seconds=ttl,
        parser_version="test-v1",
        subject={"player": "Bowen"},
    ).as_dict()


def test_prior_structured_observation_becomes_explicitly_stale():
    rows, counts = _reconcile_observations(
        {"schema_version": 2, "observations": [_prior_row("2026-08-26T19:00:00+00:00", 60)]},
        [],
        datetime(2026, 8, 26, 21, 0, tzinfo=timezone.utc),
    )
    assert counts["fresh"] == 0
    assert counts["stale"] == 1
    assert rows[0]["status"] == "STALE"
    assert rows[0]["stale"] is True


def test_recent_prior_becomes_last_known_good_but_not_current():
    rows, counts = _reconcile_observations(
        {"schema_version": 2, "observations": [_prior_row("2026-08-26T20:55:00+00:00", 1800)]},
        [],
        datetime(2026, 8, 26, 21, 0, tzinfo=timezone.utc),
    )
    assert counts["cached_last_known_good"] == 1
    assert rows[0]["status"] == "CACHED_LAST_KNOWN_GOOD"
    assert rows[0]["stale"] is True


def test_cross_source_direction_disagreement_is_explicit():
    fffix = _prior_row(NOW, 1800)
    ffhub = ChallengerObservation(
        source_id="ffhub",
        capability="price_prediction",
        value={"player": "Bowen", "direction": "FALL"},
        source_url="https://www.fantasyfootballhub.co.uk/",
        fetched_at=NOW,
        observed_at=NOW,
        ttl_seconds=1800,
        parser_version="test-v1",
        subject={"player": "Bowen"},
    ).as_dict()
    states = _disagreement_states([fffix, ffhub])
    assert states == [{
        "subject_key": "bowen",
        "player": "Bowen",
        "capability": "price_prediction",
        "state": "DISAGREEMENT",
        "providers": ["fffix", "ffhub"],
        "directions": ["FALL", "RISE"],
    }]


def test_official_health_endpoints_are_registry_driven(tmp_path):
    (tmp_path / "health.json").write_text(json.dumps({
        "alpha": {"status": "LIVE", "latency_ms": 4},
        "beta": {"status": "LIVE", "latency_ms": 9},
        "ignored": {"status": "DEGRADED", "latency_ms": 1},
    }))
    spec = SourceSpec(
        "official_fpl",
        "Official FPL",
        "AUTHORITATIVE",
        1,
        True,
        True,
        "runtime_official",
        ("prices",),
        {"health_endpoints": ["alpha", "beta"]},
    )
    result = manager._official_result(spec, tmp_path)
    assert result.status == "LIVE"
    assert result.reachable is True
    assert result.latency_ms == 9.0
    assert result.detail["critical_endpoints"] == {"alpha": "LIVE", "beta": "LIVE"}


def test_official_health_missing_registry_endpoints_fails_closed(tmp_path):
    (tmp_path / "health.json").write_text("{}")
    spec = SourceSpec("official_fpl", "Official FPL", "AUTHORITATIVE", 1, True, True, "runtime_official", ("prices",), {})
    result = manager._official_result(spec, tmp_path)
    assert result.status == "DEGRADED"
    assert result.reachable is False
    assert result.detail["registry_error"] == "missing health_endpoints"


def test_weather_artifact_path_is_registry_driven(tmp_path):
    payload = {
        "fixture_count": 3,
        "available_count": 2,
        "material_count": 1,
        "governance": {"advisory_only": True},
    }
    (tmp_path / "custom-weather.json").write_text(json.dumps(payload))
    spec = SourceSpec(
        "open_meteo",
        "Open-Meteo",
        "ENRICHMENT",
        3,
        True,
        False,
        "weather_artifact",
        ("fixture_weather",),
        {"artifact_paths": ["custom-weather.json"]},
    )
    result = manager._weather_artifact_result(spec, tmp_path)
    assert result.status == "LIVE"
    assert result.reachable is True
    assert result.detail["artifact"] == "custom-weather.json"
    assert result.observation_count == 2


def test_challenger_exception_is_isolated_and_nonblocking(monkeypatch, tmp_path):
    official = SourceSpec("official_fpl", "Official FPL", "AUTHORITATIVE", 1, True, True, "runtime_official", ("prices", "price_prediction"), {"health_endpoints": ["bootstrap"]})
    challenger = SourceSpec("fffix", "Fantasy Football Fix", "CHALLENGER", 2, True, False, "public_web", ("price_prediction",), {})
    monkeypatch.setattr(manager, "source_specs", lambda: (official, challenger))
    monkeypatch.setattr(manager, "load_source_registry", lambda: {"policy": {"default_timeout_seconds": 0.1, "max_workers": 2}})
    monkeypatch.setattr(manager, "registry_integrity", lambda: {"integrity_ok": True})

    def fake_run(spec, data_dir, timeout):
        if spec.source_id == "fffix":
            raise RuntimeError("challenger unavailable")
        return SourceResult("official_fpl", "LIVE", True, 1.0, 0, {"prices": "AUTHORITATIVE_NATIVE", "price_prediction": "AUTHORITATIVE_NATIVE"}, {})

    monkeypatch.setattr(manager, "_run_one", fake_run)
    result = manager.collect_sources(tmp_path)
    assert result["decision_blocking"] is False
    assert result["overall"] == "AMBER"
    fffix = next(row for row in result["sources"] if row["id"] == "fffix")
    assert fffix["status"] == "UNAVAILABLE"
    assert fffix["detail"]["isolated_failure"] is True
