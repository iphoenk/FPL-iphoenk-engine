from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.v12_report_orchestration import materialize_deep_report
from src.engines.v12_section_resolver import (
    SectionResolutionError,
    resolve_section,
    validate_resolved_sections,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


def _candidate(value: str, *, state: str = "COMPLETE"):
    return {"state": state, "content": {"value": value}}


def _bound(value: str, *, valid: bool = True):
    proof = {
        "exact_lineage_match": True,
        "dependency_unchanged": True,
        "mathematically_applicable": True,
    }
    if not valid:
        proof["dependency_unchanged"] = False
    return {
        "state": "COMPLETE",
        "content": {"value": value, "current_bound_proof": proof},
    }


def test_section_resolver_priority_current_then_bound_then_prior():
    resolved = resolve_section(
        section_id="S14",
        label="PACKAGE OPTIMIZER / TRANSFER FRONTIER",
        current=_candidate("current"),
        current_bound=_bound("bound"),
        prior=_candidate("prior"),
        prior_source_occurrence="2026-09-29T21:30:00+07:00",
    )
    assert resolved["source_state"] == "CURRENT"
    assert resolved["content"]["presentation_status"] == "CURRENT"
    assert resolved["content"]["value"] == "current"


def test_section_resolver_uses_current_bound_only_with_exact_proof():
    valid = resolve_section(
        section_id="S14",
        label="PACKAGE OPTIMIZER / TRANSFER FRONTIER",
        current_bound=_bound("bound"),
        prior=_candidate("prior"),
        prior_source_occurrence="2026-09-29T21:30:00+07:00",
    )
    assert valid["source_state"] == "CURRENT-BOUND"
    assert valid["content"]["presentation_status"] == "CURRENT-BOUND"
    assert valid["content"]["current_bound_proof"]["dependency_unchanged"] is True

    invalid = resolve_section(
        section_id="S14",
        label="PACKAGE OPTIMIZER / TRANSFER FRONTIER",
        current_bound=_bound("bound", valid=False),
        prior=_candidate("prior"),
        prior_source_occurrence="2026-09-29T21:30:00+07:00",
    )
    assert invalid["source_state"] == "PRIOR"
    assert invalid["content"]["presentation_status"] == "PRIOR"


def test_prior_requires_source_occurrence():
    with pytest.raises(SectionResolutionError, match="PRIOR requires source occurrence"):
        resolve_section(
            section_id="S14",
            label="PACKAGE OPTIMIZER / TRANSFER FRONTIER",
            prior=_candidate("prior"),
        )


def test_materializer_keeps_prelabelled_prior_truthful_and_23_sections():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={
            "S14": {
                "state": "DEGRADED",
                "degradation_reason": "fresh optimizer unavailable",
                "content": {
                    "presentation_status": "PRIOR",
                    "prior_source_occurrence": "2026-09-29T21:30:00+07:00",
                    "hold": {"route": "HOLD"},
                },
            }
        },
    )
    assert len(report["sections"]) == 23
    assert report["exact_canonical_order"] is True
    s14 = next(row for row in report["sections"] if row["section_id"] == "S14")
    assert s14["source_state"] == "PRIOR"
    assert s14["state"] == "DEGRADED"
    assert s14["content"]["presentation_status"] == "PRIOR"
    assert s14["content"]["prior_source_occurrence"] == "2026-09-29T21:30:00+07:00"


def test_batch_validator_rejects_false_current_and_invalid_bound():
    failures = validate_resolved_sections(
        [
            {
                "section_id": "S03",
                "source_state": "CURRENT",
                "content": {
                    "presentation_status": "CURRENT",
                    "prior_source_occurrence": "2026-09-29T04:30:00+07:00",
                },
            },
            {
                "section_id": "S14",
                "source_state": "CURRENT-BOUND",
                "content": {
                    "presentation_status": "CURRENT-BOUND",
                    "current_bound_proof": {
                        "exact_lineage_match": True,
                        "dependency_unchanged": False,
                        "mathematically_applicable": True,
                    },
                },
            },
        ]
    )
    assert "S03:FALSE_CURRENT" in failures
    assert "S14:CURRENT_BOUND_PROOF_INVALID" in failures
