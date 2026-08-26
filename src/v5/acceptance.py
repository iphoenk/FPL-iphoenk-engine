from __future__ import annotations

import json
from pathlib import Path

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
        (m := modules.get(name)) is not None
        and m.status in active_statuses
        and bool(m.entrypoint)
        and bool(m.config)
        and not m.entrypoint.startswith("planned")
        and not m.config.startswith("planned")
        and (ROOT / m.config).exists()
        for name in names
    )


def run_bootstrap_acceptance() -> AcceptanceReport:
    acceptance = load_json_config(ACCEPTANCE_CONFIG)
    manifest = load_json_config(MANIFEST_CONFIG)
    architecture = load_json_config(ARCHITECTURE_CONFIG)
    projection_source = (ROOT / "src/models/projection.py").read_text(encoding="utf-8")
    metadata = ruleset_metadata()
    modules = module_specs()
    module_policy = acceptance["module_policy"]
    service_policy = acceptance["service_policy"]
    active_statuses = {str(x) for x in module_policy["active_statuses"]}
    modular_policy = architecture.get("principles", {}).get("modular_authority", {})
    microservice_policy = architecture.get("principles", {}).get("microservices", {})
    services = service_specs()
    service_ids = {s.service_id for s in services}
    required_services = {str(x) for x in service_policy["required_services"]}
    service_errors = validate_registry()
    deployment_path = ROOT / str(service_policy["require_deployment_manifest"])
    service_cfg = service_registry()

    checks = (
        AcceptanceCheck(
            "v5_manifest",
            manifest.get("version") == V5_VERSION,
            Plane.GOVERNANCE,
            "V5 package version matches convergence manifest",
        ),
        AcceptanceCheck(
            "v3_truth_baseline_declared",
            str(manifest.get("baselines", {}).get("production_truth", "")).startswith("v3"),
            Plane.TRUTH,
            "Production truth baseline remains explicitly V3",
        ),
        AcceptanceCheck(
            "v4_prediction_baseline_declared",
            manifest.get("baselines", {}).get("prediction_intelligence") == "v4-prediction-engine",
            Plane.INTELLIGENCE,
            "Prediction benchmark remains V4",
        ),
        AcceptanceCheck(
            "rules_registry_active",
            RULESET_ID == "FPL_2026_27" and RULESET_SEASON == "2026/27",
            Plane.TRUTH,
            "Verified 2026/27 ruleset is the active single authority",
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
            "projection_uses_rules_registry",
            "from src.rules import" in projection_source and "GOAL_POINTS" in projection_source,
            Plane.INTELLIGENCE,
            "Projection imports scoring constants from the unified rules authority",
        ),
        AcceptanceCheck(
            "no_legacy_goal_map_in_projection",
            "{1:6,2:6,3:5,4:4}" not in projection_source.replace(" ", ""),
            Plane.GOVERNANCE,
            "Legacy hardcoded goal-points map is absent from projection",
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
            and all(m.entrypoint and m.config and m.adjustment_surface for m in modules),
            Plane.GOVERNANCE,
            "Every registered V5 domain exposes entrypoint, config and adjustment surface",
        ),
        AcceptanceCheck(
            "truth_plane_authorities_active",
            _registered_modules_ok(list(module_policy["required_truth_modules"]), active_statuses),
            Plane.TRUTH,
            "All registry-declared mandatory truth authorities are active and discoverable",
        ),
        AcceptanceCheck(
            "governance_modules_active",
            _registered_modules_ok(list(module_policy["required_governance_modules"]), active_statuses),
            Plane.GOVERNANCE,
            "All registry-declared mandatory governance modules are active and discoverable",
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
            "production_promotion_locked",
            manifest.get("production_promotion", {}).get("allowed") is False,
            Plane.GOVERNANCE,
            "V5 alpha cannot replace V3 production before convergence acceptance",
        ),
    )
    return AcceptanceReport(version=V5_VERSION, checks=checks)


def main() -> int:
    report = run_bootstrap_acceptance()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
