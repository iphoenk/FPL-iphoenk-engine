from __future__ import annotations

import json

from src.rules import GOAL_POINTS, RULESET_ID, RULESET_SEASON, ruleset_metadata
from src.v5 import V5_VERSION
from src.v5.config_cache import ROOT, load_json_config
from src.v5.contracts import AcceptanceCheck, AcceptanceReport, Plane
from src.v5.module_registry import module_specs
from src.v5.service_registry import registry as service_registry, service_specs, validate_registry

ACCEPTANCE_CONFIG = "config/v5_acceptance_registry.json"
MANIFEST_CONFIG = "config/v5_convergence_manifest.json"
ARCHITECTURE_CONFIG = "config/v5_architecture_principles.json"
ORCHESTRATOR_CONFIG = "config/v5_orchestrator_registry.json"
GATE0_CONFIG = "config/gate0_registry.json"
SOURCE_CONFIG = "config/sources/registry.json"
SOURCE_AUTHORITY_CONFIG = "config/v5_source_authority_registry.json"


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
    return {
        str(row.get("id")): row
        for row in registry.get("sources") or []
        if isinstance(row, dict) and row.get("id")
    }


def run_bootstrap_acceptance() -> AcceptanceReport:
    acceptance = load_json_config(ACCEPTANCE_CONFIG)
    manifest = load_json_config(MANIFEST_CONFIG)
    architecture = load_json_config(ARCHITECTURE_CONFIG)
    orchestrator_cfg = load_json_config(ORCHESTRATOR_CONFIG)
    gate0_cfg = load_json_config(GATE0_CONFIG)
    source_registry_cfg = load_json_config(SOURCE_CONFIG)
    source_authority_cfg = load_json_config(SOURCE_AUTHORITY_CONFIG)
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

    baseline = str(convergence.get("production_baseline") or "")
    baseline_sha = str(convergence.get("production_main_sha") or "")
    manifest_baselines = manifest.get("baselines") or {}

    source_policy = source_registry_cfg.get("policy") or {}
    source_rows = _source_rows(source_registry_cfg)
    authority_governance = source_authority_cfg.get("governance") or {}
    authority_sources = source_authority_cfg.get("sources") or {}
    onefpl = source_rows.get("onefpl") or {}
    livefpl = source_rows.get("livefpl") or {}

    required_observation_contract = str(
        convergence.get("challenger_observation_contract_required") or ""
    )
    required_onefpl_parser = str(convergence.get("onefpl_parser_contract_required") or "")
    required_livefpl_parser = str(convergence.get("livefpl_parser_contract_required") or "")

    checks = (
        AcceptanceCheck(
            "v5_manifest",
            manifest.get("version") == V5_VERSION,
            Plane.GOVERNANCE,
            "package version matches convergence manifest",
        ),
        AcceptanceCheck(
            "production_baseline_declared",
            manifest_baselines.get("production_truth") == baseline
            and manifest_baselines.get("production_main_sha") == baseline_sha
            and bool(baseline_sha),
            Plane.TRUTH,
            "production baseline version and SHA are registry-driven and consistent",
        ),
        AcceptanceCheck(
            "prediction_baseline_declared",
            baseline in str(manifest_baselines.get("prediction_intelligence") or ""),
            Plane.INTELLIGENCE,
            "prediction convergence references accepted production baseline",
        ),
        AcceptanceCheck(
            "rules_registry_active",
            RULESET_ID == "FPL_2026_27" and RULESET_SEASON == "2026/27",
            Plane.TRUTH,
            "verified season rules remain single authority",
        ),
        AcceptanceCheck(
            "goalkeeper_goal_rule",
            GOAL_POINTS.get(1) == 10,
            Plane.TRUTH,
            "goalkeeper goal scoring remains 10",
        ),
        AcceptanceCheck(
            "rules_fingerprint_present",
            bool(metadata.get("fingerprint_sha256")),
            Plane.GOVERNANCE,
            "ruleset exposes auditable fingerprint",
        ),
        AcceptanceCheck(
            "prediction_consumes_truth_contract",
            'payload.get("rules")' in prediction_source and "from src.rules import" not in prediction_source,
            Plane.INTELLIGENCE,
            "prediction consumes truth rules contract",
        ),
        AcceptanceCheck(
            "prediction_network_contract_compact",
            '"rates": player.get("rates")' not in prediction_source,
            Plane.INTELLIGENCE,
            "full attacking-rate blob stays inside prediction boundary",
        ),
        AcceptanceCheck(
            "native_decision",
            "build_packages" in decision_source
            and "optimize_lineup" in decision_source
            and "build_trace" in decision_source
            and "build_watchlist" not in decision_source,
            Plane.DECISION,
            "decision owns package/lineup/trace without importing watchlist authority",
        ),
        AcceptanceCheck(
            "native_watchlist_service",
            convergence.get("full_dss_watchlist_required") is True
            and "build_watchlist" in watchlist_source
            and "FULL_DSS" not in decision_source,
            Plane.DECISION,
            "full DSS external screening is an independent service",
        ),
        AcceptanceCheck(
            "native_reporting",
            convergence.get("decision_first_reporting_required") is True
            and "USER_REPORT" in reporting_source
            and "TECHNICAL_APPENDIX" in reporting_source
            and "COMPACT_DELTA" in reporting_source,
            Plane.GOVERNANCE,
            "reporting separates user, technical and delta layers",
        ),
        AcceptanceCheck(
            "v318_source_reachability_contract",
            convergence.get("source_reachability_separate_from_capability_health_required") is True
            and source_policy.get("source_reachability_is_separate_from_capability_health") is True
            and authority_governance.get("source_reachability_is_separate_from_capability_health") is True,
            Plane.INTELLIGENCE,
            "V3.18.1 reachability and capability-health semantics are preserved",
        ),
        AcceptanceCheck(
            "v318_stale_observation_guard",
            convergence.get("stale_observations_never_silently_current_required") is True
            and source_policy.get("stale_observations_are_never_silently_current") is True
            and authority_governance.get("stale_observations_are_never_silently_current") is True,
            Plane.INTELLIGENCE,
            "stale challenger observations cannot be silently treated as current",
        ),
        AcceptanceCheck(
            "v318_challenger_observation_contract",
            required_observation_contract == "challenger_observation_v2"
            and source_policy.get("challenger_observation_contract") == required_observation_contract
            and authority_governance.get("challenger_observation_contract") == required_observation_contract,
            Plane.INTELLIGENCE,
            "challenger observation schema is explicit and baseline-compatible",
        ),
        AcceptanceCheck(
            "v318_onefpl_structured_contract",
            required_onefpl_parser == "onefpl-price-v2"
            and onefpl.get("parser_contract") == required_onefpl_parser
            and bool(onefpl.get("structured_url"))
            and bool(onefpl.get("fallback_structured_urls"))
            and bool(onefpl.get("allowed_hosts"))
            and int(onefpl.get("observation_ttl_seconds") or 0) > 0,
            Plane.INTELLIGENCE,
            "OneFPL structured-access contract matches the accepted V3.18.1 baseline",
        ),
        AcceptanceCheck(
            "v318_livefpl_structured_contract",
            required_livefpl_parser == "livefpl-price-v1"
            and livefpl.get("parser_contract") == required_livefpl_parser
            and bool(livefpl.get("structured_url"))
            and int(livefpl.get("observation_ttl_seconds") or 0) > 0,
            Plane.INTELLIGENCE,
            "LiveFPL structured challenger contract remains explicit",
        ),
        AcceptanceCheck(
            "runtime_enrichment_authority_consistent",
            bool((authority_sources.get("understat") or {}).get("enabled"))
            and bool((authority_sources.get("api_football") or {}).get("enabled")),
            Plane.INTELLIGENCE,
            "runtime enrichment providers are represented consistently in source authority",
        ),
        AcceptanceCheck(
            "gate0_registry_authority",
            int(gate0_contract.get("expected_count") or 0) == len(gate0_checks) and len(gate0_checks) > 0,
            Plane.GOVERNANCE,
            "Gate0 checks come from canonical registry",
        ),
        AcceptanceCheck(
            "parallel_analysis_preflight",
            bool(parallel_required)
            and parallel_required.issubset(analysis_group)
            and all(x in routes for x in parallel_required),
            Plane.GOVERNANCE,
            "analysis preflight routes remain parallelized",
        ),
        AcceptanceCheck(
            "modular_separation_default",
            modular.get("default_action") == "SEPARATE_WHEN_PRACTICAL",
            Plane.GOVERNANCE,
            "separable domains default to modules/registries",
        ),
        AcceptanceCheck(
            "module_registry_discoverable",
            len(modules) >= int(module_policy["minimum_registered_modules"])
            and all(x.entrypoint and x.config for x in modules),
            Plane.GOVERNANCE,
            "registered modules expose entrypoint and config",
        ),
        AcceptanceCheck(
            "truth_modules_active",
            _registered_modules_ok(list(module_policy["required_truth_modules"]), active),
            Plane.TRUTH,
            "truth authorities active",
        ),
        AcceptanceCheck(
            "intelligence_modules_active",
            _registered_modules_ok(list(module_policy["required_intelligence_modules"]), active),
            Plane.INTELLIGENCE,
            "intelligence/evaluation authorities active",
        ),
        AcceptanceCheck(
            "decision_modules_active",
            _registered_modules_ok(list(module_policy["required_decision_modules"]), active),
            Plane.DECISION,
            "decision authorities active",
        ),
        AcceptanceCheck(
            "framework_modules_active",
            _registered_modules_ok(list(module_policy["required_framework_modules"]), active),
            Plane.GOVERNANCE,
            "framework authorities active",
        ),
        AcceptanceCheck(
            "presentation_modules_active",
            _registered_modules_ok(list(module_policy.get("required_presentation_modules") or []), active),
            Plane.GOVERNANCE,
            "reporting authority active",
        ),
        AcceptanceCheck(
            "governance_modules_active",
            _registered_modules_ok(list(module_policy["required_governance_modules"]), active),
            Plane.GOVERNANCE,
            "runtime governance authorities active",
        ),
        AcceptanceCheck(
            "microservices_mandatory",
            acceptance["architecture"].get("require_microservices") is True
            and micro.get("required") is True
            and service_cfg.get("mandatory") is True
            and service_cfg.get("architecture") == "bounded-context-microservices",
            Plane.GOVERNANCE,
            "bounded-context microservices mandatory",
        ),
        AcceptanceCheck(
            "microservice_topology_valid",
            len(services) >= int(service_policy["minimum_services"])
            and required_services.issubset(service_ids)
            and not service_errors,
            Plane.GOVERNANCE,
            "service topology valid",
        ),
        AcceptanceCheck(
            "deployment_manifest_present",
            (ROOT / str(service_policy["require_deployment_manifest"])).exists(),
            Plane.GOVERNANCE,
            "deployment manifest present",
        ),
        AcceptanceCheck(
            "v4_bridge_not_authority",
            "prediction_bridge" not in {x.name for x in modules}
            and load_json_config("config/v5_runner_registry.json")
            .get("feature_switches", {})
            .get("v4_prediction_bridge")
            is False,
            Plane.INTELLIGENCE,
            "V4 bridge is reference only",
        ),
        AcceptanceCheck(
            "production_promotion_locked",
            manifest.get("production_promotion", {}).get("allowed") is False,
            Plane.GOVERNANCE,
            "pre-production engine cannot replace production",
        ),
    )
    return AcceptanceReport(version=V5_VERSION, checks=checks)


def main() -> int:
    report = run_bootstrap_acceptance()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
