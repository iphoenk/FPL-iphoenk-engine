import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def test_v5_converges_to_exact_accepted_production_closeout():
    manifest = load("config/v5_convergence_manifest.json")
    acceptance = load("config/v5_acceptance_registry.json")
    engine = load("config/engine.json")
    sources = load("config/sources/registry.json")
    parity = load("config/v5_capability_parity_registry.json")

    baselines = manifest["baselines"]
    convergence = acceptance["convergence"]

    assert baselines["production_truth"] == convergence["production_baseline"]
    assert baselines["production_main_sha"] == convergence["production_main_sha"]
    assert baselines["production_schema_version"] == convergence["production_schema_version"]
    assert engine["schema_version"] == convergence["production_schema_version"]
    assert baselines["production_truth"] == "v3.22.0"
    assert baselines["production_main_sha"] == "6639f899669daa6ae9f991009900437413057e86"
    assert baselines["production_schema_version"] == 49

    assert parity["authorities"]["production"] == baselines["production_truth"]
    assert parity["authorities"]["production_main_sha"] == baselines["production_main_sha"]
    assert parity["authorities"]["candidate"] == manifest["version"]
    v322 = {row["id"]: row for row in parity["v3_22_runtime_capability_map"]}
    assert v322["REC-15_REC-30_runtime_slo_resource_guard"]["v5_status"] == "ADOPTED"
    assert v322["REC-20_normalized_player_feature_plumbing"]["v5_status"] == "ADOPTED_AND_EXTENDED"
    assert v322["REC-29_rolling_runtime_publication"]["v5_status"] == "SUPERSEDED_UNTIL_CUTOVER"
    assert parity["governance"]["v3_22_runtime_optimization_must_not_reduce_decision_quality"] is True

    assert sources["schema_version"] == convergence["source_registry_schema_required"] == 4
    assert sources["policy"]["source_network_locations_are_registry_owned"] is True
    assert sources["policy"]["source_ingestion_timeouts_are_registry_owned"] is True

    rows = {row["id"]: row for row in sources["sources"]}
    one = rows["onefpl"]
    under = rows["understat"]
    weather = rows["open_meteo"]

    assert one["enabled"] is False
    assert one["delegated_to"] == "REPORT_TIME_SOURCE_REGISTRY_V1"
    assert under["enabled"] is False
    assert weather["enabled"] is True
    assert weather["policy_ref"] == convergence["weather_policy_ref_required"]
    assert convergence["weather_may_directly_change_xpts"] is False
    assert convergence["weather_may_directly_change_captaincy"] is False
    assert convergence["weather_may_directly_change_starting_xi"] is False
    assert convergence["weather_may_directly_change_transfer_decision"] is False
    assert convergence["weather_may_directly_change_watchlist_membership"] is False

    assert manifest["acceptance"]["no_regression_vs_v3_22_0_runtime_performance_contract"] is True
    assert manifest["acceptance"]["no_regression_vs_v3_22_0_player_feature_plumbing"] is True
    assert manifest["acceptance"]["no_regression_vs_v3_22_0_runtime_publish_integrity"] is True
    assert manifest["production_promotion"]["allowed"] is False
