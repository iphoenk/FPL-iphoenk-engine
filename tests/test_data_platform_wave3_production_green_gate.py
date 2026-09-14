from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime_v6.wave3_chaos_acceptance import EXPECTED_SCENARIO_IDS
from src.runtime_v6.wave3_proof import CORE_STAGES, Wave3ProofError
from src.runtime_v6.wave3_window import build_window_summary


def _proof(slot: datetime, run_id: int) -> dict:
    iso = slot.isoformat()
    stages = {name: {"state": "PASS", "at": iso, "evidence": name} for name in CORE_STAGES}
    return {
        "schema_version": 1,
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "logical_slot": iso,
        "observed_at": (slot + timedelta(minutes=31)).isoformat(),
        "run_id": str(run_id),
        "run_attempt": "1",
        "stages": stages,
        "core_chain_pass": True,
    }


def _write_48_proofs(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    start = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
    for index in range(47):
        (prior / f"proof-{index}.json").write_text(
            json.dumps(_proof(start + timedelta(hours=index), 1000 + index)), encoding="utf-8"
        )
    current = tmp_path / "current.json"
    current.write_text(json.dumps(_proof(start + timedelta(hours=47), 1047)), encoding="utf-8")
    return prior, current


def _write_chaos_acceptance(tmp_path, *, status: str = "PASS"):
    path = tmp_path / "wave3-chaos-acceptance.json"
    scenarios = [
        {"scenario_id": scenario_id, "status": "PASS"}
        for scenario_id in sorted(EXPECTED_SCENARIO_IDS)
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "acceptance_kind": "WAVE3_CONTROLLED_CHAOS_MATRIX",
                "status": status,
                "evaluated_at": "2026-09-14T06:54:36Z",
                "evidence_scope": "DETERMINISTIC_CI_READ_ONLY",
                "junit_sha256": "a" * 64,
                "runtime_write_authorized": False,
                "natural_slot_counter_affected": False,
                "canonical_scenario_count": 16,
                "passed_scenario_count": 16,
                "failed_or_missing_scenario_count": 0,
                "scenarios": scenarios,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_rolling_48_without_chaos_acceptance_cannot_be_production_green(tmp_path):
    prior, current = _write_48_proofs(tmp_path)

    summary = build_window_summary(prior, current)

    assert summary["rolling_48_of_48_complete"] is True
    assert summary["natural_window_eligible"] is True
    assert summary["chaos_acceptance_pass"] is False
    assert summary["production_green_eligible"] is False
    assert summary["chaos_acceptance"]["status"] == "NOT_PROVIDED"


def test_rolling_48_plus_valid_bound_chaos_acceptance_is_production_green_eligible(tmp_path):
    prior, current = _write_48_proofs(tmp_path)
    chaos = _write_chaos_acceptance(tmp_path)

    summary = build_window_summary(
        prior,
        current,
        chaos_acceptance=chaos,
        chaos_source_run_id="34815393691",
        chaos_source_head_sha="7" * 40,
        chaos_artifact_name="v6-wave3-chaos-acceptance-34815393691-1",
    )

    assert summary["rolling_48_of_48_complete"] is True
    assert summary["natural_window_eligible"] is True
    assert summary["chaos_acceptance_pass"] is True
    assert summary["production_green_eligible"] is True
    assert summary["chaos_acceptance"]["canonical_scenario_count"] == 16
    assert summary["chaos_acceptance"]["passed_scenario_count"] == 16
    assert summary["chaos_acceptance"]["source_run_id"] == "34815393691"
    assert summary["chaos_acceptance"]["source_head_sha"] == "7" * 40


def test_failed_or_incomplete_chaos_acceptance_is_rejected_fail_closed(tmp_path):
    prior, current = _write_48_proofs(tmp_path)
    chaos = _write_chaos_acceptance(tmp_path, status="FAIL")

    with pytest.raises(Wave3ProofError, match="wave3_chaos_acceptance_not_pass:status"):
        build_window_summary(
            prior,
            current,
            chaos_acceptance=chaos,
            chaos_source_run_id="34815393691",
            chaos_source_head_sha="7" * 40,
            chaos_artifact_name="v6-wave3-chaos-acceptance-34815393691-1",
        )


def test_valid_chaos_payload_without_verified_ci_provenance_is_rejected(tmp_path):
    prior, current = _write_48_proofs(tmp_path)
    chaos = _write_chaos_acceptance(tmp_path)

    with pytest.raises(Wave3ProofError, match="wave3_chaos_source_run_id_missing"):
        build_window_summary(prior, current, chaos_acceptance=chaos)
