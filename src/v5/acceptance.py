from __future__ import annotations

import json

from src.rules import GOAL_POINTS, RULESET_ID, RULESET_SEASON, ruleset_metadata
from src.v5 import V5_VERSION
from src.v5.config_cache import ROOT, load_json_config
from src.v5.contracts import AcceptanceCheck, AcceptanceReport, Plane
from src.v5.module_registry import module_specs
from src.v5.release_attestation import release_attestation
from src.v5.service_registry import registry as service_registry, service_specs, validate_registry

ACCEPTANCE_CONFIG = "config/v5_acceptance_registry.json"
MANIFEST_CONFIG = "config/v5_convergence_manifest.json"
ARCHITECTURE_CONFIG = "config/v5_architecture_principles.json"
ORCHESTRATOR_CONFIG = "config/v5_orchestrator_registry.json"
GATE0_CONFIG = "config/gate0_registry.json"
SOURCE_CONFIG = "config/sources/registry.json"


def _registered_modules_ok(names: list[str], active_statuses: set[str]) -> bool:
    modules = {x.name: x for x in module_specs()}
    return all(
        (module := modules.get(name)) is not None
        and module.status in active_statuses
        and bool(module.entrypoint)
        and bool(module.config)
        and not module.entrypoint.startswith("planned")
        and not module.config.startswith("planned")
        and (ROOT / module.config).exists()
        for name in names
    )


def _source_rows(registry: dict) -> dict[str, dict]:
    return {str(row.get("id")): row for row in registry.get("sources") or [] if isinstance(row, dict) and row.get("id")}


def run_bootstrap_acceptance() -> AcceptanceReport:
    acceptance = load_json_config(ACCEPTANCE_CONFIG)
    manifest = load_json_config(MANIFEST_CONFIG)
    architecture = load_json_config(ARCHITECTURE_CONFIG)
    orchestrator_cfg = load_json_config(ORCHESTRATOR_CONFIG)
    gate0_cfg = load_json_config(GATE0_CONFIG)
    source_registry_cfg = load_json_config(SOURCE_CONFIG)
    performance_cfg = load_json_config("config/v5_performance_budgets.json")
    metadata = ruleset_metadata()
    modules = module_specs()
    module_policy = acceptance["module_policy"]
    service_policy = acceptance["service_policy"]
    convergence = acceptance.get("convergence") or {}
    active = {str(x) for x in module_policy["active_statuses"]}
    services = service_specs()
    service_ids = {x.service_id for x in services}
    required_services = {str(x) for x in service_policy["required_services"]}
    service_errors = validate_registry()
    service_cfg = service_registry()
    modular = architecture.get("principles", {}).get("modular_authority", {})
    micro = architecture.get("principles", {}).get("microservices", {})
    gate0_contract = gate0_cfg.get("contract") or {}
    gate0_checks = gate0_cfg.get("checks") or []
    parallel_groups = orchestrator_cfg.get("parallel_groups") or {}
    routes = orchestrator_cfg.get("routing") or {}
    parallel_required = {str(x) for x in convergence.get("analysis_parallel_routes_required") or []}
    analysis_group = {str(x) for x in parallel_groups.get("analysis_preflight") or []}
    prediction_source = (ROOT / "src/v5/services/prediction.py").read_text()
    decision_source = (ROOT / "src/v5/services/decision.py").read_text()
    watchlist_source = (ROOT / "src/v5/services/watchlist.py").read_text()
    reporting_source = (ROOT / "src/v5/reporting.py").read_text()
    public_api_source = (ROOT / "src/v5/public_api.py").read_text()
    price_service_source = (ROOT / "src/v5/services/price.py").read_text()
    tactical_consumption_source = (ROOT / "src/v5/decision/tactical_consumption.py").read_text()
    baseline = str(convergence.get("production_baseline") or "")
    baseline_sha = str(convergence.get("production_main_sha") or "")
    manifest_baselines = manifest.get("baselines") or {}
    source_policy = source_registry_cfg.get("policy") or {}
    source_rows = _source_rows(source_registry_cfg)
    onefpl = source_rows.get("onefpl") or {}
    understat = source_rows.get("understat") or {}
    attestation = release_attestation()
    parity_cfg = load_json_config("config/v5_capability_parity_registry.json")
    parity_domains = {str(x) for x in parity_cfg.get("required_domains") or []}
    budgets = performance_cfg.get("budgets") or {}
    comparator_domains = {"owned_challenger_comparator", "observed_tactical_context", "tactical_decision_consumption", "transfer_momentum_truthful_evidence", "interactive_subsecond_serving"}
    checks = (
        AcceptanceCheck("v5_manifest", manifest.get("version") == V5_VERSION, Plane.GOVERNANCE, "package version matches convergence manifest"),
        AcceptanceCheck("production_baseline_declared", manifest_baselines.get("production_truth") == baseline and manifest_baselines.get("production_main_sha") == baseline_sha and bool(baseline_sha), Plane.TRUTH, "football-truth baseline and current production runtime SHA are registry-driven and consistent"),
        AcceptanceCheck("production_schema_48", int(manifest_baselines.get("production_schema_version") or 0) == 48, Plane.TRUTH, "settled V3.20 football-truth schema 48 remains explicit"),
        AcceptanceCheck("prediction_baseline_declared", baseline in str(manifest_baselines.get("prediction_intelligence") or ""), Plane.INTELLIGENCE, "prediction convergence references accepted football-truth baseline"),
        AcceptanceCheck("rules_registry_active", RULESET_ID == "FPL_2026_27" and RULESET_SEASON == "2026/27", Plane.TRUTH, "verified season rules remain single authority"),
        AcceptanceCheck("goalkeeper_goal_rule", GOAL_POINTS.get(1) == 10, Plane.TRUTH, "goalkeeper goal scoring remains 10"),
        AcceptanceCheck("rules_fingerprint_present", bool(metadata.get("fingerprint_sha256")), Plane.GOVERNANCE, "ruleset exposes auditable fingerprint"),
        AcceptanceCheck("prediction_consumes_truth_contract", 'payload.get("rules")' in prediction_source and "from src.rules import" not in prediction_source, Plane.INTELLIGENCE, "prediction consumes truth rules contract"),
        AcceptanceCheck("native_decision", "build_packages" in decision_source and "optimize_lineup" in decision_source and "build_trace" in decision_source and "build_watchlist" not in decision_source, Plane.DECISION, "decision owns package/lineup/trace without importing watchlist authority"),
        AcceptanceCheck("native_watchlist_service", convergence.get("full_dss_watchlist_required") is True and "build_watchlist" in watchlist_source and "FULL_DSS" not in decision_source, Plane.DECISION, "full DSS external screening is an independent service"),
        AcceptanceCheck("native_owned_challenger_comparator", convergence.get("owned_challenger_comparator_required") is True and (ROOT / "src/v5/evaluation/owned_challenger_comparator.py").exists(), Plane.INTELLIGENCE, "generic OWNED-vs-Challenger comparator is native V5 Evaluation authority"),
        AcceptanceCheck("tactical_close_call_consumption", convergence.get("tactical_decision_consumption_required") is True and "tactical_direct_xpts_mutation" in tactical_consumption_source and "close_group_sort" in tactical_consumption_source, Plane.DECISION, "tactical context is consumed only as close-call evidence without xPts mutation"),
        AcceptanceCheck("truthful_transfer_momentum", convergence.get("transfer_momentum_requires_official_counts_and_price_linkage") is True and 'CAPABILITIES = ["price_intelligence"]' in price_service_source, Plane.INTELLIGENCE, "DSS-42 is not advertised statically; capability requires runtime Official-count and current-price evidence"),
        AcceptanceCheck("official_parallel_fanout", convergence.get("official_independent_endpoint_fanout_required") is True and "ThreadPoolExecutor" in public_api_source and "def fetch_many" in public_api_source and "deduplicating paths" in public_api_source, Plane.TRUTH, "independent Official endpoint fan-out is parallel under one ingestion authority"),
        AcceptanceCheck("interactive_subsecond_budget", convergence.get("interactive_subsecond_serving_required") is True and float(budgets.get("interactive_target_seconds") or 99) <= 1.0 and float(budgets.get("interactive_decision_regeneration_ms") or 99999) < 1000 and float(budgets.get("owned_challenger_comparator_ms") or 99999) <= 50, Plane.GOVERNANCE, "interactive and comparator performance guardrails are explicit and promotion-blocking"),
        AcceptanceCheck("reconciled_capability_parity", comparator_domains.issubset(parity_domains) and parity_cfg.get("governance", {}).get("runtime_hardening_is_reconciled_by_capability_not_code_merge") is True, Plane.GOVERNANCE, "current production runtime hardening is reconciled by capability without importing V3 business ownership"),
        AcceptanceCheck("native_reporting", convergence.get("decision_first_reporting_required") is True and "USER_REPORT" in reporting_source and "TECHNICAL_APPENDIX" in reporting_source and "COMPACT_DELTA" in reporting_source, Plane.GOVERNANCE, "reporting separates user, technical and delta layers"),
        AcceptanceCheck("v320_source_policy", source_policy.get("source_network_locations_are_registry_owned") is True and source_policy.get("source_ingestion_timeouts_are_registry_owned") is True and source_policy.get("active_artifact_aliases_must_not_embed_gameweek") is True, Plane.INTELLIGENCE, "settled source ownership semantics are preserved"),
        AcceptanceCheck("onefpl_report_time_boundary", onefpl.get("enabled") is False and onefpl.get("adapter") == "disabled" and onefpl.get("delegated_to") == convergence.get("onefpl_report_time_delegation_required"), Plane.INTELLIGENCE, "OneFPL automated collector remains disabled and report-time delegated"),
        AcceptanceCheck("understat_scrape_disabled", understat.get("enabled") is False and understat.get("adapter") == "disabled", Plane.INTELLIGENCE, "Understat direct scrape stays disabled by production source policy"),
        AcceptanceCheck("release_attestation", attestation.get("contract") == "V5_RELEASE_ATTESTATION_V1" and bool(attestation.get("attestation")) and attestation.get("production_main_sha") == baseline_sha, Plane.GOVERNANCE, "candidate release attestation binds version, baseline and runtime fingerprint"),
        AcceptanceCheck("advanced_feature_bundle", (ROOT / "src/v5/intelligence/feature_bundle.py").exists() and (ROOT / "config/intelligence/advanced_prediction.json").exists(), Plane.INTELLIGENCE, "advanced features expose truthful consumption state"),
        AcceptanceCheck("temporal_backtest", (ROOT / "src/v5/evaluation/temporal_backtest.py").exists() and (ROOT / "src/v5/evaluation/prediction_settlement.py").exists(), Plane.INTELLIGENCE, "prediction evaluation exposes temporal leakage and settlement guards"),
        AcceptanceCheck("correlated_simulation_shadow", (ROOT / "src/v5/decision/correlated_simulation.py").exists() and (ROOT / "config/intelligence/correlated_simulation.json").exists(), Plane.DECISION, "correlated simulation exists as calibrated-shadow utility, not authority"),
        AcceptanceCheck("isolated_team_review", (ROOT / "src/v5/team_review.py").exists() and load_json_config("config/v5_team_review_registry.json").get("may_mutate_decision") is False, Plane.GOVERNANCE, "team review is isolated and read-only"),
        AcceptanceCheck("capability_parity_registry", bool(parity_cfg.get("required_domains")) and parity_cfg.get("governance", {}).get("missing_parity_evidence_blocks_promotion") is True, Plane.GOVERNANCE, "V3/V4 capability parity is explicit"),
        AcceptanceCheck("gate0_registry_authority", int(gate0_contract.get("expected_count") or 0) == len(gate0_checks) and len(gate0_checks) > 0, Plane.GOVERNANCE, "Gate0 checks come from canonical registry"),
        AcceptanceCheck("parallel_analysis_preflight", bool(parallel_required) and parallel_required.issubset(analysis_group) and all(x in routes for x in parallel_required), Plane.GOVERNANCE, "analysis preflight routes remain parallelized"),
        AcceptanceCheck("modular_separation_default", modular.get("default_action") == "SEPARATE_WHEN_PRACTICAL", Plane.GOVERNANCE, "separable domains default to modules/registries"),
        AcceptanceCheck("module_registry_discoverable", len(modules) >= int(module_policy["minimum_registered_modules"]) and all(x.entrypoint and x.config for x in modules), Plane.GOVERNANCE, "registered modules expose entrypoint and config"),
        AcceptanceCheck("truth_modules_active", _registered_modules_ok(list(module_policy["required_truth_modules"]), active), Plane.TRUTH, "truth authorities active"),
        AcceptanceCheck("intelligence_modules_active", _registered_modules_ok(list(module_policy["required_intelligence_modules"]), active), Plane.INTELLIGENCE, "intelligence/evaluation authorities active"),
        AcceptanceCheck("decision_modules_active", _registered_modules_ok(list(module_policy["required_decision_modules"]), active), Plane.DECISION, "decision authorities active"),
        AcceptanceCheck("framework_modules_active", _registered_modules_ok(list(module_policy["required_framework_modules"]), active), Plane.GOVERNANCE, "framework authorities active"),
        AcceptanceCheck("presentation_modules_active", _registered_modules_ok(list(module_policy.get("required_presentation_modules") or []), active), Plane.GOVERNANCE, "reporting authority active"),
        AcceptanceCheck("governance_modules_active", _registered_modules_ok(list(module_policy["required_governance_modules"]), active), Plane.GOVERNANCE, "runtime governance authorities active"),
        AcceptanceCheck("microservices_mandatory", acceptance["architecture"].get("require_microservices") is True and micro.get("required") is True and service_cfg.get("mandatory") is True and service_cfg.get("architecture") == "bounded-context-microservices", Plane.GOVERNANCE, "bounded-context microservices mandatory"),
        AcceptanceCheck("microservice_topology_valid", len(services) >= int(service_policy["minimum_services"]) and required_services.issubset(service_ids) and not service_errors, Plane.GOVERNANCE, "service topology valid"),
        AcceptanceCheck("deployment_manifest_present", (ROOT / str(service_policy["require_deployment_manifest"])).exists(), Plane.GOVERNANCE, "deployment manifest present"),
        AcceptanceCheck("v4_bridge_not_authority", "prediction_bridge" not in {x.name for x in modules} and load_json_config("config/v5_runner_registry.json").get("feature_switches", {}).get("v4_prediction_bridge") is False, Plane.INTELLIGENCE, "V4 bridge is reference only"),
        AcceptanceCheck("production_promotion_locked", manifest.get("production_promotion", {}).get("allowed") is False, Plane.GOVERNANCE, "pre-production engine cannot replace production"),
    )
    return AcceptanceReport(version=V5_VERSION, checks=checks)


def main() -> int:
    report = run_bootstrap_acceptance()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
