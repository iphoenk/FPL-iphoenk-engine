from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.engines import competitive_load


def _write(path, observations):
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "COMPETITIVE_LOAD_OBSERVATIONS_V1",
                "observations": observations,
            }
        ),
        encoding="utf-8",
    )


def _valid_row(now: datetime, **overrides):
    row = {
        "element": 1,
        "competition": "UEFA Champions League",
        "match_time": (now - timedelta(hours=24)).isoformat(),
        "venue": "AWAY",
        "started": True,
        "minutes": 90,
        "sub_on_minute": None,
        "sub_off_minute": None,
        "extra_time_minutes": 0,
        "travel_context": "EUROPEAN_AWAY",
        "international": False,
        "long_haul": False,
        "source": "UEFA match centre",
        "source_url": "https://www.uefa.com/example",
        "verification_level": "OFFICIAL_COMPETITION",
        "verified": True,
    }
    row.update(overrides)
    return row


def test_verified_official_non_pl_observation_is_accepted(tmp_path, monkeypatch):
    now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    input_path = tmp_path / "competitive_load_observations.json"
    monkeypatch.setattr(competitive_load, "OBSERVATIONS", input_path)
    _write(input_path, [_valid_row(now)])

    rows, audit = competitive_load._validated_optional_observations({1}, now=now)

    assert audit["status"] == "VALIDATED"
    assert audit["accepted_rows"] == 1
    assert audit["rejected_rows"] == 0
    assert rows[1][0]["verification_level"] == "OFFICIAL_COMPETITION"
    assert rows[1][0]["source_url"].startswith("https://")


def test_unverified_or_missing_provenance_rows_are_rejected(tmp_path, monkeypatch):
    now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    input_path = tmp_path / "competitive_load_observations.json"
    monkeypatch.setattr(competitive_load, "OBSERVATIONS", input_path)
    _write(
        input_path,
        [
            _valid_row(now, verified=False),
            _valid_row(now, source_url=""),
            _valid_row(now, verification_level="COMMUNITY_ONLY"),
        ],
    )

    rows, audit = competitive_load._validated_optional_observations({1}, now=now)

    assert rows == {}
    assert audit["accepted_rows"] == 0
    assert audit["rejected_rows"] == 3
    assert audit["rejection_reasons"]["NOT_VERIFIED"] == 1
    assert audit["rejection_reasons"]["INVALID_SOURCE_URL"] == 1
    assert audit["rejection_reasons"]["INVALID_VERIFICATION_LEVEL"] == 1


def test_future_stale_and_unknown_player_rows_do_not_affect_load(tmp_path, monkeypatch):
    now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    input_path = tmp_path / "competitive_load_observations.json"
    monkeypatch.setattr(competitive_load, "OBSERVATIONS", input_path)
    _write(
        input_path,
        [
            _valid_row(now, match_time=(now + timedelta(hours=2)).isoformat()),
            _valid_row(now, match_time=(now - timedelta(days=30)).isoformat()),
            _valid_row(now, element=9999),
        ],
    )

    rows, audit = competitive_load._validated_optional_observations({1}, now=now)

    assert rows == {}
    assert audit["accepted_rows"] == 0
    assert audit["stale_rows"] == 1
    assert audit["rejection_reasons"]["FUTURE_MATCH"] == 1
    assert audit["rejection_reasons"]["UNKNOWN_ELEMENT"] == 1


def test_duplicate_match_prefers_higher_verification_precedence(tmp_path, monkeypatch):
    now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    input_path = tmp_path / "competitive_load_observations.json"
    monkeypatch.setattr(competitive_load, "OBSERVATIONS", input_path)
    match_time = (now - timedelta(hours=24)).isoformat()
    _write(
        input_path,
        [
            _valid_row(
                now,
                match_time=match_time,
                source="crosschecked",
                source_url="https://example.com/crosscheck",
                verification_level="CROSSCHECKED_OFFICIAL",
                minutes=80,
            ),
            _valid_row(
                now,
                match_time=match_time,
                source="official club",
                source_url="https://club.example.com/match",
                verification_level="OFFICIAL_CLUB",
                minutes=90,
            ),
        ],
    )

    rows, audit = competitive_load._validated_optional_observations({1}, now=now)

    assert audit["accepted_rows"] == 1
    assert audit["deduplicated_rows"] == 1
    assert rows[1][0]["verification_level"] == "OFFICIAL_CLUB"
    assert rows[1][0]["minutes"] == 90


def test_native_premier_league_rows_cannot_be_injected_as_external_evidence(tmp_path, monkeypatch):
    now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    input_path = tmp_path / "competitive_load_observations.json"
    monkeypatch.setattr(competitive_load, "OBSERVATIONS", input_path)
    _write(input_path, [_valid_row(now, competition="Premier League")])

    rows, audit = competitive_load._validated_optional_observations({1}, now=now)

    assert rows == {}
    assert audit["rejection_reasons"]["INVALID_OR_NATIVE_COMPETITION"] == 1
