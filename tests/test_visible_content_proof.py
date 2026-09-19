from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.visible_content_proof import (
    CANONICAL_AUTHORITY,
    PYTHON_QA_MODULE,
    RUNTIME_NAME,
    VisibleContentProofError,
    build_visible_content_proof,
    canonical_content_fingerprint,
    compact_visible_content_status,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / CANONICAL_AUTHORITY


def _canonical_text() -> str:
    return CANONICAL.read_text(encoding="utf-8")


def _complete(section_id: str, available: int | None = None, expected: int | None = None) -> dict:
    return {
        "section_id": section_id,
        "state": "COMPLETE",
        "available_count": available,
        "expected_count": expected,
    }


def _degraded(
    section_id: str,
    *,
    state: str = "DEGRADED",
    available: int | None = None,
    expected: int | None = None,
    reason: str = "authoritative scope incomplete after bounded recovery",
    missing_scope: list[str] | None = None,
) -> dict:
    return {
        "section_id": section_id,
        "state": state,
        "available_count": available,
        "expected_count": expected,
        "degradation_reason": reason,
        "missing_scope": list(missing_scope or []),
    }


def _degradation_record(section: dict) -> dict:
    return {
        "section": section["section_id"],
        "state": section["state"],
        "available_count": section.get("available_count"),
        "expected_count": section.get("expected_count"),
        "degradation_reason": section.get("degradation_reason"),
        "missing_scope": list(section.get("missing_scope") or []),
    }


def _proof(**overrides):
    text = _canonical_text()
    kwargs = {
        "canonical_authority_path": CANONICAL_AUTHORITY,
        "canonical_content_fingerprint_sha256": canonical_content_fingerprint(text),
        "canonical_version": "FPL MASTER CANONICAL V12",
        "report_slot": "2026-09-19T12:30:00+07:00",
        "report_mode": "DEEP",
        "report_due": True,
        "observed_at": "2026-09-19T12:30:07+07:00",
        "section_states": [_complete("ALL15", 15, 15), _complete("WATCHLIST20", 20, 20)],
        "hard_failures": [],
        "section_degradations": [],
        "warnings": [],
        "report_can_continue": True,
        "search_authority": "FULL",
        "repository_python_qa_executed": False,
        "python_execution_evidence": None,
    }
    kwargs.update(overrides)
    return build_visible_content_proof(**kwargs)


def test_01_canonical_contains_all_section_level_states():
    text = _canonical_text()
    for state in ("COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"):
        assert state in text


def test_02_canonical_says_truthful_degradation_does_not_suppress_due_report():
    text = _canonical_text()
    assert "truthful section degradation is not whole-report failure" in text
    assert "never suppress a due report solely because the section is incomplete" in text


def test_03_canonical_forbids_fabricated_rows_for_exact_counts():
    text = _canonical_text()
    assert "never fabricate missing rows/data" in text
    assert "never add placeholder rows merely to satisfy an exact count" in text


def test_04_canonical_complete_malformed_scope_is_hard_failure():
    text = _canonical_text()
    assert "WATCHLIST20 state COMPLETE with only 17 rows is a hard failure" in text
    assert "claims COMPLETE but exact count/schema is wrong" in text


def test_05_visible_content_proof_contains_canonical_path_and_fingerprint():
    proof = _proof()
    assert proof["canonical_authority"]["path"] == CANONICAL_AUTHORITY
    assert len(proof["canonical_authority"]["content_sha256"]) == 64
    assert proof["canonical_authority"]["content_sha256"] == canonical_content_fingerprint(
        _canonical_text()
    )


def test_06_visible_content_proof_contains_report_slot_mode_and_due_state():
    proof = _proof()
    assert proof["report_slot"] == "2026-09-19T12:30:00+07:00"
    assert proof["report_mode"] == "DEEP"
    assert proof["report_due"] is True
    assert proof["observed_at"] == "2026-09-19T12:30:07+07:00"


def test_07_degraded_watchlist_records_17_of_20_and_reason():
    watch = _degraded(
        "WATCHLIST20",
        available=17,
        expected=20,
        reason="3 candidates lack valid current canonical evaluation",
    )
    proof = _proof(
        section_states=[_complete("ALL15", 15, 15), watch],
        section_degradations=[_degradation_record(watch)],
    )
    row = next(item for item in proof["section_states"] if item["section_id"] == "WATCHLIST20")
    assert row["state"] == "DEGRADED"
    assert row["available_count"] == 17
    assert row["expected_count"] == 20
    assert row["degradation_reason"] == "3 candidates lack valid current canonical evaluation"
    assert proof["content_contract_status"] == "DEGRADED"
    assert proof["report_can_continue"] is True


def test_08_multiple_degraded_sections_still_continue_without_hard_failure():
    watch = _degraded("WATCHLIST20", available=17, expected=20)
    icon = _degraded(
        "ICON+",
        state="UNAVAILABLE",
        reason="live mini-league scope unavailable",
    )
    proof = _proof(
        section_states=[_complete("ALL15", 15, 15), watch, icon],
        section_degradations=[
            _degradation_record(watch),
            _degradation_record(icon),
        ],
    )
    assert proof["content_contract_status"] == "DEGRADED"
    assert proof["hard_failures"] == []
    assert proof["report_can_continue"] is True
    compact = compact_visible_content_status(proof)
    assert compact["content_contract"] == "DEGRADED"
    assert {row["section"] for row in compact["degraded_sections"]} == {
        "WATCHLIST20",
        "ICON+",
    }


def test_09_hard_semantic_contradiction_requires_report_can_continue_false():
    proof = _proof(
        hard_failures=["WATCHLIST20_COMPLETE_COUNT_MISMATCH"],
        report_can_continue=False,
    )
    assert proof["content_contract_status"] == "FAIL"
    assert proof["report_can_continue"] is False
    with pytest.raises(VisibleContentProofError):
        _proof(
            hard_failures=["WATCHLIST20_COMPLETE_COUNT_MISMATCH"],
            report_can_continue=True,
        )


def test_10_python_qa_not_executed_can_never_be_claimed_pass():
    proof = _proof(repository_python_qa_executed=False, python_execution_evidence=None)
    runtime = proof["runtime_provenance"]
    assert runtime["runtime"] == RUNTIME_NAME
    assert runtime["repository_python_qa_executed"] is False
    assert runtime["python_qa_status"] == "NOT_PROVEN"
    assert runtime["python_execution_evidence"] is None
    assert runtime["python_qa_status"] != "PASS"

    with pytest.raises(VisibleContentProofError):
        _proof(
            repository_python_qa_executed=False,
            python_execution_evidence={"pre_render_status": "PASS"},
        )


def test_11_python_qa_executed_true_requires_exact_occurrence_bound_evidence():
    with pytest.raises(VisibleContentProofError):
        _proof(repository_python_qa_executed=True, python_execution_evidence={})

    evidence = {
        "report_slot": "2026-09-19T12:30:00+07:00",
        "qa_module_path": PYTHON_QA_MODULE,
        "executed_at": "2026-09-19T12:30:05+07:00",
        "pre_render_status": "PASS",
        "post_render_status": "PASS",
        "evidence_fingerprint": "b" * 64,
    }
    proof = _proof(
        repository_python_qa_executed=True,
        python_execution_evidence=evidence,
    )
    runtime = proof["runtime_provenance"]
    assert runtime["repository_python_qa_executed"] is True
    assert runtime["python_qa_status"] == "EXECUTED"
    assert runtime["python_execution_evidence"]["report_slot"] == proof["report_slot"]

    with pytest.raises(VisibleContentProofError):
        _proof(
            repository_python_qa_executed=True,
            python_execution_evidence={**evidence, "report_slot": "2026-09-19T11:30:00+07:00"},
        )


def test_12_visible_content_proof_is_transient_evidence_not_authority_or_state():
    proof = _proof()
    assert proof["proof_kind"] == "TRANSIENT_VISIBLE_CONTENT_PROOF"
    assert proof["authoritative"] is False
    assert proof["durable_state"] is False
    assert proof["persistence_forbidden"] is True
    assert "FPL_MASTER_STATE_V12" not in str(proof)
