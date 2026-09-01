from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label} anchor not found in {path}")
    p.write_text(text.replace(old, new, 1))


# Prediction optional in-memory contract handoff.
replace_once(
    "src/services/prediction_service.py",
    "def run():",
    "def run(*, return_predictions: bool = False):",
    "prediction signature",
)
replace_once(
    "src/services/prediction_service.py",
    '\n    return latest\n\n\nif __name__ == "__main__":\n',
    '\n    if return_predictions:\n        return {"latest": latest, "predictions": predictions}\n    return latest\n\n\nif __name__ == "__main__":\n',
    "prediction return bundle",
)
replace_once(
    "src/services/prediction_service_price_mover.py",
    "def run():\n    result = run_prediction()\n    patch_price_artifacts(DATA)\n    return result\n",
    "def run(*, return_predictions: bool = False):\n    result = run_prediction(return_predictions=True) if return_predictions else run_prediction()\n    patch_price_artifacts(DATA)\n    return result\n",
    "prediction wrapper",
)

# Validation optional prediction handoff, default file-backed path preserved.
replace_once(
    "src/services/validation_service.py",
    "def run() -> dict:",
    "def run(*, predictions_snapshot: dict | None = None) -> dict:",
    "validation signature",
)
replace_once(
    "src/services/validation_service.py",
    '    snapshot_started = perf_counter()\n    raw_snapshot = read_json(RAW_SNAPSHOT, {})\n    predictions_snapshot = read_json(PREDICTIONS, {})\n    timings["parent_snapshot_load_ms"] = round((perf_counter() - snapshot_started) * 1000.0, 2)\n',
    '    snapshot_started = perf_counter()\n    raw_snapshot = read_json(RAW_SNAPSHOT, {})\n    predictions_preloaded = predictions_snapshot is not None\n    if predictions_snapshot is None:\n        predictions_snapshot = read_json(PREDICTIONS, {})\n    timings["parent_snapshot_load_ms"] = round((perf_counter() - snapshot_started) * 1000.0, 2)\n',
    "validation prediction load",
)
replace_once(
    "src/services/validation_service.py",
    '            "parent_predictions_loaded_once": True,\n            "lifecycle_received_preloaded_raw": True,\n',
    '            "parent_predictions_loaded_once": not predictions_preloaded,\n            "parent_predictions_received_preloaded": predictions_preloaded,\n            "lifecycle_received_preloaded_raw": True,\n',
    "validation reuse evidence",
)
replace_once(
    "src/services/validation_service.py",
    '            "parent_snapshot_reuse_fail_closed": True,\n            "official_api_refetch": False,\n',
    '            "parent_snapshot_reuse_fail_closed": True,\n            "prediction_handoff_is_explicit_optional_input": True,\n            "file_backed_prediction_fallback_preserved": True,\n            "official_api_refetch": False,\n',
    "validation reuse guardrail",
)

# Validation eligibility records digest of exact reconciliation bytes/object whose
# immutable source integrity was fully verified in this cycle.
replace_once(
    "src/engines/v4_backtest_store.py",
    "    integrity_checked: list[int] = []\n    rejected: list[dict] = []\n",
    "    integrity_checked: list[int] = []\n    integrity_checked_sha256: dict[str, str] = {}\n    rejected: list[dict] = []\n",
    "eligibility digest registry",
)
replace_once(
    "src/engines/v4_backtest_store.py",
    '            gw = int(sample.get("gw"))\n            integrity_checked.append(gw)\n            if model_version and sample.get("model_version") != model_version:\n',
    '            gw = int(sample.get("gw"))\n            integrity_checked.append(gw)\n            integrity_checked_sha256[str(gw)] = _digest(sample)\n            if model_version and sample.get("model_version") != model_version:\n',
    "eligibility digest capture",
)
replace_once(
    "src/engines/v4_backtest_store.py",
    '        "integrity_checked_gws": integrity_checked,\n        "rejected_samples": rejected,\n',
    '        "integrity_checked_gws": integrity_checked,\n        "integrity_checked_sha256": integrity_checked_sha256,\n        "rejected_samples": rejected,\n',
    "eligibility digest output",
)

# Maturity consumes same-cycle exact digest proof. Without proof, the original full
# reconciled_integrity path remains the fallback. Supplied mismatched proof fails closed.
replace_once(
    "src/engines/v4_maturity_reconciler.py",
    "from src.engines.v4_backtest_store import reconciled_integrity\n",
    "from src.engines.v4_backtest_store import _digest, reconciled_integrity\n",
    "maturity digest import",
)
replace_once(
    "src/engines/v4_maturity_reconciler.py",
    '''def _calibration_maturity_evidence(predictions: dict) -> tuple[bool, dict]:
    model_version = predictions.get("model_version")
    paths = sorted(RECONCILED.glob("gw*.json")) if RECONCILED.exists() else []
    eligible: list[dict] = []
    rejected: list[dict] = []
    passing: list[dict] = []
    best_observed_n = 0

    for path in paths:
        sample = read_json(path, {})
        ok, reason = reconciled_integrity(sample, model_version=model_version)
        if not ok:
            rejected.append({"file": path.name, "reason": reason})
            continue
        gw = int(sample.get("gw") or 0)
''',
    '''def _calibration_maturity_evidence(
    predictions: dict,
    validation_eligibility: dict | None = None,
) -> tuple[bool, dict]:
    model_version = predictions.get("model_version")
    paths = sorted(RECONCILED.glob("gw*.json")) if RECONCILED.exists() else []
    eligible: list[dict] = []
    rejected: list[dict] = []
    passing: list[dict] = []
    best_observed_n = 0
    proof = validation_eligibility if isinstance(validation_eligibility, dict) else {}
    proof_usable = (
        proof.get("single_pass_source_integrity") is True
        and proof.get("model_version") == model_version
    )
    proof_gws = {int(value) for value in (proof.get("integrity_checked_gws") or [])}
    proof_digests = proof.get("integrity_checked_sha256") or {}
    proof_reused_gws: list[int] = []
    fallback_full_integrity_gws: list[int] = []

    for path in paths:
        sample = read_json(path, {})
        gw = int(sample.get("gw") or 0)
        expected_digest = proof_digests.get(str(gw)) if proof_usable and gw in proof_gws else None
        if expected_digest is not None:
            metrics = ((sample.get("report") or {}).get("metrics") or {})
            proof_ok = (
                sample.get("kind") == "post_gw_reconciliation"
                and sample.get("immutable") is True
                and sample.get("sample_eligible") is True
                and sample.get("model_version") == model_version
                and metrics.get("status") == "PASS"
                and int(metrics.get("n") or 0) > 0
                and int(metrics.get("leakage_rejected") or 0) == 0
                and _digest(sample) == expected_digest
            )
            if not proof_ok:
                rejected.append({"file": path.name, "reason": "same_cycle_integrity_proof_mismatch"})
                continue
            proof_reused_gws.append(gw)
        else:
            ok, reason = reconciled_integrity(sample, model_version=model_version)
            fallback_full_integrity_gws.append(gw)
            if not ok:
                rejected.append({"file": path.name, "reason": reason})
                continue
''',
    "maturity calibration proof reuse",
)
replace_once(
    "src/engines/v4_maturity_reconciler.py",
    '        "rejected_samples": rejected,\n        "passing_gws": [row["gw"] for row in passing],\n',
    '        "rejected_samples": rejected,\n        "validation_integrity_proof_reused_gws": proof_reused_gws,\n        "fallback_full_integrity_gws": fallback_full_integrity_gws,\n        "same_cycle_integrity_proof_requires_exact_digest": True,\n        "passing_gws": [row["gw"] for row in passing],\n',
    "maturity proof telemetry",
)
replace_once(
    "src/engines/v4_maturity_reconciler.py",
    "    universe: dict | None = None,\n    persist: bool = True,\n) -> dict:\n",
    "    universe: dict | None = None,\n    validation_eligibility: dict | None = None,\n    persist: bool = True,\n) -> dict:\n",
    "maturity reconcile signature",
)
replace_once(
    "src/engines/v4_maturity_reconciler.py",
    "    calibration_active, calibration_detail = _calibration_maturity_evidence(predictions)\n",
    "    calibration_active, calibration_detail = _calibration_maturity_evidence(\n        predictions, validation_eligibility=validation_eligibility\n    )\n",
    "maturity proof wiring",
)

# Governance prediction handoff + validation eligibility proof handoff.
replace_once(
    "src/services/governance_service.py",
    "def run() -> dict:\n",
    "def run(*, predictions_snapshot: dict | None = None) -> dict:\n",
    "governance signature",
)
replace_once(
    "src/services/governance_service.py",
    '    predictions = read_json(DATA / "predictions_v4.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    universe = read_json(DATA / "universe.json", {})\n',
    '    predictions_preloaded = predictions_snapshot is not None\n    predictions = predictions_snapshot if predictions_preloaded else read_json(DATA / "predictions_v4.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    universe = read_json(DATA / "universe.json", {})\n    lifecycle = read_json(DATA / "validation" / "lifecycle_v4.json", {})\n    validation_eligibility = lifecycle.get("eligibility") or {}\n',
    "governance preloaded prediction",
)
replace_once(
    "src/services/governance_service.py",
    "        universe=universe,\n        persist=False,\n",
    "        universe=universe,\n        validation_eligibility=validation_eligibility,\n        persist=False,\n",
    "governance maturity proof pass",
)
replace_once(
    "src/services/governance_service.py",
    '            "production_health_does_not_promote_model_maturity": True,\n            "fail_closed": True,\n',
    '            "production_health_does_not_promote_model_maturity": True,\n            "prediction_handoff_optional_and_file_fallback_preserved": True,\n            "predictions_received_preloaded": predictions_preloaded,\n            "validation_integrity_proof_passed_to_maturity": True,\n            "fail_closed": True,\n',
    "governance reuse guardrail",
)
replace_once(
    "src/services/governance_live_overlay.py",
    'def run() -> dict:\n    """Add live-score composition to the existing final governance boundary."""\n    out = governance_service.run()\n',
    'def run(*, predictions_snapshot: dict | None = None) -> dict:\n    """Add live-score composition to the existing final governance boundary."""\n    out = (\n        governance_service.run(predictions_snapshot=predictions_snapshot)\n        if predictions_snapshot is not None\n        else governance_service.run()\n    )\n',
    "governance overlay handoff",
)

# Hot path passes the exact prediction object to validation and governance.
replace_once(
    "src/services/hot_orchestrator.py",
    "def _validation_worker(conn) -> None:\n",
    "def _validation_worker(conn, predictions_snapshot: dict) -> None:\n",
    "hot validation signature",
)
replace_once(
    "src/services/hot_orchestrator.py",
    "        detail = validation_service.run()\n",
    "        detail = validation_service.run(predictions_snapshot=predictions_snapshot)\n",
    "hot validation handoff",
)
replace_once(
    "src/services/hot_orchestrator.py",
    '    prediction_service_price_mover.run()\n    service_ms["prediction"] = round((perf_counter() - t) * 1000.0, 2)\n    prediction_cache = prediction_model_cache.last_status()\n',
    '    prediction_bundle = prediction_service_price_mover.run(return_predictions=True)\n    service_ms["prediction"] = round((perf_counter() - t) * 1000.0, 2)\n    predictions_snapshot = (prediction_bundle or {}).get("predictions") or {}\n    if not predictions_snapshot.get("model_version") or not predictions_snapshot.get("players"):\n        raise RuntimeError("hot-path prediction handoff missing full prediction contract")\n    prediction_cache = prediction_model_cache.last_status()\n',
    "hot prediction bundle",
)
replace_once(
    "src/services/hot_orchestrator.py",
    '        args=(validation_send,),\n        name="v496-hot-validation",\n',
    '        args=(validation_send, predictions_snapshot),\n        name="v496-hot-validation",\n',
    "hot validation args",
)
replace_once(
    "src/services/hot_orchestrator.py",
    "    governance_detail = governance_live_overlay.run()\n",
    "    governance_detail = governance_live_overlay.run(predictions_snapshot=predictions_snapshot)\n",
    "hot governance handoff",
)
replace_once(
    "src/services/hot_orchestrator.py",
    '            "validation_fork_removes_interpreter_bootstrap_only": True,\n            "architecture_guard_runs_first": True,\n',
    '            "validation_fork_removes_interpreter_bootstrap_only": True,\n            "prediction_validation_handoff_explicit": True,\n            "prediction_governance_handoff_explicit": True,\n            "prediction_handoffs_copy_on_write_or_read_only": True,\n            "production_file_backed_service_fallbacks_preserved": True,\n            "same_cycle_integrity_proof_reused_by_governance": True,\n            "architecture_guard_runs_first": True,\n',
    "hot reuse guardrails",
)

Path("tests/test_v4_hot_governance_reuse.py").write_text(
    '''from __future__ import annotations

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
'''
)
