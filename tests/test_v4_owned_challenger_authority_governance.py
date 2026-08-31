from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v4_challenger_serving_composition import _assert_complete

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _complete_payload(**overrides):
    payload = {
        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",
        "status": "READY",
        "decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",
        "overall_decision": "REVIEW",
        "official_fact_completeness": {
            "owned": {"actual": 15, "complete": True},
            "watchlist": {"actual": 20, "complete": True},
        },
        "owned_screening": [{"element": index + 1} for index in range(15)],
    }
    payload.update(overrides)
    return payload


def test_serving_rejects_second_decision_authority():
    _assert_complete(_complete_payload(), canonical_action="REVIEW")
    with pytest.raises(RuntimeError, match="canonical action mismatch"):
        _assert_complete(_complete_payload(overall_decision="REVIEW_NOW"), canonical_action="REVIEW")
    with pytest.raises(RuntimeError, match="canonical decision authority"):
        _assert_complete(_complete_payload(decision_authority="OWNED_CHALLENGER"), canonical_action="REVIEW")


def test_owned_challenger_policy_is_release_and_attestation_governed():
    policy = _load("config/intelligence/owned_challenger_decision_v4.json")
    manifest = _load("config/release_manifest.json")
    services = _load("config/service_registry.json")
    contracts = _load("config/service_contract_registry.json")
    ownership = _load("config/architecture_ownership_registry.json")
    assert manifest["registries"]["owned_challenger_policy"] == policy["registry"]
    optimization = next(row for row in services["services"] if row["id"] == "optimization")
    assert "owned_challenger_decision" in optimization["produces"]
    contract = contracts["contracts"]["owned_challenger_decision"]
    assert contract["path"] == "data/owned_challenger_decision_v4.json"
    assert contract["equals"]["decision_authority"] == "CANONICAL_DECISION_ARBITRATION_V1"
    responsibility = next(row for row in ownership["responsibilities"] if row["id"] == "OWNED_CHALLENGER_EVIDENCE")
    assert responsibility["decision_authority"] == "CANONICAL_DECISION_ARBITRATION_V1"
    architecture_source = (ROOT / "src/services/architecture_guard_service.py").read_text(encoding="utf-8")
    assert 'CONFIG / "intelligence/owned_challenger_decision_v4.json"' in architecture_source
    assert 'checks["owned_challenger_single_decision_authority"]' in architecture_source
