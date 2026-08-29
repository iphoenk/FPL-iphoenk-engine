from __future__ import annotations

import inspect
from pathlib import Path

from src.engines import v4_validation_cycle
from src.services import reconciliation_readiness_service, validation_service


def test_validation_lifecycle_accepts_preloaded_snapshot_without_file_reads(monkeypatch):
    raw = {"schema": "snapshot.v1", "checkpoint_context": {}}
    predictions = {"model_version": "test-model", "players": [{"element": 1}]}

    def forbidden_read(*_args, **_kwargs):
        raise AssertionError("preloaded lifecycle snapshot must not be reread from disk")

    monkeypatch.setattr(v4_validation_cycle, "read_json", forbidden_read)
    monkeypatch.setattr(v4_validation_cycle, "atomic_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(v4_validation_cycle, "capture_submitted_state", lambda raw, now=None: {"status": "SKIP"})
    monkeypatch.setattr(v4_validation_cycle, "reconcile_latest_finished", lambda raw, now=None: {"status": "SKIP"})
    monkeypatch.setattr(v4_validation_cycle, "snapshot_current", lambda raw, predictions, now=None: {"status": "PASS"})
    monkeypatch.setattr(v4_validation_cycle, "refresh_eligible_view", lambda model: {"model_version": model, "eligible_samples": 0})

    out = v4_validation_cycle.cycle(raw=raw, predictions=predictions)

    assert out["status"] == "PASS"
    assert out["guardrails"]["preloaded_snapshot_contract_equivalent"] is True


def test_reconciliation_readiness_reuses_preloaded_raw_lifecycle_and_ownership(monkeypatch):
    raw = {
        "schema": "snapshot.v1",
        "generated_at": "2026-08-29T19:00:00+00:00",
        "phase": {"submitted_gw": 1, "last_finished_gw": 1, "scoring_gw": 2},
        "official": {"picks": {"picks": []}, "event_live": {"elements": []}},
    }
    lifecycle = {"status": "PASS", "snapshot": {"status": "PASS"}, "eligibility": {"eligible_gws": []}}
    ownership = {
        "responsibilities": [
            {"id": "OFFICIAL_FPL_ACQUISITION", "owner": "raw_snapshot", "execution_boundary": "raw_snapshot"},
            {"id": "VALIDATION_STORE", "owner": "validation_store", "execution_boundary": "validation"},
            {"id": "RECONCILIATION_TRUTH", "owner": "reconciliation_truth", "execution_boundary": "validation"},
            {"id": "VALIDATION_LIFECYCLE", "owner": "validation_lifecycle", "execution_boundary": "validation"},
            {"id": "RECONCILIATION_READINESS", "owner": "reconciliation_readiness", "execution_boundary": "validation"},
        ]
    }
    deadline_path = Path("deadline-gw2.json")
    archive_path = Path("archive-gw2.json")

    monkeypatch.setattr(reconciliation_readiness_service, "_target_gw", lambda: 2)
    monkeypatch.setattr(reconciliation_readiness_service.store, "deadline_snapshot_path", lambda gw: deadline_path)
    monkeypatch.setattr(reconciliation_readiness_service.store, "reconciled_path", lambda gw: archive_path)
    monkeypatch.setattr(reconciliation_readiness_service.store, "snapshot_integrity", lambda snapshot, gw: (True, "ok"))
    monkeypatch.setattr(reconciliation_readiness_service, "atomic_json", lambda *_args, **_kwargs: None)

    def guarded_read(path, default=None):
        if path in {
            reconciliation_readiness_service.RAW_SNAPSHOT,
            reconciliation_readiness_service.LIFECYCLE,
            reconciliation_readiness_service.OWNERSHIP,
        }:
            raise AssertionError(f"preloaded readiness input reread from disk: {path}")
        if path == deadline_path:
            return {"deadline_time": "2026-08-30T20:00:00+00:00", "players": [{"element": 1}]}
        if path == archive_path:
            return {}
        return default if default is not None else {}

    monkeypatch.setattr(reconciliation_readiness_service, "read_json", guarded_read)

    out = reconciliation_readiness_service.run(raw=raw, lifecycle=lifecycle, ownership=ownership)

    assert out["status"] == "PASS"
    assert out["stage"] == "PREDEADLINE_READY"
    assert out["input_reuse"] == {
        "raw_snapshot_preloaded": True,
        "lifecycle_preloaded": True,
        "ownership_preloaded": True,
    }
    assert out["guardrails"]["preloaded_input_contract_equivalent"] is True


def test_consolidated_validation_wires_parent_snapshot_into_lifecycle_and_readiness():
    source = inspect.getsource(validation_service.run)
    assert "v4_validation_cycle.cycle(raw=raw_snapshot, predictions=predictions_snapshot)" in source
    assert "reconciliation_readiness_service.run(raw=raw_snapshot, lifecycle=lifecycle)" in source
    assert "parent_snapshot_reuse_fail_closed" in source
