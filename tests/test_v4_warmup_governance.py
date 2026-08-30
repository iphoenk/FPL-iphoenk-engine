from __future__ import annotations

import json

from src.engines.v4_maturity_reconciler import _rotation_evidence
from src.engines.v4_warmup_governance import MINIMUM_RECONCILED_ROWS, _calibration_evidence


def _rows(count: int) -> list[dict]:
    rows = []
    for idx in range(count):
        actual = float(idx) / 10.0
        inside = idx % 5 != 0
        rows.append({
            "element": idx + 1,
            "predicted": actual,
            "actual": actual,
            "lower80": actual - 1.0 if inside else actual + 1.0,
            "upper80": actual + 1.0 if inside else actual + 2.0,
        })
    return rows


def _sample(rows: list[dict], gw: int = 1) -> dict:
    return {
        "gw": gw,
        "model_version": "test-model",
        "report": {
            "rows": rows,
            "metrics": {
                "status": "PASS",
                "n": len(rows),
                "leakage_rejected": 0,
                "minutes": {
                    "start_n": max(0, len(rows) - 10),
                    "start_missing": min(10, len(rows)),
                },
            },
        },
    }


def test_warmup_file_presence_alone_never_promotes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "gw01.json"
    path.write_text(json.dumps(_sample([])))
    monkeypatch.setattr(
        "src.engines.v4_warmup_governance.store.reconciled_integrity",
        lambda sample, model_version=None: (True, None),
    )
    promote, detail = _calibration_evidence(tmp_path, model_version="test-model")
    assert promote is False
    assert detail["maturity_state"] == "WARMUP"
    assert detail["reconciled_rows"] == 0


def test_warmup_requires_existing_calibration_gate_threshold(tmp_path, monkeypatch) -> None:
    path = tmp_path / "gw01.json"
    path.write_text(json.dumps(_sample(_rows(MINIMUM_RECONCILED_ROWS - 1))))
    monkeypatch.setattr(
        "src.engines.v4_warmup_governance.store.reconciled_integrity",
        lambda sample, model_version=None: (True, None),
    )
    promote, detail = _calibration_evidence(tmp_path, model_version="test-model")
    assert promote is False
    assert detail["promotion_gate"]["reason"] == "insufficient_sample"
    assert detail["reconciled_rows"] == MINIMUM_RECONCILED_ROWS - 1


def test_warmup_promotes_deterministically_only_after_real_gate_passes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "gw01.json"
    path.write_text(json.dumps(_sample(_rows(MINIMUM_RECONCILED_ROWS))))
    monkeypatch.setattr(
        "src.engines.v4_warmup_governance.store.reconciled_integrity",
        lambda sample, model_version=None: (True, None),
    )
    promote, detail = _calibration_evidence(tmp_path, model_version="test-model")
    assert promote is True
    assert detail["maturity_state"] == "ACTIVE"
    assert detail["promotion_gate"] == {"promote": True, "reason": "passed"}
    assert detail["aggregate_metrics"]["interval80_coverage"] == 0.8
    assert detail["missing_starts_excluded_from_start_calibration"] is True
    assert detail["retrospective_prediction_reconstruction_forbidden"] is True


def test_corrupt_or_wrong_model_reconciliation_cannot_mature_capability(tmp_path, monkeypatch) -> None:
    path = tmp_path / "gw01.json"
    path.write_text(json.dumps(_sample(_rows(MINIMUM_RECONCILED_ROWS))))
    monkeypatch.setattr(
        "src.engines.v4_warmup_governance.store.reconciled_integrity",
        lambda sample, model_version=None: (False, "model_version_mismatch"),
    )
    promote, detail = _calibration_evidence(tmp_path, model_version="production-model")
    assert promote is False
    assert detail["maturity_state"] == "WARMUP"
    assert detail["rejected_reconciliations"] == [{"file": "gw01.json", "reason": "model_version_mismatch"}]


def test_rotation_maturity_does_not_require_any_unadjusted_player() -> None:
    predictions = {
        "players": [
            {
                "priors": {
                    "competition_pressure": 0.3,
                    "competition_source": "inferred_tactical_role_peer_group",
                    "squad_depth_pressure": 0.2,
                    "competition_factor": 0.82,
                    "competition_adjustment_applied": True,
                }
            },
            {
                "priors": {
                    "competition_pressure": 0.1,
                    "competition_source": "inferred_tactical_role_peer_group",
                    "squad_depth_pressure": 0.1,
                    "competition_factor": 0.93,
                    "competition_adjustment_applied": True,
                }
            },
        ]
    }
    ok, detail = _rotation_evidence(predictions)
    assert ok is True
    assert detail["distinct_competition_factors"] == 2
    assert detail["canonical_per_player_source_rows"] == 2
