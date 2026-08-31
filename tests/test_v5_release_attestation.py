import json
from pathlib import Path

from src.v5.release_attestation import release_attestation

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text())


def test_release_attestation_binds_current_candidate(monkeypatch):
    deployed = "a" * 40
    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", deployed)
    release_attestation.cache_clear()
    row = release_attestation()
    manifest = load("config/v5_convergence_manifest.json")

    assert row["contract"] == "V5_RELEASE_ATTESTATION_V1"
    assert row["v5_version"] == "5.0.0-beta.4"
    assert row["production_baseline_version"] == "v3.20.0"
    assert row["production_main_sha"] == deployed
    assert manifest["baselines"]["production_source_authority"] == "runtime-data:data/runtime_manifest.json#source_commit"
    assert "production_main_sha" not in manifest["baselines"]
    assert str(row["runtime_release_fingerprint"]).startswith("sha256:")
    assert str(row["attestation"]).startswith("sha256:")
    assert row["promotion_authority"] is False
