"""P0-C regression: DEEP / MATCH / PRICE section catalogs are isolated.

Root cause under test: the visible-body parser recognised every report
family's heading grammar in every body, so the ``#### MATCH n`` fixture
sub-headings that DEEP S16B.1 renders were read as MATCH1..MATCHn sections
(CANONICAL_CATALOG_MISMATCH, VISIBLE_SECTION_UNEXPECTED, SEQUENCE_MISMATCH).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.runtime_v6.domains.report_plane.visible_body_contract import (
    UnknownSectionFamilyError,
    _FAMILY_SECTION_PATTERNS,
    _parse_sections,
    section_family_for_ids,
    validate_visible_report_body,
)

DEEP_IDS = ["S01", "S02", "S03", "S16B"]
MATCH_IDS = [f"MATCH{i}" for i in range(1, 4)]
PRICE_IDS = [f"PRICE{i}" for i in range(1, 4)]


def _deep_body(*, fixtures: int = 10, ids=tuple(DEEP_IDS)) -> str:
    parts = []
    for sid in ids:
        number = sid[1:]
        parts.append(f"## SECTION {number} — Title {sid}\nStatus: COMPLETE\nbody {sid}")
        if sid == "S16B":
            parts.append("### S16B.1 — MATCH-BY-MATCH REVIEW")
            parts.extend(f"#### MATCH {i} — fixture {i}\nTactical setup: x" for i in range(1, fixtures + 1))
            parts.append("### S16B.2 — AFTER-GW REASSESSMENT\nWHAT CHANGED: none")
    return "\n\n".join(parts)


def _family_body(prefix: str, count: int) -> str:
    return "\n\n".join(f"## {prefix} {i} — T{i}\nStatus: COMPLETE\nbody" for i in range(1, count + 1))


def _validate(body: str, ids):
    return validate_visible_report_body(
        rendered_body=body,
        expected_section_ids=ids,
        expected_counts={},
        expected_fact_keys=[],
        expected_model_keys=[],
        expected_inference_keys=[],
        expected_weather_state="MISSING",
        mini_league_denominator_complete_required=False,
    )


def _failures(result) -> list[str]:
    return list(result.get("failures") or result.get("hard_failures") or [])


# ---- original incident -------------------------------------------------


def test_original_failure_deep_s16b_match_subheadings_are_not_sections():
    ids, _, _ = _parse_sections(_deep_body(fixtures=10), "DEEP")
    assert ids == DEEP_IDS
    assert not any(i.startswith("MATCH") for i in ids)


def test_legacy_unscoped_parse_still_shows_the_contamination():
    """Documents the defect the family argument removes (no silent default fix)."""
    ids, _, _ = _parse_sections(_deep_body(fixtures=10))
    assert [i for i in ids if i.startswith("MATCH")] == [f"MATCH{i}" for i in range(1, 11)]


def test_validate_deep_with_s16b_has_no_catalog_failures():
    failures = _failures(_validate(_deep_body(fixtures=10), DEEP_IDS))
    assert not [f for f in failures if f.startswith(("VISIBLE_SECTION_UNEXPECTED", "VISIBLE_SECTION_SEQUENCE_MISMATCH"))]


def test_real_deep_renderer_output_with_ten_fixtures_parses_only_s_sections():
    from src.engines.v12_report_orchestration import render_deep_text

    report = {
        "report_mode": "DEEP",
        "s16b_due": True,
        "sections": [
            {"section_id": "S01", "label": "Decision", "state": "COMPLETE", "content": {}},
            {
                "section_id": "S16B",
                "label": "Post-match",
                "state": "COMPLETE",
                "content": {
                    "gw": 7,
                    "match_by_match_review": [
                        {"fixture_id": i, "result": f"A {i}-0 B"} for i in range(1, 11)
                    ],
                    "after_gw_reassessment": {},
                },
            },
        ],
    }
    body = render_deep_text(report)
    assert _parse_sections(body, "DEEP")[0] == ["S01", "S16B"]
    assert [i for i in _parse_sections(body)[0] if i.startswith("MATCH")]  # legacy defect


# ---- positive: each family ---------------------------------------------


def test_valid_deep_match_price_parse_to_their_own_catalog():
    assert _parse_sections(_deep_body(), "DEEP")[0] == DEEP_IDS
    assert _parse_sections(_family_body("MATCH", 3), "MATCH")[0] == MATCH_IDS
    assert _parse_sections(_family_body("PRICE", 3), "PRICE")[0] == PRICE_IDS


@pytest.mark.parametrize(
    "ids,family",
    [(DEEP_IDS, "DEEP"), (MATCH_IDS, "MATCH"), (PRICE_IDS, "PRICE"),
     (["POST_ALL_MATCH1", "POST_ALL_MATCH2"], "POST_ALL_MATCH")],
)
def test_family_inference(ids, family):
    assert section_family_for_ids(ids) == family


def test_family_inference_fails_closed_on_mixed_or_empty():
    assert section_family_for_ids([]) is None
    assert section_family_for_ids(["S01", "MATCH1"]) is None
    assert section_family_for_ids(["MATCH1", "PRICE1"]) is None


# ---- cross-mode contamination ------------------------------------------


def test_match_body_under_deep_family_yields_no_sections():
    assert _parse_sections(_family_body("MATCH", 3), "DEEP")[0] == []


def test_deep_headings_under_match_family_yield_no_sections():
    assert _parse_sections(_deep_body(ids=("S01", "S02", "S03")), "MATCH")[0] == []


def test_price_body_validated_as_deep_reports_missing_sections():
    failures = _failures(_validate(_family_body("PRICE", 3), DEEP_IDS))
    assert any(f.startswith("VISIBLE_SECTIONS_MISSING=") for f in failures)


def test_deep_body_validated_as_match_reports_missing_sections():
    failures = _failures(_validate(_deep_body(ids=("S01", "S02", "S03")), MATCH_IDS))
    assert any(f.startswith("VISIBLE_SECTIONS_MISSING=") for f in failures)


def test_deep_body_with_s16b_validated_as_match_still_fails_closed():
    assert _failures(_validate(_deep_body(fixtures=10), MATCH_IDS))


# ---- negative: duplicate / missing / unexpected / reordered -------------


def test_duplicate_section_detected():
    body = _deep_body(ids=("S01", "S02", "S02", "S03", "S16B"))
    failures = _failures(_validate(body, DEEP_IDS))
    assert any(f.startswith("VISIBLE_SECTION_DUPLICATE=S02") for f in failures)


def test_missing_section_detected():
    failures = _failures(_validate(_deep_body(ids=("S01", "S03", "S16B")), DEEP_IDS))
    assert any(f.startswith("VISIBLE_SECTIONS_MISSING=S02") for f in failures)


def test_unexpected_section_detected():
    body = _deep_body(ids=("S01", "S02", "S03", "S04", "S16B"))
    failures = _failures(_validate(body, DEEP_IDS))
    assert any(f.startswith("VISIBLE_SECTION_UNEXPECTED=S04") for f in failures)


def test_reordered_sections_detected():
    failures = _failures(_validate(_deep_body(ids=("S02", "S01", "S03", "S16B")), DEEP_IDS))
    assert "VISIBLE_SECTION_SEQUENCE_MISMATCH" in failures


# ---- unknown modes ------------------------------------------------------


def test_unknown_family_is_rejected_not_defaulted():
    with pytest.raises(UnknownSectionFamilyError, match="UNKNOWN_SECTION_FAMILY=BOGUS"):
        _parse_sections(_deep_body(), "BOGUS")


def test_unknown_catalog_family_skips_scoping_but_still_fails_validation():
    # Mixed/unknown catalog -> family None -> legacy grammar; validation must
    # still fail closed because the rendered ids cannot equal the mixed catalog.
    failures = _failures(_validate(_deep_body(), ["S01", "MATCH1"]))
    assert failures


# ---- shared mutable state / concurrency ---------------------------------


def test_family_pattern_table_is_not_mutable_through_public_view():
    with pytest.raises(TypeError):
        _FAMILY_SECTION_PATTERNS["DEEP"] = ()  # type: ignore[index]


def test_family_tuples_are_immutable():
    assert isinstance(_FAMILY_SECTION_PATTERNS["DEEP"], tuple)


def test_concurrent_mixed_mode_parsing_has_no_cross_talk():
    jobs = []
    for n in range(120):
        jobs.append(("DEEP", _deep_body(fixtures=1 + n % 10), DEEP_IDS))
        jobs.append(("MATCH", _family_body("MATCH", 3), MATCH_IDS))
        jobs.append(("PRICE", _family_body("PRICE", 3), PRICE_IDS))

    def run(job):
        family, body, expected = job
        return _parse_sections(body, family)[0] == expected

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(run, jobs))
