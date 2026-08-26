from __future__ import annotations

from datetime import datetime, timezone

import pytest

import src.sources.manager as manager
from src.sources.base import SourceResult, SourceSpec
from src.sources.livefpl import parse_price_observations as parse_livefpl
from src.sources.manager import _disagreement_states, _reconcile_observations
from src.sources.observations import ChallengerObservation, OBSERVATION_CONTRACT
from src.sources.onefpl import parse_price_observations as parse_onefpl

NOW = "2026-08-26T21:00:00+00:00"


def test_livefpl_price_parser_requires_observed_values():
    html = "<html><body>Bowen FWD £7.8 59.1% 180.03% Tonight +10.53%</body></html>"
    rows = parse_livefpl(html, source_url="https://www.livefpl.net/prices", fetched_at=NOW, ttl_seconds=1800)
    assert len(rows) == 1
    row = rows[0]
    assert row["contract"] == OBSERVATION_CONTRACT
    assert row["provider"] == "livefpl"
    assert row["capability"] == "price_prediction"
    assert row["value"]["player"] == "Bowen"
    assert row["value"]["direction"] == "RISE"
    assert row["value"]["predicted_pct"] == pytest.approx(180.03)
    assert row["value"]["per_hour_pct"] == pytest.approx(10.53)
    assert row["stale"] is False


def test_onefpl_price_parser_and_loading_page_no_fabrication():
    html = "<html><body>SilvaDEF BOU BOU£5.0m 1.3%Drop risk</body></html>"
    rows = parse_onefpl(html, source_url="https://onefpl.com/prices", fetched_at=NOW, ttl_seconds=1800)
    assert len(rows) == 1
    assert rows[0]["provider"] == "onefpl"
    assert rows[0]["value"]["direction"] == "FALL"
    assert rows[0]["value"]["pressure_pct"] == pytest.approx(1.3)
    assert parse_onefpl("<html><body>Loading FPL tool...</body></html>", source_url="https://onefpl.com/prices", fetched_at=NOW, ttl_seconds=1800) == []


def test_available_observation_cannot_have_missing_value():
    with pytest.raises(ValueError):
        ChallengerObservation(
            source_id="onefpl",
            capability="price_prediction",
            value=None,
            source_url="https://onefpl.com/prices",
            fetched_at=NOW,
            observed_at=NOW,
            ttl_seconds=1800,
            parser_version="test-v1",
            subject={"player": "Example"},
        )


def _prior_row(observed_at: str, ttl: int) -> dict:
    return ChallengerObservation(
        source_id="livefpl",
        capability="price_prediction",
        value={"player": "Bowen", "direction": "RISE"},
        source_url="https://www.livefpl.net/prices",
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
    live = _prior_row(NOW, 1800)
    one = ChallengerObservation(
        source_id="onefpl",
        capability="price_prediction",
        value={"player": "Bowen", "direction": "FALL"},
        source_url="https://onefpl.com/prices",
        fetched_at=NOW,
        observed_at=NOW,
        ttl_seconds=1800,
        parser_version="test-v1",
        subject={"player": "Bowen"},
    ).as_dict()
    states = _disagreement_states([live, one])
    assert states == [{
        "subject_key": "bowen",
        "player": "Bowen",
        "capability": "price_prediction",
        "state": "DISAGREEMENT",
        "providers": ["livefpl", "onefpl"],
        "directions": ["FALL", "RISE"],
    }]


def test_challenger_exception_is_isolated_and_nonblocking(monkeypatch, tmp_path):
    official = SourceSpec("official_fpl", "Official FPL", "AUTHORITATIVE", 1, True, True, "runtime_official", ("prices",), {})
    challenger = SourceSpec("livefpl", "LiveFPL", "CHALLENGER", 2, True, False, "livefpl", ("price_prediction",), {})
    monkeypatch.setattr(manager, "source_specs", lambda: (official, challenger))
    monkeypatch.setattr(manager, "load_source_registry", lambda: {"policy": {"default_timeout_seconds": 0.1, "max_workers": 2}})
    monkeypatch.setattr(manager, "registry_integrity", lambda: {"integrity_ok": True})

    def fake_run(spec, data_dir, timeout):
        if spec.source_id == "livefpl":
            raise RuntimeError("challenger unavailable")
        return SourceResult("official_fpl", "LIVE", True, 1.0, 0, {"prices": "AUTHORITATIVE_NATIVE"}, {})

    monkeypatch.setattr(manager, "_run_one", fake_run)
    result = manager.collect_sources(tmp_path)
    assert result["decision_blocking"] is False
    assert result["overall"] == "AMBER"
    live = next(row for row in result["sources"] if row["id"] == "livefpl")
    assert live["status"] == "UNAVAILABLE"
    assert live["detail"]["isolated_failure"] is True
