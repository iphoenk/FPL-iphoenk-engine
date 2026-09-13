from __future__ import annotations

from src.runtime_v6.verified_crosswalks import load_verified_crosswalks


def test_wave_b_understat_secondary_registry_extension_is_reviewed_and_stable_id_only():
    config = load_verified_crosswalks()
    source = config["sources"]["understat"]
    rows = [
        row for row in source["players"]
        if row.get("verification_method") == "FPL_ID_MAP_PINNED_UNDERSTAT_NATIVE_TO_OFFICIAL_FPL_CODE"
    ]
    assert len(rows) == 68
    assert len({int(row["source_native_id"]) for row in rows}) == 68
    assert len({int(row["official_fpl_code"]) for row in rows}) == 68
    assert all(int(row["official_fpl_element_id"]) > 0 for row in rows)
    assert all(row["review_status"] == "DETERMINISTIC_SECONDARY_REGISTRY_REVIEWED" for row in rows)
    assert all(str(row["review_reference"]).startswith("github-actions:run/") for row in rows)
    assert all(row["verification_commit"] == "e5a9942affd98501db473a8d3b6a0f9e93751e8a" for row in rows)
    assert all("sha256:19d1f9d08ab975e40d26b214f6984cce7d6bc58f62fbef3bec46722b2196d56a" in row["evidence"] for row in rows)
    assert all("name" not in row for row in rows)


def test_wave_b_understat_secondary_extension_keeps_only_native_15045_unresolved_by_this_registry():
    config = load_verified_crosswalks()
    meta = config["sources"]["understat"]["wave_b_secondary_extension"]
    assert meta["mapping_count"] == 68
    assert meta["name_matching_used"] is False
    assert meta["fuzzy_matching_used"] is False
    assert meta["unresolved_observed_native_ids_after_review"] == [15045]
