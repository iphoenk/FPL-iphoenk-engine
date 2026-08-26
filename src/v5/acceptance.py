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


def _registered_modules_ok(names: list[str], active_statuses: set[str]) -> bool:
    modules = {m.name: m for m in module_specs()}
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


def run_bootstrap_acceptance() -> AcceptanceReport:
    acceptance = load_json_config(ACCEPTANCE_CONFIG)
    manifest = load_json_config(MANIFEST_CONFIG)
    architecture = load_json_config(ARCHITECTURE_CONFIG)
    metadata = ruleset_metadata()
    modules = module_specs()
    module_policy = acceptance["module_policy"]
    service_policy = acceptance["service_policy"]
    active_statuses = {str(x) for x in module_policy["active_statuses"]}
    modular_policy = architecture.get("principles", {}).get("modular_authority", {})
    microservice_policy = architecture.get("principles", {}).get("microservices", {})
    services = service_specs()
    service_ids = {service.service_id for service in services}
    required_services = {str(x) for x in service_policy["required_services"]}
    service_errors = validate_registry()
    deployment_path = ROOT / str(service_policy["require_deployment_manifest"])
    service_cfg = service_registry()
    prediction_source = (ROOT / "src/v5/services/prediction.py").read_text(encoding="utf-8")
    decision_source = (ROOT / "src/v5/services/decision.py").read_text(encoding="utf-8")
    gate0_source = (ROOT / "src/v5/governance/gate0.py").read_text(encoding="utf-8")
    orchestrator_source = (ROOT / "src/v5/services/orchestrator.py").read_text(encoding="utf-8")

    required_intelligence = list(module_policy.get("required_intelligence_modules") or [])
    required_decision = list(module_policy.get("required_decision_modules") or [])
    required_framework = list(module_policy.get("required_framework_modules") or [])
    convergence = acceptance.get("convergence") or {}
    checks = (
        AcceptanceCheck(
            "v5_manifest",
            manifest.get("version") == V5_VERSION,
            Plane.GOVERNANCE,
            "V5 package version matches convergence manifest",
        ),
        AcceptanceCheck(
            "v3_10_production_baseline",
            manifest.get("baselines", {}).get("production_truth") == "v3.10.0"
            and bool(manifest.get("baselines", {}).get("production_main_sha")),
            Plane.TRUTH,
            "V5 convergence is anchored to the current v3.10 production baseline",
        ),
        AcceptanceCheck(
            "p0_baseline_declared",
            "v3.10.0" in str(manifest.get("baselines", {}).get("prediction_intelligence", "")),
            Plane.INTELLIGENCE,
            "P0 prediction intelligence is an explicit convergence baseline",
        ),
        AcceptanceCheck(
            "rules_registry_active",
            RULESET_ID == "FPL_2026_27" and RULESET_SEASON == "2026/27",
            Plane.TRUTH,
            "Verified 2026/27 ruleset remains the single rules authority",
        ),
        AcceptanceCheck(
            "goalkeeper_goal_rule",
            GOAL_POINTS.get(1) == 10,
            Plane.TRUTH,
            "Goalkeeper goal scoring is 10 points for 2026/27",
        ),
        AcceptanceCheck(
            "rules_fingerprint_present",
            bool(metadata.get("fingerprint_sha256")),
            Plane.GOVERNANCE,
            "Active ruleset exposes an auditable fingerprint",
        ),
        AcceptanceCheck(
            "prediction_consumes_truth_rules_contract",
            'payload.get("rules")' in prediction_source and "from src.rules import" not in prediction_source,
            Plane.INTELLIGENCE,
            "Prediction service consumes the truth-service rules contract instead of importing rules business authority",
        ),
        AcceptanceCheck(
            "decision_not_bridge_only",
            "BRIDGE_ONLY" not in decision_source and "build_packages" in decision_source,
            Plane.DECISION,
            "Decision service owns a real package optimizer instead of a bridge-only summary",
        ),
        AcceptanceCheck(
            "native_lineup_and_trace",
            convergence.get("native_lineup_required") is True
            and convergence.get("decision_trace_required") is True
            and "optimize_lineup" in decision_source
            and "build_trace" in decision_source,
            Plane.DECISION,
            "Decision service owns native lineup governance and auditable decision trace",
        ),
        AcceptanceCheck(
            "gate0_full_16_authority",
            convergence.get("gate0_full_16_required") is True
            and "def audit(" in gate0_source
            and "G0-16" in gate0_source
            and "purchase_total + bank" not in gate0_source,
            Plane.GOVERNANCE,
            "Gate0 owns preflight/postflight 16-check legality without the invalid static £100m team-value cap",
        ),
        AcceptanceCheck(
            "parallel_evaluation_decision_prepare",
            "decision_prepare" in orchestrator_source
            and "decision_finalize" in orchestrator_source
            and "evaluation_and_decision_prepare" in orchestrator_source,
            Plane.GOVERNANCE,
            "Heavy decision preparation remains parallel with evaluation before lightweight finalization",
        ),
        AcceptanceCheck(
            "orchestrator_uses_evaluation_and_governance",
            "evaluation_build" in orchestrator_source and "governance_audit" in orchestrator_source,
            Plane.GOVERNANCE,
            "Orchestrator routes calibration and final governance through independent services",
        ),
        AcceptanceCheck(
            "modular_separation_default",
            modular_policy.get("default_action") == "SEPARATE_WHEN_PRACTICAL",
            Plane.GOVERNANCE,
            "V5 defaults to dedicated modules/registries for separable domains",
        ),
        AcceptanceCheck(
            "module_registry_discoverable",
            len(modules) >= int(module_policy["minimum_registered_modules"])
            and all(module.entrypoint and module.config for module in modules),
            Plane.GOVERNANCE,
            "Every registered V5 domain exposes an entrypoint and configuration authority",
        ),
        AcceptanceCheck(
            "truth_plane_authorities_active",
            _registered_modules_ok(list(module_policy["required_truth_modules"]), active_statuses),
            Plane.TRUTH,
            "All mandatory truth authorities are active and discoverable",
        ),
        AcceptanceCheck(
            "p0_intelligence_modules_active",
            _registered_modules_ok(required_intelligence, active_statuses),
            Plane.INTELLIGENCE,
            "All five P0 capability families are service-owned and active/alpha",
        ),
        AcceptanceCheck(
            "native_decision_modules_active",
            _registered_modules_ok(required_decision, active_statuses),
            Plane.DECISION,
            "Package, lineup, trace and DSS authorities are explicit Decision Service modules",
        ),
        AcceptanceCheck(
            "framework_modules_active",
            _registered_modules_ok(required_framework, active_statuses),
            Plane.GOVERNANCE,
            "Gate0 and enhancement/framework governance are explicit service-owned modules",
        ),
        AcceptanceCheck(
            "governance_modules_active",
            _registered_modules_ok(list(module_policy["required_governance_modules"]), active_statuses),
            Plane.GOVERNANCE,
            "Runtime governance modules are active and discoverable",
        ),
        AcceptanceCheck(
            "microservices_mandatory",
            acceptance["architecture"].get("require_microservices") is True
            and microservice_policy.get("required") is True
            and service_cfg.get("mandatory") is True
            and service_cfg.get("architecture") == "bounded-context-microservices",
            Plane.GOVERNANCE,
            "V5 runtime architecture is explicitly bounded-context microservices",
        ),
        AcceptanceCheck(
            "microservice_topology_valid",
            len(services) >= int(service_policy["minimum_services"])
            and required_services.issubset(service_ids)
            and not service_errors,
            Plane.GOVERNANCE,
            "Registered services have unique ownership, valid ports and an acyclic dependency graph",
        ),
        AcceptanceCheck(
            "microservice_deployment_manifest_present",
            deployment_path.exists(),
            Plane.GOVERNANCE,
            "Independent V5 service deployment manifest is present",
        ),
        AcceptanceCheck(
            "v4_bridge_not_authority",
            "prediction_bridge" not in {module.name for module in modules}
            and load_json_config("config/v5_runner_registry.json").get("feature_switches", {}).get("v4_prediction_bridge") is False,
            Plane.INTELLIGENCE,
            "Legacy V4 prediction bridge is no longer a registered business authority",
        ),
        AcceptanceCheck(
            "production_promotion_locked",
            manifest.get("production_promotion", {}).get("allowed") is False,
            Plane.GOVERNANCE,
            "V5 alpha cannot replace production until parity and postflight gates pass",
        ),
    )
    return AcceptanceReport(version=V5_VERSION, checks=checks)


def main() -> int:
    report = run_bootstrap_acceptance()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
