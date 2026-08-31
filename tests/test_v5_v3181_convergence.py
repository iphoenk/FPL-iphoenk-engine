import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SOURCE_AUTHORITY = "runtime-data:data/runtime_manifest.json#source_commit"
PRODUCTION_SOURCE_ENV = "V5_PRODUCTION_SOURCE_SHA"


def load(path):
    return json.loads((ROOT / path).read_text())


def test_v5_converges_to_exact_v320_production_closeout():
    manifest = load("config/v5_convergence_manifest.json")
    acceptance = load("config/v5_acceptance_registry.json")
    engine = load("config/engine.json")
    sources = load("config/sources/registry.json")

    baselines = manifest["baselines"]
    convergence = acceptance["convergence"]
    assert baselines["production_truth"] == "v3.20.0"
    assert baselines["production_source_authority"] == PRODUCTION_SOURCE_AUTHORITY
    assert baselines["production_source_environment"] == PRODUCTION_SOURCE_ENV
    assert convergence["production_source_authority"] == PRODUCTION_SOURCE_AUTHORITY
    assert convergence["production_source_environment"] == PRODUCTION_SOURCE_ENV
    assert "production_main_sha" not in baselines
    assert "production_code_commit" not in baselines
    assert "production_main_sha" not in convergence
    assert "production_code_commit" not in convergence
    assert baselines["production_schema_version"] == 48 and engine["schema_version"] == 48
    assert convergence["production_baseline"] == "v3.20.0"
    assert sources["policy"]["source_network_locations_are_registry_owned"] is True
    one = next(x for x in sources["sources"] if x["id"] == "onefpl")
    under = next(x for x in sources["sources"] if x["id"] == "understat")
    assert one["enabled"] is False and one["delegated_to"] == "REPORT_TIME_SOURCE_REGISTRY_V1"
    assert under["enabled"] is False
    assert manifest["production_promotion"]["allowed"] is False
