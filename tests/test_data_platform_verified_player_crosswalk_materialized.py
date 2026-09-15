from __future__ import annotations

from src.runtime_v6.verified_crosswalks import load_verified_crosswalks


EXPECTED = {
    "understat": 587,
    "fotmob": 352,
    "statmuse": 303,
}


def test_materialized_player_crosswalks_are_partial_verified_and_unique():
    config = load_verified_crosswalks()
    assert config["canonical_authority"] == "official_fpl"
    assert config["fuzzy_matching_allowed"] is False
    assert config["governance"]["player_crosswalk_uses_official_code_only"] is True
    assert config["governance"]["player_crosswalk_partial_coverage_is_allowed"] is True

    for source_id, expected_count in EXPECTED.items():
        source = config["sources"][source_id]
        rows = source["players"]
        assert len(rows) == expected_count
        assert len({int(row["official_fpl_code"]) for row in rows}) == expected_count
        assert len({str(row["source_native_id"]) for row in rows}) == expected_count
        assert source["player_crosswalk_name_matching"] is False
        assert source["player_verification_method"] == "REEP_V0_PINNED_OPTA_NUMERIC_TO_PROVIDER_ID"
        assert source["player_crosswalk_release"] == "2026.25"
        assert source["player_crosswalk_commit"] == "0ec59faa5d81615b7a8200ae6121023a3bc14ce3"
        assert source["player_crosswalk_blob"] == "dc4441b1f94f05c36b807ed23f3a2b7dede5878d"
        assert "official_fpl:bootstrap.elements.code" in source["evidence"]
        assert all("name" not in row for row in rows)


def test_fotmob_keeps_verified_twenty_team_crosswalk_alongside_player_links():
    config = load_verified_crosswalks()
    rows = config["sources"]["fotmob"]["teams"]
    assert len(rows) == 20
    assert len({int(row["source_native_id"]) for row in rows}) == 20
    assert {int(row["official_fpl_team_id"]) for row in rows} == set(range(1, 21))
