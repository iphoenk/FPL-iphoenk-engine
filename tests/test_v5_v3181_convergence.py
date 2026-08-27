import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(path):return json.loads((ROOT/path).read_text())
def test_v5_converges_to_exact_v320_production_closeout():
    manifest=load("config/v5_convergence_manifest.json"); acceptance=load("config/v5_acceptance_registry.json"); engine=load("config/engine.json"); sources=load("config/sources/registry.json")
    assert manifest["baselines"]["production_truth"]=="v3.20.0"
    assert manifest["baselines"]["production_main_sha"]=="15e75599045f901958753c2bcb275fceacc94d7c"
    assert manifest["baselines"]["production_schema_version"]==48 and engine["schema_version"]==48
    assert acceptance["convergence"]["production_baseline"]=="v3.20.0"
    assert acceptance["convergence"]["production_main_sha"]==manifest["baselines"]["production_main_sha"]
    assert sources["policy"]["source_network_locations_are_registry_owned"] is True
    one=next(x for x in sources["sources"] if x["id"]=="onefpl"); under=next(x for x in sources["sources"] if x["id"]=="understat")
    assert one["enabled"] is False and one["delegated_to"]=="REPORT_TIME_SOURCE_REGISTRY_V1"
    assert under["enabled"] is False
    assert manifest["production_promotion"]["allowed"] is False
