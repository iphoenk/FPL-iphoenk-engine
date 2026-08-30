import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOYED_SHA = "80fe400888f7a4979f4537971cbc8eef6470dbe6"
STALE_DEPLOYED_SHAS = {
    "794d45d37782b3b47617d80384589a7a0cc55730",
    "5175f9bc68354100a8bc3a36a3b97e853e90b73d",
    "9f483a2eb2cd346fa014dfdb8a2b8edb7456906d",
    "892dd783b2fa0199cecf74e5a6548bb0619816dd",
    "9a76a6231bdd747a247eabc8867a2312a188317a",
}
OWNED_METADATA = (
    "config/v5_convergence_manifest.json",
    "config/v5_acceptance_registry.json",
    "config/v5_capability_parity_registry.json",
    "IMPLEMENTATION_STATUS.json",
)


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_implementation_status_matches_current_revalidation_state():
    status = _load("IMPLEMENTATION_STATUS.json")
    manifest = _load("config/v5_convergence_manifest.json")
    persistence = _load("config/v5_persistence_registry.json")
    evidence = manifest["operational_acceptance_evidence"]
    production = manifest["production_promotion"]

    assert status["production_authority"]["main_sha"] == manifest["baselines"]["production_main_sha"]
    assert status["production_authority"]["runtime_schema_version"] == manifest["baselines"]["production_runtime_schema_version"]
    assert status["acceptance"]["fresh_postvalidated_real_shadow_cycles"] == production["validated_real_shadow_cycles"] == 0
    assert status["acceptance"]["required_postvalidated_real_shadow_cycles"] == production["required_real_shadow_cycles"] == 3
    assert status["acceptance"]["operational_candidate_eligible"] is False
    assert production["operational_acceptance_complete"] is False
    assert evidence["status"] == "SUPERSEDED_BY_PRODUCTION_REANCHOR_PENDING_REVALIDATION"
    assert evidence["release_fingerprint"] is None
    assert evidence["remaining_validated_cycles"] == 3
    assert evidence["superseded_evidence"]["validated_real_shadow_cycles"] == 3
    assert evidence["superseded_evidence"]["release_fingerprint"].startswith("sha256:")
    assert status["acceptance"]["previous_operational_acceptance"]["postvalidated_real_shadow_cycles"] == 3
    assert status["acceptance"]["previous_operational_acceptance"]["release_fingerprint"] == evidence["superseded_evidence"]["release_fingerprint"]
    assert status["acceptance"]["prediction_candidate_eligible"] is False
    assert production["prediction_acceptance_complete"] is False
    assert status["acceptance"]["production_candidate_eligible"] is False
    assert status["acceptance"]["production_promotion_allowed"] is False

    storage = status["evidence_storage"]
    retention = persistence["write_policy"]["history_retention"]
    assert storage["rolling_history_canonical"] is False
    assert storage["rolling_history_max_age_days"] == retention["max_age_days"]
    assert storage["rolling_history_max_records"] == retention["max_records"]
    assert storage["rolling_history_max_bytes"] == retention["max_bytes"]
    assert storage["actions_raw_artifact_retention_days"] == persistence["evidence_storage"]["raw_actions_artifact_retention_days"]


def test_owned_metadata_is_reanchored_to_the_one_deployed_runtime_sha():
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    parity = _load("config/v5_capability_parity_registry.json")
    status = _load("IMPLEMENTATION_STATUS.json")

    assert manifest["baselines"]["production_main_sha"] == DEPLOYED_SHA
    assert manifest["baselines"]["production_code_commit"] == DEPLOYED_SHA
    assert acceptance["convergence"]["production_main_sha"] == DEPLOYED_SHA
    assert acceptance["convergence"]["production_code_commit"] == DEPLOYED_SHA
    assert parity["authorities"]["current_production_code_commit"] == DEPLOYED_SHA
    assert parity["authorities"]["current_production_runtime"] == f"deployed@{DEPLOYED_SHA}"
    assert parity["current_production_reanchor"]["production_main_sha"] == DEPLOYED_SHA
    assert parity["current_production_reanchor"]["production_code_commit"] == DEPLOYED_SHA
    assert status["production_authority"]["main_sha"] == DEPLOYED_SHA

    assert manifest["baselines"]["production_truth"] == "v3.20.0"
    assert acceptance["convergence"]["production_baseline"] == "v3.20.0"
    assert parity["authorities"]["football_truth_baseline"] == "v3.20.0"
    assert manifest["advanced_v5"]["v3_atomic_runtime_publication_reconciled_as_runtime_governance_hardening"] is True
    assert acceptance["convergence"]["v3_atomic_runtime_publication_reconciled_as_runtime_governance_hardening"] is True
    assert parity["current_production_reanchor"]["v3_topology"]["atomic_runtime_publication_runtime_governance_only"] is True
    assert parity["governance"]["v3_atomic_runtime_publication_is_runtime_governance_not_v5_prediction_or_decision_authority"] is True

    for path in OWNED_METADATA:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert not (STALE_DEPLOYED_SHAS & set(text.split())), path
        for stale_sha in STALE_DEPLOYED_SHAS:
            assert stale_sha not in text, f"stale deployed SHA remains in {path}: {stale_sha}"


def test_predeadline_governance_is_public_official_plus_scoped_capture_only():
    phase = _load("config/v5_phase_authority_registry.json")
    squad = _load("config/v5_squad_registry.json")
    source = _load("config/v5_source_authority_registry.json")
    shadow = _load("config/v5_shadow_parity_registry.json")
    trigger = _load("config/v5_shadow_trigger.json")

    governance = phase["pre_deadline_governance"]
    assert governance["primary_authority_model"] == "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE"
    assert governance["official_public_submitted_is_default_planning_baseline"] is True
    assert governance["user_capture_may_override_only_for_explicit_target_gw"] is True
    assert governance["user_capture_requires_active_wc_fh_or_planning_override"] is True
    assert governance["stale_or_unscoped_user_capture_must_not_mask_official_submitted_team"] is True
    assert governance["authenticated_official_is_optional_private_enrichment"] is True
    assert governance["authenticated_official_must_not_be_squad_lineup_or_captaincy_authority"] is True

    for domain in ("squad", "lineup", "captaincy"):
        assert "official_authenticated" not in phase["phases"]["PRE_DEADLINE"][domain]
    assert squad["pre_deadline"]["default_authority"] == "official_public"
    assert squad["pre_deadline"]["conditional_override_authority"] == "user_lock"
    assert squad["pre_deadline"]["override_requires_exact_target_gw"] is True
    assert squad["pre_deadline"]["override_requires_active_wc_fh_or_planning_override"] is True
    assert squad["pre_deadline"]["authenticated_official_is_squad_authority"] is False
    assert source["domains"]["pre_deadline_locked_squad"] == ["official_public", "user_lock"]

    proof = shadow["predeadline_authority_validation"]
    assert proof["primary_authority_model"] == "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE"
    assert set(proof["allowed_decision_squad_authorities"]) == {"official_public", "user_lock"}
    assert proof["authenticated_official_must_not_select_squad_lineup_or_captaincy"] is True
    assert trigger["require_authenticated_official_predeadline"] is False
    assert trigger["require_official_submitted_predeadline"] is False
    assert trigger["require_public_official_plus_user_capture_predeadline"] is True


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
