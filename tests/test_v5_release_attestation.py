import json
from pathlib import Path

from src.v5 import V5_VERSION
from src.v5.release_attestation import release_attestation

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def test_release_attestation_binds_current_candidate():
    manifest = load("config/v5_convergence_manifest.json")
    row = release_attestation()

    assert row["contract"] == "V5_RELEASE_ATTESTATION_V1"
    assert row["v5_version"] == V5_VERSION == manifest["version"]
    assert row["production_baseline_version"] == manifest["baselines"]["production_truth"]
    assert row["production_main_sha"] == manifest["baselines"]["production_main_sha"]
    assert str(row["runtime_release_fingerprint"]).startswith("sha256:")
    assert str(row["attestation"]).startswith("sha256:")
    assert row["promotion_authority"] is False
