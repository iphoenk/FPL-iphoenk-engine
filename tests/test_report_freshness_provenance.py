from datetime import datetime, timezone

import pytest

from src.engines.v12_report_freshness_provenance import (
    AGING, FRESH, STALE, UNAVAILABLE, UNKNOWN,
    attach_report_provenance, build_dataset_provenance, build_player_evidence,
    build_source_provenance, classify_freshness, validate_section_provenance,
)


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def test_type_specific_freshness_is_deterministic():
    assert classify_freshness("2026-10-09T11:00:00Z", ttl_hours=2, now=NOW) == FRESH
    assert classify_freshness("2026-10-09T09:00:00Z", ttl_hours=2, now=NOW) == AGING
    assert classify_freshness("2026-10-09T07:00:00Z", ttl_hours=2, now=NOW) == STALE
    assert classify_freshness(None, ttl_hours=2, now=NOW) == UNKNOWN
    assert classify_freshness(None, ttl_hours=2, now=NOW, unavailable=True) == UNAVAILABLE


def test_required_source_dataset_player_contracts_and_polarity():
    source = build_source_provenance(
        source_id="injury:official",
        source_type="official",
        source_authority="OFFICIAL_FPL",
        source_reference="https://example.invalid/injury",
        fetched_at="2026-10-09T11:00:00Z",
        observed_at="2026-10-09T11:00:00Z",
        evidence_cutoff_at="2026-10-09T11:00:00Z",
        ttl_hours=2, now=NOW,
    )
    dataset = build_dataset_provenance(
        dataset_id="players",
        dataset_version="v1",
        generated_at="2026-10-09T11:00:00Z",
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2026-10-09T11:00:00Z",
        target_gw=6, target_fixture_ids=["fx-1"],
        source_ids=["injury:official"], schema_version="1",
        evidence_cutoff_at="2026-10-09T11:00:00Z", ttl_hours=2, now=NOW,
    )
    player = build_player_evidence(
        player_id=1, target_gw=6, target_fixture_id="fx-1",
        raw_claim="questionable", normalized_claim="DOUBTFUL",
        claim_domain="availability", evidence_polarity="NEGATIVE",
        derived_at="2026-10-09T11:00:00Z",
        evidence_cutoff_at="2026-10-09T11:00:00Z",
        source_id="injury:official", ttl_hours=2, now=NOW,
    )
    assert source["freshness_state"] == FRESH
    assert dataset["freshness_state"] == FRESH
    assert player["target_fixture_id"] == "fx-1"
    assert player["evidence_polarity"] == "NEGATIVE"


def test_stale_and_cutoff_are_degraded_and_future_cutoff_invalid():
    sections = {
        "S08": {"state": "COMPLETE", "content": {
            "source_id": "captain:model",
            "freshness_state": STALE,
            "evidence_cutoff_at": "2026-10-09T10:00:00Z",
            "player_id": 1,
        }},
        "S18": {"state": "COMPLETE", "content": {}},
    }
    report = attach_report_provenance(
        sections, report_kind="DEEP", target_gw=6,
        report_timestamp="2026-10-09T09:00:00Z", target_fixture_ids=["fx-1"],
    )
    assert report["S08"]["content"]["provenance"]["degradation_state"] == "DEGRADED"
    assert validate_section_provenance(
        {"degradation_state": "COMPLETE", "freshness_summary": {},
         "evidence_cutoff_at": "2026-10-09T10:00:00Z"},
        report_timestamp="2026-10-09T09:00:00Z",
    )["valid"] is False


def test_unavailable_never_becomes_neutral_and_missing_cutoff_degrades():
    report = attach_report_provenance(
        {"S19": {"state": "COMPLETE", "content": {"freshness_state": UNAVAILABLE}}},
        report_kind="DEEP", target_gw=6,
        report_timestamp=NOW, target_fixture_ids=[],
    )
    provenance = report["S19"]["content"]["provenance"]
    assert provenance["degradation_state"] == "DEGRADED"
    assert provenance["freshness_summary"][UNAVAILABLE] == 1
    assert provenance["evidence_cutoff_at"] is None


def test_provenance_is_privacy_safe():
    with pytest.raises(ValueError, match="PRIVACY"):
        from src.engines.v12_report_freshness_provenance import build_section_provenance
        build_section_provenance(
            section_id="S17", report_kind="DEEP", target_gw=6,
            target_fixture_ids=[], source_ids=["token-secret"], dataset_ids=[],
            player_ids=[], evidence_cutoff_at=None, freshness_summary={},
            degradation_state="DEGRADED",
        )
