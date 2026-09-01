from __future__ import annotations

import inspect
import json

from src.engines import v4_maturity_reconciler as maturity
from src.engines.v4_backtest_store import _digest
from src.services import governance_live_overlay, governance_service, hot_orchestrator


def _sample():
    return {
        "kind": "post_gw_reconciliation",
        "gw": 2,
        "model_version": "m",
        "immutable": True,
        "sample_eligible": True,
        "report": {"metrics": {"status": "PASS", "n": 1, "leakage_rejected": 0}},
    }


def test_maturity_reuses_exact_same_cycle_integrity_proof(monkeypatch, tmp_path):
    sample = _sample()
    (tmp_path / "gw02.json").write_text(json.dumps(sample))
    monkeypatch.setattr(maturity, "RECONCILED", tmp_path)
    monkeypatch.setattr(maturity, "promotion_gate", lambda *_a, **_k: {"promote": False})
    monkeypatch.setattr(maturity, "reconciled_integrity", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("full source integrity must not repeat")))
    proof = {
        "model_version": "m",
        "single_pass_source_integrity": True,
        "integrity_checked_gws": [2],
        "integrity_checked_sha256": {"2": _digest(sample)},
    }
    active, detail = maturity._calibration_maturity_evidence({"model_version": "m"}, validation_eligibility=proof)
    assert active is False
    assert detail["validation_integrity_proof_reused_gws"] == [2]
    assert detail["fallback_full_integrity_gws"] == []


def test_maturity_rejects_changed_reconciliation_after_validation(monkeypatch, tmp_path):
    sample = _sample()
    (tmp_path / "gw02.json").write_text(json.dumps(sample))
    monkeypatch.setattr(maturity, "RECONCILED", tmp_path)
    monkeypatch.setattr(maturity, "promotion_gate", lambda *_a, **_k: {"promote": False})
    monkeypatch.setattr(maturity, "reconciled_integrity", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("mismatched supplied proof must fail closed")))
    proof = {
        "model_version": "m",
        "single_pass_source_integrity": True,
        "integrity_checked_gws": [2],
        "integrity_checked_sha256": {"2": "0" * 64},
    }
    _, detail = maturity._calibration_maturity_evidence({"model_version": "m"}, validation_eligibility=proof)
    assert detail["validation_integrity_proof_reused_gws"] == []
    assert detail["rejected_samples"][0]["reason"] == "same_cycle_integrity_proof_mismatch"


def test_governance_and_hot_path_keep_optional_file_backed_fallbacks():
    g = inspect.getsource(governance_service.run)
    overlay = inspect.getsource(governance_live_overlay.run)
    hot = inspect.getsource(hot_orchestrator.run)
    worker = inspect.getsource(hot_orchestrator._validation_worker)
    assert "predictions_snapshot if predictions_preloaded else read_json" in g
    assert "validation_eligibility=validation_eligibility" in g
    assert "else governance_service.run()" in overlay
    assert "run(return_predictions=True)" in hot
    assert "governance_live_overlay.run(predictions_snapshot=predictions_snapshot)" in hot
    assert "validation_service.run(predictions_snapshot=predictions_snapshot)" in worker
