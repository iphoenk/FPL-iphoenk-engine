from __future__ import annotations

import pytest

from src.runtime_v6.verified_crosswalks import (
    VerifiedCrosswalkError,
    enrich_verified_external_crosswalks,
    load_verified_crosswalks,
)


def _identity() -> dict:
    return {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 2,
        "coverage": {
            source: {
                "strategy": "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
                "deterministic_bridge": False,
                "identity_health": "RED",
                "mapped_status": "UNMAPPED",
                "mapped_player_count": 0,
                "canonical_player_count": 2,
                "coverage_ratio": 0.0,
                "unmapped_player_count": 2,
                "join_allowed": False,
            }
            for source in ("opta_the_analyst", "understat", "fotmob", "statmuse", "ffscout")
        },
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "official_code": 1001,
                "web_name": "Alpha",
                "links": {},
                "unresolved": {
                    "opta_the_analyst": "UNMAPPED",
                    "understat": "UNMAPPED",
                    "fotmob": "UNMAPPED",
                    "statmuse": "UNMAPPED",
                    "ffscout": "UNMAPPED",
                },
            },
            "2": {
                "official_fpl_element_id": 2,
                "official_code": 1002,
                "web_name": "Beta",
                "links": {},
                "unresolved": {
                    "opta_the_analyst": "UNMAPPED",
                    "understat": "UNMAPPED",
                    "fotmob": "UNMAPPED",
                    "statmuse": "UNMAPPED",
                    "ffscout": "UNMAPPED",
                },
            },
        },
        "entity_bridges": {
            "team": {"canonical_team_count": 0, "mappings": {}, "coverage": {}},
            "fixture": {"canonical_fixture_count": 0, "mappings": {}, "coverage": {}},
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }


def test_opta_numeric_bridge_is_exact_and_name_free():
    results = {"opta_the_analyst": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}
    enriched = enrich_verified_external_crosswalks(_identity(), results, config={"sources": {}})

    coverage = enriched["coverage"]["opta_the_analyst"]
    assert coverage["identity_health"] == "GREEN"
    assert coverage["mapped_player_count"] == 2
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["name_matching_used"] is False
    assert enriched["mappings"]["1"]["links"]["opta_the_analyst"]["source_native_id"] == 1001
    assert enriched["mappings"]["1"]["links"]["opta_the_analyst"]["status"] == "EXACT"
    assert "opta_the_analyst" not in enriched["mappings"]["1"]["unresolved"]


def test_opta_numeric_duplicate_code_fails_closed_without_guessing():
    identity = _identity()
    identity["mappings"]["2"]["official_code"] = 1001
    results = {"opta_the_analyst": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}

    enriched = enrich_verified_external_crosswalks(identity, results, config={"sources": {}})
    coverage = enriched["coverage"]["opta_the_analyst"]

    assert coverage["mapped_player_count"] == 0
    assert coverage["duplicate_canonical_code_count"] == 1
    assert coverage["identity_health"] == "RED"
    assert enriched["mappings"]["1"]["links"].get("opta_the_analyst") is None
    assert enriched["mappings"]["2"]["links"].get("opta_the_analyst") is None


def test_configured_provider_player_bridge_anchors_on_official_code_only():
    config = {
        "sources": {
            "understat": {
                "verification_status": "VERIFIED_MANUAL",
                "player_verification_method": "REEP_OPTA_NUMERIC_TO_UNDERSTAT",
                "verified_at": "2026-09-13T00:00:00+00:00",
                "evidence": ["reep-release:test"],
                "players": [
                    {"official_fpl_code": 1001, "source_native_id": 700},
                ],
            }
        }
    }
    results = {"understat": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}

    enriched = enrich_verified_external_crosswalks(_identity(), results, config=config)
    coverage = enriched["coverage"]["understat"]
    link = enriched["mappings"]["1"]["links"]["understat"]

    assert coverage["mapped_player_count"] == 1
    assert coverage["identity_health"] == "AMBER"
    assert coverage["canonical_anchor"] == "official_fpl.bootstrap.elements.code"
    assert link["source_native_id"] == 700
    assert link["status"] == "VERIFIED_MANUAL"
    assert link["provenance"]["name_matching_used"] is False
    assert enriched["mappings"]["2"]["links"].get("understat") is None


def test_ffscout_without_verified_native_ids_stays_fail_closed():
    results = {"ffscout": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}
    enriched = enrich_verified_external_crosswalks(_identity(), results, config={"sources": {}})

    assert enriched["coverage"]["ffscout"]["join_allowed"] is False
    assert enriched["coverage"]["ffscout"]["identity_health"] == "RED"
    assert all("ffscout" not in row["links"] for row in enriched["mappings"].values())


def test_crosswalk_loader_rejects_duplicate_player_native_ids(tmp_path):
    path = tmp_path / "crosswalk.json"
    path.write_text(
        """{
          "schema_version": 1,
          "season": "2026-2027",
          "canonical_authority": "official_fpl",
          "fuzzy_matching_allowed": false,
          "sources": {
            "understat": {
              "players": [
                {"official_fpl_code": 1001, "source_native_id": 700},
                {"official_fpl_code": 1002, "source_native_id": 700}
              ]
            }
          }
        }""",
        encoding="utf-8",
    )

    with pytest.raises(VerifiedCrosswalkError, match="duplicate native player id"):
        load_verified_crosswalks(path)
