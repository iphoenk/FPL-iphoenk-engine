from __future__ import annotations

import json

import pytest

from src.runtime_v3 import artifact_contracts
from src.runtime_v3.artifact_contracts import validate_artifact


CRITICAL = {
    "team.json",
    "chips.json",
    "projections.json",
    "lineup_decision.json",
    "package_decision.json",
    "framework_health.json",
    "dss_watchlist.json",
    "decision_brief.json",
    "user_report.json",
}


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_critical_decision_and_serving_artifacts_have_explicit_contracts():
    registry = artifact_contracts.load_registry()
    assert registry["policy"]["critical_decision_and_serving_artifacts_are_structurally_validated"] is True
    assert registry["policy"]["unknown_json_contract"] == "PARSE_ONLY"
    assert CRITICAL.issubset(set(registry["contracts"]))


def test_package_decision_rejects_failed_gate0(tmp_path):
    path = tmp_path / "package_decision.json"
    payload = {
        "generated_at": "2026-09-01T00:00:00Z",
        "model": "package_governance_v1",
        "ruleset_id": "FPL_2026_27",
        "planning_gw": 3,
        "selected_package": {"id": "HOLD"},
        "selected_package_id": "HOLD",
        "manual_authority_override": True,
        "current_squad_legal": True,
        "gate0_revalidated": False,
        "governance": {},
    }
    _write(path, payload)
    with pytest.raises(RuntimeError, match="gate0_revalidated"):
        validate_artifact(path, path.name)


def test_package_decision_accepts_governed_gate0_pass(tmp_path):
    path = tmp_path / "package_decision.json"
    payload = {
        "generated_at": "2026-09-01T00:00:00Z",
        "model": "package_governance_v1",
        "ruleset_id": "FPL_2026_27",
        "planning_gw": 3,
        "selected_package": {"id": "HOLD"},
        "selected_package_id": "HOLD",
        "manual_authority_override": True,
        "current_squad_legal": True,
        "gate0_revalidated": True,
        "governance": {},
    }
    _write(path, payload)
    assert validate_artifact(path, path.name)["validation"] == "CONTRACT_VALID"


def test_decision_brief_rejects_structurally_incomplete_payload(tmp_path):
    path = tmp_path / "decision_brief.json"
    payload = {
        "decision": {},
        "generated_at": "2026-09-01T00:00:00Z",
        "planning_gw": 3,
        "serving_contract": {},
        "gameweek_context": {},
        "finance": {},
    }
    _write(path, payload)
    with pytest.raises(RuntimeError, match="owned_15"):
        validate_artifact(path, path.name)


def test_user_report_rejects_missing_owned_squad(tmp_path):
    path = tmp_path / "user_report.json"
    _write(path, {"decision": {}})
    with pytest.raises(RuntimeError, match="owned_squad"):
        validate_artifact(path, path.name)
