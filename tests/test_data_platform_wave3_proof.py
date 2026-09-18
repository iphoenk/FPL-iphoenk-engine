from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime_v6.wave3_proof import (
    Wave3ProofError,
    assert_rejected_candidate_did_not_move_runtime,
    build_slot_proof,
    evaluate_proof_window,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _runtime_tree(
    tmp_path: Path,
    *,
    schedule_kind: str = "chatgpt_scheduler",
    event_name: str = "issues",
    integrity: str = "PASS",
) -> Path:
    root = tmp_path / "data" / "v6"
    natural_kind = schedule_kind == "chatgpt_scheduler"
    _write_json(
        root / "manifest.json",
        {
            "generated_at": "2026-09-14T06:31:10+00:00",
            "runtime_control": {
                "event_name": event_name,
                "schedule_kind": schedule_kind,
                "chatgpt_scheduler_proof": natural_kind,
                "counts_as_completed_operational_slot": natural_kind,
                "authoritative_runtime_snapshot": natural_kind,
                "logical_slot_source": "GOVERNED_TRIGGER_EVENT" if natural_kind else "RUNTIME_CLOCK",
                "expected_cycle_at": "2026-09-14T06:00:00+00:00",
                "cycle_observed_at": "2026-09-14T06:31:00+00:00",
            },
        },
    )
    _write_json(
        root / "health" / "candidate_freeze.lock",
        {
            "candidate_state": "FROZEN",
            "frozen_at": "2026-09-14T06:31:11+00:00",
            "run_id": "12345",
            "run_attempt": "1",
            "candidate_generation_id": "12345:1:abcdef0123456789",
            "registry_fingerprint": "f" * 64,
            "registry_epoch": "epoch-1",
            "candidate_tree_sha256": "a" * 64,
        },
    )
    _write_json(
        root / "health" / "publish_integrity.json",
        {
            "status": integrity,
            "tree_sha256": "a" * 64,
            "errors": [] if integrity == "PASS" else ["corrupt_candidate"],
        },
    )
    return root


def _proof(slot: datetime, *, run: int = 1) -> dict:
    iso = slot.astimezone(timezone.utc).isoformat()
    stages = {
        name: {"state": "PASS"}
        for name in (
            "TRIGGERED",
            "ACQUIRED",
            "STAGED",
            "FROZEN",
            "INTEGRITY_PASS",
            "VALIDATED",
            "PROMOTED",
        )
    }
    return {
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "core_chain_pass": True,
        "logical_slot": iso,
        "run_id": str(run),
        "run_attempt": "1",
        "publication_generation_id": f"publication-{run}",
        "stages": stages,
    }


def test_post_publish_proof_contains_full_core_lifecycle_and_provenance(tmp_path):
    root = _runtime_tree(tmp_path)
    proof = build_slot_proof(
        root,
        published_runtime_sha="b" * 40,
        source_commit="c" * 40,
        production_validated=True,
        promotion_verified=True,
        run_id="12345",
        run_attempt="1",
        collect_job_id="501",
        publish_job_id="502",
        fulfillment_job_id="503",
        verified_at=datetime(2026, 9, 14, 6, 32, tzinfo=timezone.utc),
    )
    assert proof["natural_slot"] is True
    assert proof["natural_transport"] == "FPL_MASTER_SLOT_ISSUE_TITLE"
    assert proof["core_trigger_source"] == "GOVERNED_TRIGGER_EVENT"
    assert proof["logical_slot_source"] == "GOVERNED_TRIGGER_EVENT"
    assert proof["audit_transport_required_for_core_proof"] is False
    assert proof["core_chain_pass"] is True
    assert proof["candidate_generation_id"] == "12345:1:abcdef0123456789"
    assert proof["publication_generation_id"] == "v6-publication:12345:1:12345:1:abcdef0123456789"
    assert proof["registry_fingerprint"] == "f" * 64
    assert proof["published_runtime_sha"] == "b" * 40
    assert proof["workflow_run_id"] == "12345"
    assert proof["acquisition_run_id"] == "501"
    assert proof["publication_run_id"] == "502"
    assert proof["orchestration_fulfillment_run_id"] == "503"
    assert proof["governance"]["proof_created_post_publish_without_runtime_tree_mutation"] is True
    assert proof["governance"]["initial_natural_gate_consecutive_slots"] == 6
    assert proof["governance"]["production_green_requires_controlled_chaos_acceptance"] is True
    for stage in (
        "TRIGGERED",
        "ACQUIRED",
        "STAGED",
        "FROZEN",
        "INTEGRITY_PASS",
        "VALIDATED",
        "PROMOTED",
    ):
        assert proof["stages"][stage]["state"] == "PASS"


def test_controlled_issue_comment_master_acquire_cannot_count_as_natural_proof(tmp_path):
    root = _runtime_tree(tmp_path, schedule_kind="chatgpt_scheduler", event_name="issue_comment")
    with pytest.raises(Wave3ProofError, match="not_genuine_natural_core_transport"):
        build_slot_proof(
            root,
            source_commit="c" * 40,
            production_validated=True,
            promotion_verified=True,
            run_id="12345",
            run_attempt="1",
        collect_job_id="501",
        publish_job_id="502",
        fulfillment_job_id="503",
        )


def test_report_prefetch_and_manual_recovery_cannot_be_counted_as_natural_core_proof(tmp_path):
    for kind in ("report_prefetch", "manual_recovery"):
        root = _runtime_tree(tmp_path / kind, schedule_kind=kind, event_name="issue_comment")
        with pytest.raises(Wave3ProofError, match="not_genuine_natural_core_transport"):
            build_slot_proof(
                root,
                source_commit="c" * 40,
                production_validated=True,
                promotion_verified=True,
                run_id="12345",
                run_attempt="1",
        collect_job_id="501",
        publish_job_id="502",
        fulfillment_job_id="503",
            )


def test_corrupt_candidate_cannot_receive_successful_wave3_proof(tmp_path):
    root = _runtime_tree(tmp_path, integrity="FAIL")
    with pytest.raises(Wave3ProofError, match="publish_integrity_not_pass"):
        build_slot_proof(
            root,
            source_commit="c" * 40,
            production_validated=True,
            promotion_verified=True,
            run_id="12345",
            run_attempt="1",
        collect_job_id="501",
        publish_job_id="502",
        fulfillment_job_id="503",
        )


def test_promotion_must_be_proven_by_successful_source_publish_job(tmp_path):
    root = _runtime_tree(tmp_path)
    with pytest.raises(Wave3ProofError, match="promotion_not_proven"):
        build_slot_proof(
            root,
            source_commit="c" * 40,
            production_validated=True,
            promotion_verified=False,
            run_id="12345",
            run_attempt="1",
        collect_job_id="501",
        publish_job_id="502",
        fulfillment_job_id="503",
        )


def test_publisher_rejection_must_leave_runtime_pointer_unchanged():
    assert_rejected_candidate_did_not_move_runtime(
        runtime_sha_before="a" * 40,
        runtime_sha_after="a" * 40,
        candidate_accepted=False,
    )
    with pytest.raises(Wave3ProofError, match="rejected_candidate_moved_runtime_pointer"):
        assert_rejected_candidate_did_not_move_runtime(
            runtime_sha_before="a" * 40,
            runtime_sha_after="b" * 40,
            candidate_accepted=False,
        )


def test_five_consecutive_natural_slots_do_not_complete_six_slot_first_gate():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(5)]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "6/6_IN_PROGRESS"
    assert result["consecutive_successful_natural_slots"] == 5
    assert result["first_gate_target"] == 6
    assert result["first_gate_complete"] is False
    assert result["two_of_two_complete"] is True
    assert result["six_of_six_complete"] is False
    assert result["rolling_12_of_12_complete"] is False
    assert result["production_green_eligible"] is False


def test_six_consecutive_natural_slots_complete_first_gate_and_enter_rolling_12():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(6)]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "12/12_IN_PROGRESS"
    assert result["consecutive_successful_natural_slots"] == 6
    assert result["first_gate_target"] == 6
    assert result["first_gate_complete"] is True
    assert result["two_of_two_complete"] is True
    assert result["six_of_six_complete"] is True
    assert result["rolling_12_of_12_complete"] is False
    assert result["production_green_eligible"] is False


def test_gap_resets_consecutive_natural_slot_count_before_six_of_six_gate():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [
        _proof(start, run=1),
        _proof(start + timedelta(hours=1), run=2),
        _proof(start + timedelta(hours=4), run=3),
    ]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "6/6_IN_PROGRESS"
    assert result["consecutive_successful_natural_slots"] == 1
    assert result["first_gate_complete"] is False
    assert result["two_of_two_complete"] is False
    assert result["six_of_six_complete"] is False


def test_exact_rolling_12_requires_chaos_acceptance_for_production_green_eligibility():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(12)]

    natural_only = evaluate_proof_window(proofs)
    assert natural_only["phase"] == "12/12_COMPLETE"
    assert natural_only["consecutive_successful_natural_slots"] == 12
    assert natural_only["first_gate_complete"] is True
    assert natural_only["six_of_six_complete"] is True
    assert natural_only["rolling_12_of_12_complete"] is True
    assert natural_only["natural_window_eligible"] is True
    assert natural_only["chaos_acceptance_pass"] is False
    assert natural_only["production_green_eligible"] is False

    combined = evaluate_proof_window(proofs, chaos_acceptance_pass=True)
    assert combined["natural_window_eligible"] is True
    assert combined["chaos_acceptance_pass"] is True
    assert combined["production_green_eligible"] is True


def test_duplicate_logical_slot_blocks_rolling_12_acceptance():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(12)]
    proofs.append(_proof(start + timedelta(hours=11), run=999))
    result = evaluate_proof_window(proofs, chaos_acceptance_pass=True)
    assert result["duplicate_logical_slots"] == [(start + timedelta(hours=11)).isoformat()]
    assert result["rolling_12_of_12_complete"] is False
    assert result["natural_window_eligible"] is False
    assert result["production_green_eligible"] is False
