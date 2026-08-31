import pytest

from src.v5.production_baseline import production_source_contract, production_source_sha


def test_production_source_contract_is_runtime_manifest_authoritative():
    row = production_source_contract()
    assert row == {
        "authority": "runtime-data:data/runtime_manifest.json#source_commit",
        "environment": "V5_PRODUCTION_SOURCE_SHA",
    }


def test_production_source_sha_requires_exact_40_hex(monkeypatch):
    monkeypatch.delenv("V5_PRODUCTION_SOURCE_SHA", raising=False)
    with pytest.raises(RuntimeError):
        production_source_sha()
    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", "abc123")
    with pytest.raises(RuntimeError):
        production_source_sha()
    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", "C" * 40)
    assert production_source_sha() == "c" * 40
