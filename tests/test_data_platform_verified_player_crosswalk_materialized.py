from __future__ import annotations

from src.runtime_v6.verified_crosswalks import load_verified_crosswalks


EXPECTED = {
    "understat": 587,
    "fotmob": 489,
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



def test_reep_v1_fotmob_promotion_is_exact_and_auditable():
    cfg = load_verified_crosswalks()["sources"]["fotmob"]
    wave = cfg["wave_b_extension"]
    method = "REEP_V1_20261005_FOTMOB_PERSON_OPTA_PERSON_NUMERIC"
    assert wave["verification_method"] == method
    assert wave["promoted_mapping_count"] == 137
    assert wave["observed_gw1_gw6_native_count"] == 327
    assert wave["observed_native_total_count"] == 332
    assert wave["already_present_v0_nonstarter_count"] == 2
    assert wave["remaining_observed_unmapped_count"] == 0
    assert wave["name_matching_used"] is False
    assert wave["fuzzy_matching_used"] is False
    assert wave["auto_promotion_used"] is False
    newly_verified = [r for r in cfg["players"] if r.get("verification_method") == method]
    assert len(newly_verified) == 137
    assert len({r["source_native_id"] for r in newly_verified}) == 137
    assert len({r["official_fpl_code"] for r in newly_verified}) == 137
    assert len({r["official_fpl_element_id"] for r in newly_verified}) == 137
    assert len({r["reep_id"] for r in newly_verified}) == 137
    for row in newly_verified:
        assert row["review_status"] == "DETERMINISTIC_BRIDGE_REVIEWED"
        assert row["review_reference"] in {"github-actions:run/38811691738", "github-actions:run/38812432637"}
        assert row["bridge_path"] == [
            "official_fpl.bootstrap.elements.code",
            "reep_v1:opta/person_numeric",
            "reep_v1:fotmob/person",
            "official_fpl.bootstrap.elements.id",
        ]
        evidence = row["evidence"]
        assert "reep_v1_release:20261005T180536Z" in evidence
        assert (
            "reep_v1_bridges_sha256:ccfe36b94612890102d89159b82eb92f22245151b4b7ebbf2859e38f069d7731"
            in evidence
        )
        assert "source_v6_git:dada6d7962ea25576e3e12bc0f501fd065f9f064" in evidence
        assert all("fuzzy" not in str(part).lower() for part in evidence)
