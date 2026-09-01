from __future__ import annotations

import pytest

from src.engines import v4_validation_cycle as lifecycle


def test_existing_reconciliation_can_defer_duplicate_integrity(monkeypatch, tmp_path):
    archive = tmp_path / "gw02.json"
    archive.write_text("{}")
    sample = {
        "kind": "post_gw_reconciliation",
        "gw": 2,
        "model_version": "m",
        "report": {"metrics": {"status": "PASS", "n": 1}},
    }
    monkeypatch.setattr(lifecycle, "reconciled_path", lambda gw: archive)
    monkeypatch.setattr(lifecycle, "read_json", lambda path, default=None: sample if path == archive else default)

    def forbidden(*args, **kwargs):
        raise AssertionError("duplicate reconciliation integrity check must be deferred")

    monkeypatch.setattr(lifecycle, "reconcile_finished_gw", forbidden)
    result = lifecycle.reconcile_latest_finished(
        {"phase": {"last_finished_gw": 2}}, defer_existing_integrity=True
    )
    assert result["status"] == "PASS"
    assert result["action"] == "PRESERVED"
    assert result["integrity_deferred_to_eligibility"] is True


def test_cycle_fails_closed_when_deferred_integrity_not_proven(monkeypatch):
    raw = {"schema": "snapshot.v1", "phase": {}}
    predictions = {"model_version": "m", "players": [{"element": 1}]}
    monkeypatch.setattr(lifecycle, "capture_submitted_state", lambda *a, **k: {"status": "SKIP"})
    monkeypatch.setattr(
        lifecycle,
        "reconcile_latest_finished",
        lambda *a, **k: {
            "status": "PASS",
            "action": "PRESERVED",
            "gw": 2,
            "integrity_deferred_to_eligibility": True,
        },
    )
    monkeypatch.setattr(lifecycle, "snapshot_current", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(
        lifecycle,
        "refresh_eligible_view",
        lambda *a, **k: {"eligible_samples": 0, "eligible_gws": [], "integrity_checked_gws": []},
    )
    monkeypatch.setattr(lifecycle, "atomic_json", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="deferred reconciliation integrity was not proven"):
        lifecycle.cycle(raw=raw, predictions=predictions)


def test_cycle_accepts_deferred_integrity_after_single_pass_proof(monkeypatch):
    raw = {"schema": "snapshot.v1", "phase": {}}
    predictions = {"model_version": "m", "players": [{"element": 1}]}
    monkeypatch.setattr(lifecycle, "capture_submitted_state", lambda *a, **k: {"status": "SKIP"})
    monkeypatch.setattr(
        lifecycle,
        "reconcile_latest_finished",
        lambda *a, **k: {
            "status": "PASS",
            "action": "PRESERVED",
            "gw": 2,
            "integrity_deferred_to_eligibility": True,
        },
    )
    monkeypatch.setattr(lifecycle, "snapshot_current", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(
        lifecycle,
        "refresh_eligible_view",
        lambda *a, **k: {"eligible_samples": 0, "eligible_gws": [], "integrity_checked_gws": [2]},
    )
    monkeypatch.setattr(lifecycle, "atomic_json", lambda *a, **k: None)
    out = lifecycle.cycle(raw=raw, predictions=predictions)
    assert out["status"] == "PASS"
    assert out["reconciliation"]["integrity_verified_by_eligibility_rebuild"] is True
