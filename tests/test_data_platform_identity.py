from __future__ import annotations

from src.runtime_v6.identity import build_player_identity_map
from src.runtime_v6.normalizer import build_canonical_players


def _official() -> dict:
    return {
        "official": {
            "bootstrap": {
                "elements": [
                    {"id": 1, "code": 1001, "web_name": "Alpha", "first_name": "A", "second_name": "One", "team": 1, "element_type": 3, "status": "a"},
                    {"id": 2, "code": 1002, "web_name": "Beta", "first_name": "B", "second_name": "Two", "team": 2, "element_type": 4, "status": "a"},
                ]
            }
        }
    }


def _results() -> dict:
    return {
        "official_price_predictor": {
            "data": {"players": [{"id": 1}, {"id": 2}]}
        },
        "vaastav_fpl": {
            "data": {
                "players_raw": {
                    "body": "id,code,web_name\r\n1,1001,Alpha\r\n2,1002,Beta\r\n"
                }
            }
        },
        "understat": {"data": {"epl_2026": {"body": "raw html only"}}},
    }


def test_verified_shared_ids_are_mapped_without_fuzzy_matching():
    source_ids = ["official_fpl", "official_price_predictor", "vaastav_fpl", "understat"]

    identity = build_player_identity_map(_official(), _results(), source_ids)

    assert identity["governance"]["fuzzy_name_matching_allowed"] is False
    assert identity["coverage"]["official_price_predictor"]["mapped_player_count"] == 2
    assert identity["coverage"]["vaastav_fpl"]["mapped_player_count"] == 2
    assert identity["coverage"]["vaastav_fpl"]["coverage_ratio"] == 1.0
    assert identity["coverage"]["understat"]["mapped_player_count"] == 0
    assert identity["coverage"]["understat"]["strategy"] == "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE"
    assert identity["mappings"]["1"]["links"]["vaastav_fpl"]["method"] == "FPL_ELEMENT_ID_AND_CODE_EXACT"


def test_provider_code_mismatch_is_not_force_mapped():
    results = _results()
    results["vaastav_fpl"]["data"]["players_raw"]["body"] = "id,code,web_name\r\n1,9999,Alpha\r\n"

    identity = build_player_identity_map(
        _official(),
        results,
        ["official_fpl", "vaastav_fpl"],
    )

    assert identity["coverage"]["vaastav_fpl"]["mapped_player_count"] == 0
    assert identity["mappings"]["1"]["links"] == {}


def test_canonical_players_expose_verified_links_and_explicit_nulls():
    source_ids = ["official_fpl", "official_price_predictor", "vaastav_fpl", "understat"]
    identity = build_player_identity_map(_official(), _results(), source_ids)

    canonical = build_canonical_players(_official(), source_ids, identity)
    first = canonical["players"][0]

    assert canonical["schema_version"] == 2
    assert canonical["identity_map_path"] == "data/v6/evidence/player_identity_map.json"
    assert first["external_ids"]["official_price_predictor"] == 1
    assert first["external_ids"]["vaastav_fpl"] == 1
    assert first["external_ids"]["understat"] is None
    assert first["identity_links"]["vaastav_fpl"]["verified"] is True
    assert "understat" not in first["identity_links"]


def test_mapping_never_uses_names_as_fallback():
    results = _results()
    results["vaastav_fpl"]["data"]["players_raw"]["body"] = "id,code,web_name\r\n99,1001,Alpha\r\n"

    identity = build_player_identity_map(
        _official(),
        results,
        ["official_fpl", "vaastav_fpl"],
    )

    assert identity["coverage"]["vaastav_fpl"]["mapped_player_count"] == 0
