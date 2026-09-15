from __future__ import annotations

from src.runtime_v6.verified_crosswalks import (
    enrich_verified_external_crosswalks,
    load_verified_crosswalks,
)

METHOD = "REEP_V1_OPTA_PERSON_NUMERIC_TO_UNDERSTAT"
WAVE1_METHOD = "WAVE1_OFFICIAL_FPL_CODE_TO_OBSERVED_UNDERSTAT_NATIVE_ID"
RELEASE = "20260907T201034Z"
BRIDGES_SHA = "a03aef520a454bdcd181b5b332b91e7b41ee57f4914e6e2c456cf49a8b86a735"
REVIEW_REFERENCE = "github-actions:run/34762762105"
EXPECTED_NATIVE_IDS = {
    "212", "1045", "5680", "7783", "8325", "8372", "8379", "8685", "9011", "11087", "11772", "11911", "12162",
}
EXPECTED_CODES = {93605, 168144, 173774, 204561, 218543, 242313, 243016, 469266, 490884, 498444, 508395, 551050, 637238}
EXPECTED_ELEMENT_IDS = {102, 184, 207, 372, 541, 558, 583, 589, 598, 616, 617, 619, 635}
WAVE1_EXPECTED = {
    "8190": (437497, 637, "wave1-understat-identity-2026-09-15"),
    "12847": (627221, 599, "wave1-understat-identity-2026-09-15"),
    "13078": (592984, 639, "wave1-understat-identity-chema-correction-2026-09-15"),
}


def test_reviewed_understat_wave_b_rows_are_exact_unique_and_provenance_complete():
    config = load_verified_crosswalks()
    source = config["sources"]["understat"]
    rows = source["players"]
    wave = [row for row in rows if row.get("verification_method") == METHOD]
    wave1 = [row for row in rows if row.get("verification_method") == WAVE1_METHOD]

    assert len(rows) == 587
    assert len({str(row["source_native_id"]) for row in rows}) == 587
    assert len({int(row["official_fpl_code"]) for row in rows}) == 587
    assert len(wave) == 13
    assert {str(row["source_native_id"]) for row in wave} == EXPECTED_NATIVE_IDS
    assert {int(row["official_fpl_code"]) for row in wave} == EXPECTED_CODES
    assert {int(row["official_fpl_element_id"]) for row in wave} == EXPECTED_ELEMENT_IDS
    assert len(wave1) == 3
    assert {str(row["source_native_id"]) for row in wave1} == set(WAVE1_EXPECTED)

    for row in wave:
        assert row["review_status"] == "DETERMINISTIC_BRIDGE_REVIEWED"
        assert row["review_reference"] == REVIEW_REFERENCE
        assert row["verification_release"] == RELEASE
        assert row["bridge_path"] == [
            "official_fpl.bootstrap.elements.code",
            "reep_v1:opta/person_numeric",
            "reep_v1:understat/player",
            "official_fpl.bootstrap.elements.id",
        ]
        assert f"reep_v1_release:{RELEASE}" in row["evidence"]
        assert f"reep_v1_bridges_sha256:{BRIDGES_SHA}" in row["evidence"]
        assert not any("name" in item.lower() or "fuzzy" in item.lower() for item in row["evidence"])

    for row in wave1:
        native_id = str(row["source_native_id"])
        expected_code, expected_element, expected_review = WAVE1_EXPECTED[native_id]
        assert int(row["official_fpl_code"]) == expected_code
        assert int(row["official_fpl_element_id"]) == expected_element
        assert row["review_status"] == "DETERMINISTIC_BRIDGE_REVIEWED"
        assert row["review_reference"] == expected_review
        assert row["bridge_path"] == [
            "official_fpl.bootstrap.elements.code",
            "understat.observed_native_player_id",
            "official_fpl.bootstrap.elements.id",
        ]
        assert not any("name" in item.lower() or "fuzzy" in item.lower() for item in row["evidence"])

    extension = source["wave_b_extension"]
    assert extension["verification_method"] == METHOD
    assert extension["promoted_mapping_count"] == 13
    assert extension["name_matching_used"] is False
    assert extension["fuzzy_matching_used"] is False
    assert extension["auto_promotion_used"] is False


def test_promoted_row_keeps_row_level_reep_v1_provenance_at_runtime():
    identity_map = {
        "canonical_player_count": 1,
        "mappings": {
            "372": {
                "official_fpl_element_id": 372,
                "official_code": 243016,
                "links": {},
                "unresolved": {"understat": {"status": "UNMAPPED"}},
            }
        },
        "coverage": {},
    }
    results = {"understat": {"health": "GREEN", "effective_state": "LIVE_CHANGED"}}

    enriched = enrich_verified_external_crosswalks(identity_map, results)
    link = enriched["mappings"]["372"]["links"]["understat"]
    provenance = link["provenance"]

    assert link["status"] == "VERIFIED_MANUAL"
    assert link["method"] == METHOD
    assert link["source_native_id"] == 8379
    assert link["verified_at"] == "2026-09-13T14:28:58Z"
    assert provenance["official_fpl_code"] == 243016
    assert provenance["official_fpl_element_id"] == 372
    assert provenance["reep_id"] == "rpecc5cfdbee4a41"
    assert provenance["verification_release"] == RELEASE
    assert provenance["review_status"] == "DETERMINISTIC_BRIDGE_REVIEWED"
    assert provenance["review_reference"] == REVIEW_REFERENCE
    assert f"reep_v1_bridges_sha256:{BRIDGES_SHA}" in provenance["evidence"]
    assert provenance["bridge_path"] == [
        "official_fpl.bootstrap.elements.code",
        "reep_v1:opta/person_numeric",
        "reep_v1:understat/player",
        "official_fpl.bootstrap.elements.id",
    ]
    assert provenance["name_matching_used"] is False
    assert provenance["fuzzy_matching_used"] is False

    coverage = enriched["coverage"]["understat"]
    assert coverage["mapped_player_count"] == 1
    assert coverage["canonical_player_count"] == 1
    assert coverage["identity_health"] == "GREEN"
    assert coverage["conflicting_existing_link_count"] == 0
