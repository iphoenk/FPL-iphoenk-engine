from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.runtime_v6.wave3_proof import CORE_STAGES, evaluate_proof_window


def _proof(slot: datetime, *, run_id: int, publication_id: str | None = None) -> dict:
    iso = slot.isoformat()
    proof = {
        "schema_version": 1,
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "logical_slot": iso,
        "run_id": str(run_id),
        "run_attempt": "1",
        "core_chain_pass": True,
        "stages": {name: {"state": "PASS"} for name in CORE_STAGES},
    }
    if publication_id is not None:
        proof["publication_generation_id"] = publication_id
    return proof


def test_duplicate_publication_inside_active_six_blocks_six_of_six():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run_id=i + 1) for i in range(6)]
    proofs.append(_proof(start + timedelta(hours=5), run_id=999))

    result = evaluate_proof_window(proofs)

    duplicate_slot = (start + timedelta(hours=5)).isoformat()
    assert result["consecutive_successful_natural_slots"] == 6
    assert result["first_gate_complete"] is False
    assert result["six_of_six_complete"] is False
    assert result["two_of_two_complete"] is False
    assert result["phase"] == "6/6_IN_PROGRESS"
    assert result["duplicate_publication_slots_in_active_first_gate"] == [duplicate_slot]
    assert result["duplicate_publication_slots_in_active_six"] == [duplicate_slot]
    assert result["duplicate_publication_slots_in_active_two"] == [duplicate_slot]
    assert result["production_green_eligible"] is False


def test_historical_duplicate_outside_latest_48_does_not_poison_clean_rolling_window():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run_id=i + 1) for i in range(49)]
    proofs.append(_proof(start, run_id=999))

    result = evaluate_proof_window(proofs, chaos_acceptance_pass=True)

    assert result["duplicate_publication_slots"] == [start.isoformat()]
    assert result["duplicate_publication_slots_in_rolling_48"] == []
    assert result["rolling_48_of_48_complete"] is True
    assert result["natural_window_eligible"] is True
    assert result["production_green_eligible"] is True


def test_duplicate_evidence_for_same_publication_is_deduplicated_not_treated_as_duplicate_ownership():
    start = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
    proofs = [
        _proof(start + timedelta(hours=i), run_id=i + 1, publication_id=f"publication-{i + 1}")
        for i in range(2)
    ]
    repeated = dict(proofs[-1])
    proofs.append(repeated)

    result = evaluate_proof_window(proofs)

    duplicate_slot = (start + timedelta(hours=1)).isoformat()
    assert result["countable_proof_count"] == 2
    assert result["duplicate_publication_slots"] == []
    assert result["duplicate_evidence_slots"] == [duplicate_slot]
    assert result["two_of_two_complete"] is True
    assert result["first_gate_complete"] is False
    assert result["phase"] == "6/6_IN_PROGRESS"


def test_duplicate_publication_inside_rolling_48_blocks_production_green():
    start = datetime(2026, 9, 12, 0, tzinfo=timezone.utc)
    proofs = [_proof(start + timedelta(hours=i), run_id=i + 1) for i in range(48)]
    duplicate_slot = start + timedelta(hours=20)
    proofs.append(_proof(duplicate_slot, run_id=999))

    result = evaluate_proof_window(proofs, chaos_acceptance_pass=True)

    assert result["rolling_48_of_48_complete"] is False
    assert result["duplicate_publication_slots_in_rolling_48"] == [duplicate_slot.isoformat()]
    assert result["natural_window_eligible"] is False
    assert result["production_green_eligible"] is False
