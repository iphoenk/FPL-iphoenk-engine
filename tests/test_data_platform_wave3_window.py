from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime_v6.wave3_proof import CORE_STAGES, Wave3ProofError
from src.runtime_v6.wave3_window import build_window_summary


def _proof(slot: datetime, run_id: int) -> dict:
    iso = slot.isoformat()
    stages = {name: {"state": "PASS", "at": iso, "evidence": name} for name in CORE_STAGES}
    stages["PREFETCHED"] = {"state": "N/A", "at": None, "evidence": "not_required"}
    stages["DELIVERED"] = {"state": "N/A", "at": None, "evidence": "separate"}
    return {
        "schema_version": 1,
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "logical_slot": iso,
        "observed_at": (slot + timedelta(minutes=31)).isoformat(),
        "run_id": str(run_id),
        "run_attempt": "1",
        "published_runtime_sha": f"{run_id:040x}"[-40:],
        "candidate_generation_id": f"candidate-{run_id}",
        "publication_generation_id": f"publication-{run_id}",
        "registry_fingerprint": "a" * 64,
        "candidate_tree_sha256": "b" * 64,
        "published_tree_sha256": "c" * 64,
        "stages": stages,
        "core_chain_pass": True,
    }


def test_window_summary_counts_prior_artifacts_plus_current_without_inference(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    start = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)
    for index in range(5):
        (prior / f"proof-{index}.json").write_text(
            json.dumps(_proof(start + timedelta(hours=index), 100 + index)), encoding="utf-8"
        )
    current = tmp_path / "current.json"
    current.write_text(json.dumps(_proof(start + timedelta(hours=5), 105)), encoding="utf-8")

    summary = build_window_summary(prior, current)

    assert summary["countable_proof_count"] == 6
    assert summary["consecutive_successful_natural_slots"] == 6
    assert summary["six_of_six_complete"] is True
    assert summary["rolling_48_of_48_complete"] is False
    assert summary["phase"] == "48/48_IN_PROGRESS"
    assert summary["future_slots_inferred"] is False
    assert summary["manual_or_controlled_runs_count"] == 0
    assert summary["production_green_eligible"] is False


def test_window_summary_duplicate_slot_blocks_production_green(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    start = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
    for index in range(48):
        (prior / f"proof-{index}.json").write_text(
            json.dumps(_proof(start + timedelta(hours=index), 200 + index)), encoding="utf-8"
        )
    current = tmp_path / "current.json"
    current.write_text(json.dumps(_proof(start + timedelta(hours=47), 999)), encoding="utf-8")

    summary = build_window_summary(prior, current)

    assert summary["duplicate_logical_slots"] == [(start + timedelta(hours=47)).isoformat()]
    assert summary["rolling_48_of_48_complete"] is False
    assert summary["production_green_eligible"] is False


def test_window_summary_fails_closed_on_malformed_prefixed_proof_artifact(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "broken.json").write_text("not-json", encoding="utf-8")
    current = tmp_path / "current.json"
    current.write_text(json.dumps(_proof(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc), 1)), encoding="utf-8")

    with pytest.raises(Wave3ProofError, match="invalid_wave3_proof"):
        build_window_summary(prior, current)
