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


def _runtime_tree(tmp_path: Path, *, schedule_kind: str = "chatgpt_scheduler", integrity: str = "PASS") -> Path:
    root = tmp_path / "data" / "v6"
    _write_json(
        root / "manifest.json",
        {
            "generated_at": "2026-09-14T06:31:10+00:00",
            "runtime_control": {
                "schedule_kind": schedule_kind,
                "chatgpt_scheduler_proof": schedule_kind == "chatgpt_scheduler",
                "counts_as_completed_operational_slot": schedule_kind == "chatgpt_scheduler",
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
        "core_chain_pass": True,
        "logical_slot": iso,
        "run_id": str(run),
        "stages": stages,
    }


def test_post_publish_proof_contains_full_core_lifecycle_and_provenance(tmp_path):
    root = _runtime_tree(tmp_path)
    proof = build_slot_proof(
        root,
        published_runtime_sha="b" * 40,
        source_commit="c" * 40,
        production_validated=True,
        run_id="12345",
        run_attempt="1",
        verified_at=datetime(2026, 9, 14, 6, 32, tzinfo=timezone.utc),
    )
    assert proof["natural_slot"] is True
    assert proof["core_chain_pass"] is True
    assert proof["candidate_generation_id"] == "12345:1:abcdef0123456789"
    assert proof["publication_generation_id"] == f"runtime-data-v6:{'b' * 40}"
    assert proof["registry_fingerprint"] == "f" * 64
    assert proof["published_runtime_sha"] == "b" * 40
    assert proof["governance"]["proof_created_post_publish_without_runtime_tree_mutation"] is True
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


def test_report_prefetch_and_manual_recovery_cannot_be_counted_as_natural_core_proof(tmp_path):
    for kind in ("report_prefetch", "manual_recovery"):
        root = _runtime_tree(tmp_path / kind, schedule_kind=kind)
        with pytest.raises(Wave3ProofError, match="not_genuine_natural_core_slot"):
            build_slot_proof(
                root,
                published_runtime_sha="b" * 40,
                source_commit="c" * 40,
                production_validated=True,
                run_id="12345",
                run_attempt="1",
            )


def test_corrupt_candidate_cannot_receive_successful_wave3_proof(tmp_path):
    root = _runtime_tree(tmp_path, integrity="FAIL")
    with pytest.raises(Wave3ProofError, match="publish_integrity_not_pass"):
        build_slot_proof(
            root,
            published_runtime_sha="b" * 40,
            source_commit="c" * 40,
            production_validated=True,
            run_id="12345",
            run_attempt="1",
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


def test_six_consecutive_natural_slots_complete_first_gate():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(6)]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "48/48_IN_PROGRESS"
    assert result["consecutive_successful_natural_slots"] == 6
    assert result["six_of_six_complete"] is True
    assert result["rolling_48_of_48_complete"] is False
    assert result["production_green_eligible"] is False


def test_gap_resets_consecutive_natural_slot_count():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [
        _proof(start, run=1),
        _proof(start + timedelta(hours=1), run=2),
        _proof(start + timedelta(hours=4), run=3),
        _proof(start + timedelta(hours=5), run=4),
    ]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "6/6_IN_PROGRESS"
    assert result["consecutive_successful_natural_slots"] == 2
    assert result["six_of_six_complete"] is False


def test_exact_rolling_48_natural_slots_are_required_for_production_green_eligibility():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(48)]
    result = evaluate_proof_window(proofs)
    assert result["phase"] == "48/48_COMPLETE"
    assert result["consecutive_successful_natural_slots"] == 48
    assert result["rolling_48_of_48_complete"] is True
    assert result["production_green_eligible"] is True


def test_duplicate_logical_slot_blocks_rolling_48_acceptance():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run=i + 1) for i in range(48)]
    proofs.append(_proof(start + timedelta(hours=47), run=999))
    result = evaluate_proof_window(proofs)
    assert result["duplicate_logical_slots"] == [(start + timedelta(hours=47)).isoformat()]
    assert result["rolling_48_of_48_complete"] is False
    assert result["production_green_eligible"] is False
