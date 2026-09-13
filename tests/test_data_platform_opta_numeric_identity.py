from __future__ import annotations

from src.runtime_v6.verified_crosswalks import enrich_verified_external_crosswalks


def _identity() -> dict:
    return {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 2,
        "coverage": {
            "opta_the_analyst": {
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
        },
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "official_code": 1001,
                "web_name": "Alpha",
                "links": {},
                "unresolved": {"opta_the_analyst": "UNMAPPED"},
            },
            "2": {
                "official_fpl_element_id": 2,
                "official_code": 1002,
                "web_name": "Beta",
                "links": {},
                "unresolved": {"opta_the_analyst": "UNMAPPED"},
            },
        },
        "entity_bridges": {
            "team": {"canonical_team_count": 0, "mappings": {}, "coverage": {}},
            "fixture": {"canonical_fixture_count": 0, "mappings": {}, "coverage": {}},
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }


def test_opta_numeric_bridge_uses_official_code_not_names():
    results = {
        "opta_the_analyst": {
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "data": {"premier_league_stats": {"body": "provider payload not used for identity guessing"}},
        }
    }

    enriched = enrich_verified_external_crosswalks(_identity(), results)
    coverage = enriched["coverage"]["opta_the_analyst"]

    assert coverage["deterministic_bridge"] is True
    assert coverage["identity_health"] == "GREEN"
    assert coverage["mapped_player_count"] == 2
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["join_allowed"] is True
    assert coverage["name_matching_used"] is False

    first = enriched["mappings"]["1"]
    assert first["links"]["opta_the_analyst"]["source_native_id"] == 1001
    assert first["links"]["opta_the_analyst"]["status"] == "EXACT"
    assert first["links"]["opta_the_analyst"]["provenance"]["canonical_field"] == "bootstrap.elements.code"
    assert "opta_the_analyst" not in first["unresolved"]
    assert enriched["governance"]["opta_numeric_bridge_is_name_free"] is True


def test_opta_numeric_bridge_fails_closed_for_missing_or_duplicate_codes():
    identity = _identity()
    identity["mappings"]["2"]["official_code"] = 1001
    results = {"opta_the_analyst": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}

    enriched = enrich_verified_external_crosswalks(identity, results)
    coverage = enriched["coverage"]["opta_the_analyst"]

    assert coverage["identity_health"] == "AMBER"
    assert coverage["mapped_player_count"] == 1
    assert coverage["unmapped_player_count"] == 1
    assert enriched["mappings"]["2"]["links"].get("opta_the_analyst") is None
