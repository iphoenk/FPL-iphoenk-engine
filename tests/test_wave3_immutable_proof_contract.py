from __future__ import annotations

import pytest

from src.runtime_v6.wave3_proof import Wave3ProofError, validate_immutable_natural_proof_binding


def test_wave3_proof_binds_exact_run_artifact_not_branch_head():
    proof = {
        "run_id": "38478448872",
        "run_attempt": "1",
        "source_commit": "a" * 40,
        "logical_slot": "2026-10-14T05:30:00+07:00",
        "candidate_generation_id": "38478448872:1:candidate",
        "publication_receipt": {
            "run_id": "38478448872",
            "artifact_sha256": "b" * 64,
            "logical_slot": "2026-10-14T05:30:00+07:00",
        },
    }
    result = validate_immutable_natural_proof_binding(
        proof,
        branch_head="c" * 40,
        artifact_sha256="b" * 64,
    )
    assert result["status"] == "PASS"
    assert result["branch_head_ignored_for_identity"] is True


def test_wave3_proof_rejects_receipt_run_mismatch():
    proof = {
        "run_id": "38478448872",
        "run_attempt": "1",
        "source_commit": "a" * 40,
        "logical_slot": "2026-10-14T05:30:00+07:00",
        "candidate_generation_id": "38478448872:1:candidate",
        "publication_receipt": {
            "run_id": "other",
            "artifact_sha256": "b" * 64,
            "logical_slot": "2026-10-14T05:30:00+07:00",
        },
    }
    with pytest.raises(Wave3ProofError, match="immutable_proof_binding_failed"):
        validate_immutable_natural_proof_binding(
            proof,
            branch_head="c" * 40,
            artifact_sha256="b" * 64,
        )

