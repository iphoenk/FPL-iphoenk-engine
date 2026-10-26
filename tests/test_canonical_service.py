from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import canonical_service


def _result() -> dict:
    return {
        "serving_mode": "VALIDATED_REGenerated_FROM_FRESH_CANONICAL_STATE",
        "planning_gw": 9,
        "owned_15": list(range(1, 16)),
        "lineup": {
            "formation": "3-4-3",
            "starting_xi": list(range(1, 12)),
            "bench": {"gk": 12, "order": [13, 14, 15]},
            "captain": {"element": 1},
            "vice_captain": {"element": 2},
            "lineup_score": {"risk_adjustment": -0.2},
            "ruleset_id": "FPL_V12",
        },
        "package": {
            "selected_package_id": "HOLD",
            "selected_package": {"route_id": "HOLD"},
            "package_frontier": [{"route_id": "HOLD", "classification": "HOLD"}],
            "model_evidence_binding": {
                "input_fingerprint": "input-fp",
                "canonical_v12_revision": "revision-fp",
            },
            "monte_carlo": {"execution_state": "NOT_RUN"},
            "decision": {"football_action": "HOLD"},
        },
        "authority": {"governed_decision_recomputed": True, "network_fetches": 0},
        "freshness": {"status": "FRESH"},
    }


def test_contract_maps_canonical_output(monkeypatch):
    monkeypatch.setattr(canonical_service, "run_unified_fastpath", _result)
    response = TestClient(canonical_service.app).get(
        "/api/decision?entry_id=3462711&horizon=3"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == canonical_service.CONTRACT
    assert body["status"] == "ready"
    assert body["entry_id"] == 3462711
    assert body["horizon"] == 3
    assert body["decision"]["formation"] == "3-4-3"
    assert body["provenance"]["input_fingerprint"] == "input-fp"


def test_identity_and_horizon_are_fail_closed(monkeypatch):
    monkeypatch.setattr(canonical_service, "run_unified_fastpath", _result)
    client = TestClient(canonical_service.app)
    assert client.get("/api/decision?entry_id=96581&horizon=1").status_code == 403
    assert client.get("/api/decision?entry_id=3462711&horizon=2").status_code == 400


def test_runtime_failure_does_not_leak_details(monkeypatch):
    def fail():
        raise RuntimeError("/private/data/secret.json and model internals")

    monkeypatch.setattr(canonical_service, "run_unified_fastpath", fail)
    response = TestClient(canonical_service.app).get("/api/decision?entry_id=3462711")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "secret" not in response.text


def test_mismatched_team_artifact_is_rejected(monkeypatch, tmp_path):
    team = tmp_path / "team.json"
    team.write_text(json.dumps({"entry_id": 96581}), encoding="utf-8")
    monkeypatch.setenv("FPL_DATA_DIR", str(tmp_path))
    response = TestClient(canonical_service.app).get("/api/decision?entry_id=3462711")
    assert response.status_code == 503
