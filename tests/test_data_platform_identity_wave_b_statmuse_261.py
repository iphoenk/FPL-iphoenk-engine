from src.runtime_v6.verified_crosswalks import load_verified_crosswalks, enrich_verified_external_crosswalks


def _identity_map():
    return {
        "canonical_player_count": 657,
        "mappings": {
            "372": {
                "official_fpl_element_id": 372,
                "official_code": 243016,
                "links": {},
                "unresolved": {"statmuse": {"status": "UNMAPPED"}},
            }
        },
        "coverage": {},
    }


def test_statmuse_261_curated_chain_is_reviewed_and_deterministic():
    config = load_verified_crosswalks()
    source = config["sources"]["statmuse"]
    rows = [row for row in source["players"] if row["source_native_id"] == 261]
    assert len(rows) == 1
    row = rows[0]
    assert row["official_fpl_code"] == 243016
    assert row["official_fpl_element_id"] == 372
    assert row["reep_id"] == "rpecc5cfdbee4a41"
    assert row["verification_method"] == "CURATED_WIKIDATA_STATMUSE_ID_TO_TM__REEP_V1_TM_TO_OPTA__OFFICIAL_FPL_CODE"
    assert row["review_status"] == "REVIEWED_DETERMINISTIC_ONE_TO_ONE"
    assert row["reviewer"] == "V6_WAVE_B_IDENTITY_REVIEW"
    assert "statmuse:P12567:261" in row["evidence"]
    assert "wikidata:P2446:534033" in row["evidence"]
    assert "reep_v1:opta:person_numeric:243016" in row["evidence"]


def test_statmuse_261_runtime_provenance_is_per_row_not_legacy_v0():
    config = load_verified_crosswalks()
    enriched = enrich_verified_external_crosswalks(
        _identity_map(),
        {"statmuse": {"data": {}}},
        config=config,
    )
    link = enriched["mappings"]["372"]["links"]["statmuse"]
    assert link["source_native_id"] == 261
    assert link["joinable"] is True
    assert link["method"] == "CURATED_WIKIDATA_STATMUSE_ID_TO_TM__REEP_V1_TM_TO_OPTA__OFFICIAL_FPL_CODE"
    provenance = link["provenance"]
    assert provenance["verification_release"] == "20260907T201034Z"
    assert provenance["review_status"] == "REVIEWED_DETERMINISTIC_ONE_TO_ONE"
    assert provenance["reviewer"] == "V6_WAVE_B_IDENTITY_REVIEW"
    assert provenance["review_reference"] == "github_actions_run:34764199565"
    assert provenance["name_matching_used"] is False
    assert provenance["fuzzy_matching_used"] is False
    assert "reep_v1:rpecc5cfdbee4a41" in provenance["bridge_path"]
