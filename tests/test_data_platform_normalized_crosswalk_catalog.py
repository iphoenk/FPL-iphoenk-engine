from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.runtime_v6.artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from src.runtime_v6.crosswalk import apply_verified_crosswalks, load_verified_crosswalks
from src.runtime_v6.source_parsers import parse_espn, parse_fotmob, parse_solio, parse_vaastav


def _source(source_id: str, request_id: str, *, json_payload=None, body=None, semantic_class=None):
    row = {
        "source_id": source_id,
        "source_name": source_id,
        "checked_at": "2026-09-06T15:25:38+00:00",
        "effective_state": "LIVE_CHANGED",
        "current_run_action": "FETCHED",
        "data": {
            request_id: {
                "json": json_payload,
                "body": body,
                "sha256": hashlib.sha256((body or json.dumps(json_payload or {})).encode()).hexdigest(),
            }
        },
    }
    if semantic_class:
        row["semantic_class"] = semantic_class
        row["model_author"] = source_id
    return row


def test_verified_fotmob_crosswalk_is_complete_unique_and_no_fuzzy_matching():
    config = load_verified_crosswalks()
    rows = config["sources"]["fotmob"]["teams"]
    assert len(rows) == 20
    assert len({row["source_native_id"] for row in rows}) == 20
    assert {row["official_fpl_team_id"] for row in rows} == set(range(1, 21))
    assert config["fuzzy_matching_allowed"] is False
    assert config["governance"]["silent_name_matching_allowed"] is False


def test_fotmob_source_specific_parser_preserves_native_team_ids():
    source = _source(
        "fotmob",
        "league",
        json_payload={
            "table": [
                {"data": {"table": {"all": [
                    {"id": 9825, "name": "Arsenal", "shortName": "Arsenal", "pts": 6},
                    {"id": 8456, "name": "Manchester City", "shortName": "Man City", "pts": 9},
                ]}}}
            ]
        },
    )
    parsed = parse_fotmob(source)
    assert parsed["semantic_class"] == "NORMALIZED_FACT"
    assert parsed["record_counts"]["teams"] == 2
    assert [row["source_native_id"] for row in parsed["teams"]] == [9825, 8456]
    assert all(row["identity_status"] == "UNMAPPED" for row in parsed["teams"])
    assert parsed["governance"]["cross_source_aggregation"] is False


def test_espn_source_specific_parser_emits_native_teams_and_fixture_without_guessing():
    source = _source(
        "espn",
        "scoreboard",
        json_payload={
            "events": [{
                "id": "401",
                "date": "2026-09-06T13:00Z",
                "name": "Manchester United at Everton",
                "competitions": [{
                    "id": "401",
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "368", "displayName": "Everton", "abbreviation": "EVE"}},
                        {"homeAway": "away", "team": {"id": "360", "displayName": "Manchester United", "abbreviation": "MAN"}},
                    ],
                }],
            }]
        },
    )
    parsed = parse_espn(source)
    assert parsed["record_counts"] == {"players": 0, "teams": 2, "fixtures": 1, "events": 0}
    fixture = parsed["fixtures"][0]
    assert fixture["home_source_native_team_id"] == 368
    assert fixture["away_source_native_team_id"] == 360
    assert fixture["identity_status"] == "UNMAPPED"
    assert fixture["official_fpl_fixture_id"] is None


def test_vaastav_parser_and_crosswalk_require_id_team_and_kickoff_exactness():
    players_csv = "id,code,first_name,second_name\n42,123,Test,Player\n"
    fixtures_csv = "id,event,kickoff_time,team_h,team_a,finished,started\n9,2,2026-09-01T15:00:00Z,1,2,False,False\n"
    source = {
        "source_id": "vaastav_fpl",
        "source_name": "Vaastav",
        "checked_at": "2026-09-06T15:25:38+00:00",
        "effective_state": "LIVE_CHANGED",
        "current_run_action": "FETCHED",
        "data": {
            "players_raw": {"body": players_csv, "sha256": "p"},
            "fixtures": {"body": fixtures_csv, "sha256": "f"},
        },
    }
    parsed = parse_vaastav(source)
    identity = {
        "mappings": {
            "42": {"links": {"vaastav_fpl": {"source_native_id": 42, "verification_status": "EXACT"}}}
        },
        "entity_bridges": {
            "team": {
                "canonical_team_count": 2,
                "mappings": {
                    "1": {"official_fpl_team_id": 1, "links": {}},
                    "2": {"official_fpl_team_id": 2, "links": {}},
                },
                "coverage": {},
            },
            "fixture": {
                "canonical_fixture_count": 1,
                "mappings": {
                    "9": {
                        "official_fpl_fixture_id": 9,
                        "official_fpl_team_h_id": 1,
                        "official_fpl_team_a_id": 2,
                        "kickoff_time": "2026-09-01T15:00:00Z",
                        "links": {},
                    }
                },
                "coverage": {},
            },
        },
    }
    enriched, datasets, report = apply_verified_crosswalks(identity, {"vaastav_fpl": parsed})
    assert datasets["vaastav_fpl"]["players"][0]["official_fpl_element_id"] == 42
    assert datasets["vaastav_fpl"]["fixtures"][0]["official_fpl_fixture_id"] == 9
    assert datasets["vaastav_fpl"]["fixtures"][0]["identity_status"] == "EXACT"
    assert report["fixture_coverage"]["vaastav_fpl"]["mapped_fixture_count"] == 1
    assert enriched["entity_bridges"]["fixture"]["mappings"]["9"]["links"]["vaastav_fpl"]["joinable"] is True

    bad = parse_vaastav({**source, "data": {**source["data"], "fixtures": {"body": fixtures_csv.replace(",1,2,", ",2,1,"), "sha256": "bad"}}})
    _, bad_datasets, _ = apply_verified_crosswalks(identity, {"vaastav_fpl": bad})
    assert bad_datasets["vaastav_fpl"]["fixtures"][0]["official_fpl_fixture_id"] is None
    assert bad_datasets["vaastav_fpl"]["fixtures"][0]["identity_status"] == "UNMAPPED"


def test_solio_parser_keeps_model_authorship_upstream_and_does_not_create_identity_join():
    source = _source(
        "solio_analytics",
        "latest",
        semantic_class="UPSTREAM_MODEL_SIGNAL",
        json_payload={
            "generatedAt": "2026-09-06T15:04:41Z",
            "gameweek": 4,
            "deadlineIso": "2026-09-12T12:30:00Z",
            "topProjected": [{"name": "Haaland", "team": "MCI", "position": "FWD", "prPoints": 5.9}],
        },
    )
    parsed = parse_solio(source)
    assert parsed["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert parsed["model_author"] == "solio_analytics"
    assert parsed["v6_computation"] == "NONE"
    assert parsed["players"][0]["source_native_id"] is None
    assert parsed["players"][0]["identity_status"] == "UNMAPPED"
    assert parsed["players"][0]["official_fpl_element_id"] is None


def test_artifact_catalog_is_deterministic_non_recursive_and_detects_tamper(tmp_path: Path):
    (tmp_path / "current").mkdir(parents=True)
    (tmp_path / "evidence").mkdir(parents=True)
    (tmp_path / "health").mkdir(parents=True)
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    (tmp_path / "current" / "one.json").write_text(json.dumps({"source_id": "one", "record_count": 1}), encoding="utf-8")
    (tmp_path / "health" / "publish_integrity.json").write_text(json.dumps({"old": True}), encoding="utf-8")

    first = refresh_artifact_catalog(tmp_path)
    assert first["record_count"] == 2
    assert all(not row["path"].endswith("artifact_catalog.json") for row in first["artifacts"])
    assert all(not row["path"].endswith("publish_integrity.json") for row in first["artifacts"])
    assert validate_artifact_catalog(tmp_path)["valid"] is True

    second = refresh_artifact_catalog(tmp_path)
    assert second["catalog_sha256"] == first["catalog_sha256"]
    (tmp_path / "current" / "one.json").write_text(json.dumps({"source_id": "one", "tampered": True}), encoding="utf-8")
    report = validate_artifact_catalog(tmp_path)
    assert report["valid"] is False
    assert any("artifact_catalog_sha_mismatch" in error for error in report["errors"])
