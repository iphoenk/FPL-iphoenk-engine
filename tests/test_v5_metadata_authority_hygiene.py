import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_implementation_status_matches_current_revalidation_state():
    status = _load("IMPLEMENTATION_STATUS.json")
    manifest = _load("config/v5_convergence_manifest.json")
    evidence = manifest["operational_acceptance_evidence"]
    production = manifest["production_promotion"]

    assert status["production_authority"]["main_sha"] == manifest["baselines"]["production_main_sha"]
    assert status["production_authority"]["runtime_schema_version"] == manifest["baselines"]["production_runtime_schema_version"]
    assert status["acceptance"]["fresh_postvalidated_real_shadow_cycles"] == production["validated_real_shadow_cycles"] == 0
    assert status["acceptance"]["required_postvalidated_real_shadow_cycles"] == production["required_real_shadow_cycles"] == 3
    assert status["acceptance"]["operational_candidate_eligible"] is False
    assert production["operational_acceptance_complete"] is False
    assert evidence["status"] == "SUPERSEDED_BY_CODE_CHANGE_PENDING_REVALIDATION"
    assert evidence["release_fingerprint"] is None
    assert evidence["remaining_validated_cycles"] == 3
    assert evidence["superseded_evidence"]["validated_real_shadow_cycles"] == 3
    assert evidence["superseded_evidence"]["release_fingerprint"].startswith("sha256:")
    assert status["acceptance"]["prediction_candidate_eligible"] is False
    assert production["prediction_acceptance_complete"] is False
    assert status["acceptance"]["production_candidate_eligible"] is False
    assert status["acceptance"]["production_promotion_allowed"] is False


def test_registry_catalog_does_not_describe_active_v5_domains_as_pending():
    catalog = _load("config/v5_registry_catalog.json")
    domains = catalog["domains"]

    assert domains["price_trajectory"]["status"] == "ACTIVE"
    assert "v5_price_trajectory_registry.json" in domains["price_trajectory"]["authority"]
    assert domains["projection_parameters"]["status"] == "ACTIVE"
    assert "config/intelligence/projection.json" in domains["projection_parameters"]["authority"]
    assert domains["xmins"]["status"] == "ACTIVE"
    assert "config/intelligence/xmins_v3.json" in domains["xmins"]["authority"]
    assert domains["xmins_v2_legacy_config"]["status"] == "DEPRECATED_NOT_AUTHORITY"
    assert domains["xmins_v2_legacy_config"]["authority"] == "none"


def test_decision_handler_authority_is_delegated_to_service_registry():
    catalog = _load("config/v5_registry_catalog.json")
    services = _load("config/v5_service_registry.json")
    row = catalog["domains"]["decision_service_handler"]

    assert row["authority"] == "config/v5_service_registry.json#services.decision.handler"
    handler = services["services"]["decision"]["handler"]
    assert isinstance(handler, str) and handler.endswith(":handle")
