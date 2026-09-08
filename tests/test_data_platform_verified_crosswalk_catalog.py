from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.runtime_v6.artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from src.runtime_v6.source_native import build_source_native_datasets
from src.runtime_v6.verified_crosswalks import (
    build_verified_crosswalk_report,
    enrich_verified_external_crosswalks,
    load_verified_crosswalks,
)


def _identity_teams() -> dict:
    return {
        "entity_bridges": {
            "team": {
                "canonical_team_count": 20,
                "mappings": {
                    str(team_id): {
                        "official_fpl_team_id": team_id,
                        "links": {"official_fpl": {"status": "EXACT", "source_native_id": team_id}},
                    }
                    for team_id in range(1, 21)
                },
                "coverage": {},
            }
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }


def _fotmob_result() -> dict:
    config = load_verified_crosswalks()
    rows = [
        {"id": mapping["source_native_id"], "name": f"Team {mapping['official_fpl_team_id']}"}
        for mapping in config["sources"]["fotmob"]["teams"]
    ]
    matches = []
    for index in range(0, len(rows), 2):
        home = rows[index]
        away = rows[index + 1]
        matches.append(
            {
                "id": 1000 + index,
                "utcTime": "2026-09-12T12:30:00Z",
                "home": {"id": home["id"], "name": home["name"]},
                "away": {"id": away["id"], "name": away["name"]},
            }
        )
    return {
        "source_id": "fotmob",
        "source_name": "FotMob",
        "health": "GREEN",
        "effective_state": "LIVE_CHANGED",
        "checked_at": "2026-09-06T15:25:38+00:00",
        "current_run_action": "FETCHED",
        "data": {
            "league": {
                "sha256": "abc",
                "json": {
                    "details": {"id": 47, "name": "Premier League", "selectedSeason": "2026/2027"},
                    "table": [{"data": {"table": {"all": rows}}}],
                    "matches": {"allMatches": matches},
                },
            }
        },
    }


def test_verified_fotmob_team_crosswalk_is_complete_unique_and_no_fuzzy_join():
    config = load_verified_crosswalks()
    rows = config["sources"]["fotmob"]["teams"]
    assert len(rows) == 20
    assert len({row["source_native_id"] for row in rows}) == 20
    assert {row["official_fpl_team_id"] for row in rows} == set(range(1, 21))
    assert config["fuzzy_matching_allowed"] is False
    assert config["governance"]["silent_name_matching_allowed"] is False


def test_fotmob_crosswalk_requires_current_native_ids_and_reaches_green_at_20_of_20():
    results = {"fotmob": _fotmob_result()}
    enriched = enrich_verified_external_crosswalks(_identity_teams(), results)
    coverage = enriched["entity_bridges"]["team"]["coverage"]["fotmob"]
    assert coverage["mapped_team_count"] == 20
    assert coverage["canonical_team_count"] == 20
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["identity_health"] == "GREEN"
    assert coverage["join_allowed"] is True
    assert enriched["entity_bridges"]["team"]["mappings"]["1"]["links"]["fotmob"]["status"] == "VERIFIED_MANUAL"
    assert enriched["governance"]["verified_manual_crosswalk_name_matching"] is False


def test_fotmob_source_native_normalizer_consumes_verified_team_links_without_name_matching():
    results = {"fotmob": _fotmob_result()}
    identity = enrich_verified_external_crosswalks(_identity_teams(), results)
    dataset = build_source_native_datasets(results, identity)["fotmob"]
    teams = dataset["record_groups"]["teams"]
    assert len(teams) == 20
    assert all(row["official_team_id"] is not None for row in teams)
    assert all(row["identity_status"] == "VERIFIED_MANUAL" for row in teams)
    assert dataset["semantic_class"] == "NORMALIZED_FACT"
    assert dataset["governance"]["cross_source_synthesis"] is False


def test_verified_crosswalk_report_is_identity_only_and_preserves_zero_decision_authority():
    results = {"fotmob": _fotmob_result()}
    identity = enrich_verified_external_crosswalks(_identity_teams(), results)
    report = build_verified_crosswalk_report(identity, results)
    assert report["semantic_class"] == "IDENTITY_CROSSWALK"
    assert report["record_count"] == 20
    assert report["fuzzy_matching_allowed"] is False
    assert report["sources"]["fotmob"]["current_identity_coverage"]["identity_health"] == "GREEN"
    assert report["governance"]["decision_authority"] == "NONE"
    assert report["governance"]["prediction_authority"] == "NONE"
    assert report["governance"]["optimizer_authority"] == "NONE"


def test_artifact_catalog_is_non_recursive_deterministic_and_tamper_evident(tmp_path: Path):
    (tmp_path / "current").mkdir(parents=True)
    (tmp_path / "evidence").mkdir(parents=True)
    (tmp_path / "health").mkdir(parents=True)
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    (tmp_path / "current" / "one.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "source_id": "one",
                "checked_at": "2026-09-08T07:00:00+00:00",
                "current_run_action": "FETCHED",
                "availability": "AVAILABLE",
                "record_count": 1,
                "attempts": [
                    {
                        "request_id": "main",
                        "status": "AVAILABLE",
                        "sha256": "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "health" / "publish_integrity.json").write_text(
        json.dumps({"status": "OLD"}), encoding="utf-8"
    )

    first = refresh_artifact_catalog(tmp_path)
    assert first["record_count"] == 2
    assert first["primary_keys"] == ["path"]
    assert first["completeness"]["status"] == "PASS"
    assert all(not row["path"].endswith("artifact_catalog.json") for row in first["artifacts"])
    assert all(not row["path"].endswith("publish_integrity.json") for row in first["artifacts"])
    assert validate_artifact_catalog(tmp_path)["valid"] is True

    second = refresh_artifact_catalog(tmp_path)
    assert second["catalog_sha256"] == first["catalog_sha256"]

    changed = json.dumps({"source_id": "one", "tampered": True})
    (tmp_path / "current" / "one.json").write_text(changed, encoding="utf-8")
    report = validate_artifact_catalog(tmp_path)
    assert report["valid"] is False
    assert any("artifact_catalog_sha_mismatch" in error for error in report["errors"])
    assert hashlib.sha256(changed.encode()).hexdigest() != first["artifacts"][0].get("sha256", "")
