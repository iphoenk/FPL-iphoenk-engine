from __future__ import annotations
import json
from src.rules import GOAL_POINTS,RULESET_ID,RULESET_SEASON,ruleset_metadata
from src.v5 import V5_VERSION
from src.v5.config_cache import ROOT,load_json_config
from src.v5.contracts import AcceptanceCheck,AcceptanceReport,Plane
from src.v5.module_registry import module_specs
from src.v5.service_registry import registry as service_registry,service_specs,validate_registry
ACCEPTANCE_CONFIG="config/v5_acceptance_registry.json"; MANIFEST_CONFIG="config/v5_convergence_manifest.json"; ARCHITECTURE_CONFIG="config/v5_architecture_principles.json"; ORCHESTRATOR_CONFIG="config/v5_orchestrator_registry.json"; GATE0_CONFIG="config/gate0_registry.json"
def _registered_modules_ok(names:list[str],active_statuses:set[str])->bool:
    modules={x.name:x for x in module_specs()}; return all((m:=modules.get(name)) is not None and m.status in active_statuses and bool(m.entrypoint) and bool(m.config) and not m.entrypoint.startswith("planned") and not m.config.startswith("planned") and (ROOT/m.config).exists() for name in names)
def run_bootstrap_acceptance()->AcceptanceReport:
    acceptance=load_json_config(ACCEPTANCE_CONFIG); manifest=load_json_config(MANIFEST_CONFIG); architecture=load_json_config(ARCHITECTURE_CONFIG); orchestrator_cfg=load_json_config(ORCHESTRATOR_CONFIG); gate0_cfg=load_json_config(GATE0_CONFIG); metadata=ruleset_metadata(); modules=module_specs(); module_policy=acceptance["module_policy"]; service_policy=acceptance["service_policy"]; convergence=acceptance.get("convergence") or {}; active={str(x) for x in module_policy["active_statuses"]}; services=service_specs(); service_ids={x.service_id for x in services}; required_services={str(x) for x in service_policy["required_services"]}; service_errors=validate_registry(); service_cfg=service_registry(); modular=architecture.get("principles",{}).get("modular_authority",{}); micro=architecture.get("principles",{}).get("microservices",{}); gate0_contract=gate0_cfg.get("contract") or {}; gate0_checks=gate0_cfg.get("checks") or []; parallel_groups=orchestrator_cfg.get("parallel_groups") or {}; routes=orchestrator_cfg.get("routing") or {}; parallel_required={str(x) for x in convergence.get("analysis_parallel_routes_required") or []}; analysis_group={str(x) for x in parallel_groups.get("analysis_preflight") or []}; prediction_source=(ROOT/"src/v5/services/prediction.py").read_text(); decision_source=(ROOT/"src/v5/services/decision.py").read_text(); watchlist_source=(ROOT/"src/v5/services/watchlist.py").read_text(); reporting_source=(ROOT/"src/v5/reporting.py").read_text(); baseline=str(convergence.get("production_baseline") or ""); baseline_sha=str(convergence.get("production_main_sha") or ""); mb=manifest.get("baselines") or {}
    checks=(
        AcceptanceCheck("v5_manifest",manifest.get("version")==V5_VERSION,Plane.GOVERNANCE,"package version matches convergence manifest"),
        AcceptanceCheck("production_baseline_declared",mb.get("production_truth")==baseline and mb.get("production_main_sha")==baseline_sha and bool(baseline_sha),Plane.TRUTH,"production baseline version and SHA are registry-driven and consistent"),
        AcceptanceCheck("prediction_baseline_declared",baseline in str(mb.get("prediction_intelligence") or ""),Plane.INTELLIGENCE,"prediction convergence references accepted production baseline"),
        AcceptanceCheck("rules_registry_active",RULESET_ID=="FPL_2026_27" and RULESET_SEASON=="2026/27",Plane.TRUTH,"verified season rules remain single authority"),
        AcceptanceCheck("goalkeeper_goal_rule",GOAL_POINTS.get(1)==10,Plane.TRUTH,"goalkeeper goal scoring remains 10"),
        AcceptanceCheck("rules_fingerprint_present",bool(metadata.get("fingerprint_sha256")),Plane.GOVERNANCE,"ruleset exposes auditable fingerprint"),
        AcceptanceCheck("prediction_consumes_truth_contract",'payload.get("rules")' in prediction_source and "from src.rules import" not in prediction_source,Plane.INTELLIGENCE,"prediction consumes truth rules contract"),
        AcceptanceCheck("prediction_network_contract_compact",'"rates": player.get("rates")' not in prediction_source,Plane.INTELLIGENCE,"full attacking-rate blob stays inside prediction boundary"),
        AcceptanceCheck("native_decision","build_packages" in decision_source and "optimize_lineup" in decision_source and "build_trace" in decision_source and "build_watchlist" not in decision_source,Plane.DECISION,"decision owns package/lineup/trace without importing watchlist authority"),
        AcceptanceCheck("native_watchlist_service",convergence.get("full_dss_watchlist_required") is True and "build_watchlist" in watchlist_source and "FULL_DSS" not in decision_source,Plane.DECISION,"full DSS external screening is an independent service"),
        AcceptanceCheck("native_reporting",convergence.get("decision_first_reporting_required") is True and "USER_REPORT" in reporting_source and "TECHNICAL_APPENDIX" in reporting_source and "COMPACT_DELTA" in reporting_source,Plane.GOVERNANCE,"reporting separates user, technical and delta layers"),
        AcceptanceCheck("gate0_registry_authority",int(gate0_contract.get("expected_count") or 0)==len(gate0_checks) and len(gate0_checks)>0,Plane.GOVERNANCE,"Gate0 checks come from canonical registry"),
        AcceptanceCheck("parallel_analysis_preflight",bool(parallel_required) and parallel_required.issubset(analysis_group) and all(x in routes for x in parallel_required),Plane.GOVERNANCE,"analysis preflight routes remain parallelized"),
        AcceptanceCheck("modular_separation_default",modular.get("default_action")=="SEPARATE_WHEN_PRACTICAL",Plane.GOVERNANCE,"separable domains default to modules/registries"),
        AcceptanceCheck("module_registry_discoverable",len(modules)>=int(module_policy["minimum_registered_modules"]) and all(x.entrypoint and x.config for x in modules),Plane.GOVERNANCE,"registered modules expose entrypoint and config"),
        AcceptanceCheck("truth_modules_active",_registered_modules_ok(list(module_policy["required_truth_modules"]),active),Plane.TRUTH,"truth authorities active"),
        AcceptanceCheck("intelligence_modules_active",_registered_modules_ok(list(module_policy["required_intelligence_modules"]),active),Plane.INTELLIGENCE,"intelligence/evaluation authorities active"),
        AcceptanceCheck("decision_modules_active",_registered_modules_ok(list(module_policy["required_decision_modules"]),active),Plane.DECISION,"decision authorities active"),
        AcceptanceCheck("framework_modules_active",_registered_modules_ok(list(module_policy["required_framework_modules"]),active),Plane.GOVERNANCE,"framework authorities active"),
        AcceptanceCheck("presentation_modules_active",_registered_modules_ok(list(module_policy.get("required_presentation_modules") or []),active),Plane.GOVERNANCE,"reporting authority active"),
        AcceptanceCheck("governance_modules_active",_registered_modules_ok(list(module_policy["required_governance_modules"]),active),Plane.GOVERNANCE,"runtime governance authorities active"),
        AcceptanceCheck("microservices_mandatory",acceptance["architecture"].get("require_microservices") is True and micro.get("required") is True and service_cfg.get("mandatory") is True and service_cfg.get("architecture")=="bounded-context-microservices",Plane.GOVERNANCE,"bounded-context microservices mandatory"),
        AcceptanceCheck("microservice_topology_valid",len(services)>=int(service_policy["minimum_services"]) and required_services.issubset(service_ids) and not service_errors,Plane.GOVERNANCE,"service topology valid"),
        AcceptanceCheck("deployment_manifest_present",(ROOT/str(service_policy["require_deployment_manifest"])).exists(),Plane.GOVERNANCE,"deployment manifest present"),
        AcceptanceCheck("v4_bridge_not_authority","prediction_bridge" not in {x.name for x in modules} and load_json_config("config/v5_runner_registry.json").get("feature_switches",{}).get("v4_prediction_bridge") is False,Plane.INTELLIGENCE,"V4 bridge is reference only"),
        AcceptanceCheck("production_promotion_locked",manifest.get("production_promotion",{}).get("allowed") is False,Plane.GOVERNANCE,"pre-production engine cannot replace production"),
    ); return AcceptanceReport(version=V5_VERSION,checks=checks)
def main()->int:
    report=run_bootstrap_acceptance(); print(json.dumps(report.as_dict(),indent=2,sort_keys=True)); return 0 if report.passed else 1
if __name__=="__main__":raise SystemExit(main())
