from __future__ import annotations

import json

import pytest

from src.runtime_v3.artifact_contracts import validate_artifact


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_payload():
    return {
        "generated_at": "2026-08-30T00:00:00Z",
        "owned_element_ids": [1],
        "detail_element_ids": [1],
        "element_summaries": {"1": {"fixtures": [], "history": [], "history_past": []}},
    }


def test_pre_enrichment_official_detail_is_not_reusable(tmp_path):
    path = tmp_path / "official_detail.json"
    _write(path, _base_payload())
    with pytest.raises(Exception):
        validate_artifact(path, "official_detail.json")


def test_enriched_official_detail_satisfies_reuse_contract(tmp_path):
    path = tmp_path / "official_detail.json"
    payload = _base_payload()
    payload["player_detail_enrichment"] = {
        "contract": "OFFICIAL_PLAYER_DETAIL_ENRICHMENT_V1",
        "evidence_state": "PARTIAL",
        "cached_players": 1,
        "universe_players": 2,
        "governance": {"decision_blocking": False},
    }
    _write(path, payload)
    result = validate_artifact(path, "official_detail.json")
    assert result["artifact"] == "official_detail.json"
    assert result["validation"] == "CONTRACT_VALID"
    assert result["contract_registry"] == "RUNTIME_ARTIFACT_CONTRACTS_V2"
