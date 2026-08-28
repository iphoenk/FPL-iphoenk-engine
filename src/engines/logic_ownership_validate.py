from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.utils import ROOT

SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
EXECUTION_PROFILES = ROOT / "config" / "runtime" / "execution_profiles.json"
POLICY_PATH = ROOT / "config" / "runtime" / "logic_ownership.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _module_path(module: str) -> Path | None:
    if not module.startswith("src."):
        return None
    path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
    return path if path.exists() else None


def _active_model_ids() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted((ROOT / "config" / "intelligence").glob("*.json")):
        try:
            payload = _load(path)
        except Exception:
            continue
        for key in ("model_id", "historical_model_id", "model"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                out[f"{path.name}:{key}"] = value
    return out


def _python_symbol_definitions() -> dict[str, set[str]]:
    definitions: dict[str, set[str]] = defaultdict(set)
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except Exception:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions[node.name].add(relative)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        definitions[target.id].add(relative)
    return definitions


def run() -> dict[str, Any]:
    services_payload = _load(SERVICE_REGISTRY)
    profiles = _load(EXECUTION_PROFILES)
    policy_payload = _load(POLICY_PATH)
    services = services_payload.get("services") or {}
    policy = policy_payload.get("policy") or {}
    errors: list[str] = []

    if policy_payload.get("registry") != "V3_LOGIC_OWNERSHIP_V1":
        errors.append("logic ownership registry must be V3_LOGIC_OWNERSHIP_V1")
    for key in (
        "service_command_module_has_single_runtime_owner",
        "standard_official_network_fetch_has_explicit_owner",
        "official_fetch_authority_is_logical_service_owned_not_file_owned",
        "decision_and_evaluation_layers_consume_artifacts_not_standard_official_network",
        "bundle_modules_are_orchestration_only",
        "bundle_modules_must_not_duplicate_business_formulas",
        "version_stamped_modules_are_not_active_runtime_owners",
        "microservice_boundaries_follow_artifact_and_failure_ownership",
        "policy_thresholds_belong_in_config_or_rules",
        "canonical_rule_symbols_have_single_source_owner",
        "canonical_legality_functions_have_single_source_owner",
        "official_detail_must_reuse_standard_snapshot_endpoints",
        "architecture_guard_runs_outside_runtime_critical_path",
    ):
        if policy.get(key) is not True:
            errors.append(f"logic ownership policy missing {key}=true")

    if "collector" in services:
        errors.append("monolithic collector service is forbidden")
    if "architecture_guard" in services:
        errors.append("architecture guard must remain CI/release-only, not a runtime service")
    if len(services) < 10:
        errors.append(f"runtime unexpectedly collapsed into too few logical services: {len(services)}")

    max_commands = int(policy_payload.get("max_declared_commands_per_logical_service") or 0)
    module_owners: dict[str, list[str]] = defaultdict(list)
    module_stage: dict[str, str] = {}
    active_modules: list[str] = []
    for service_name, spec in services.items():
        commands = list(spec.get("commands") or [])
        if max_commands and len(commands) > max_commands:
            errors.append(f"{service_name} declares {len(commands)} commands > configured anti-monolith ceiling {max_commands}")
        for command in commands:
            module = str(command.get("module") or "")
            if not module:
                errors.append(f"{service_name} has command without module")
                continue
            module_owners[module].append(str(service_name))
            module_stage[module] = str(spec.get("stage") or "")
            active_modules.append(module)
            if re.search(r"(?:^|\.)v3\d{2,}(?:$|\.)", module):
                errors.append(f"version-stamped active runtime module: {module}")
            if _module_path(module) is None:
                errors.append(f"active service module path does not resolve: {module}")

    guard_modules = {
        "src.engines.architecture_contract_validate",
        "src.engines.capability_contract_validate",
        "src.engines.artifact_flow_validate",
        "src.engines.logic_ownership_validate",
    }
    runtime_guards = sorted(set(active_modules) & guard_modules)
    if runtime_guards:
        errors.append(f"architecture guards leaked into runtime critical path: {runtime_guards}")

    duplicate_module_owners = {module: owners for module, owners in sorted(module_owners.items()) if len(set(owners)) > 1}
    if duplicate_module_owners:
        errors.append(f"active service command modules have multiple owners: {duplicate_module_owners}")

    approved_fetch_services = set(str(x) for x in policy_payload.get("approved_direct_official_fetch_services") or [])
    forbidden_fetch_stages = set(str(x) for x in policy_payload.get("forbidden_direct_official_fetch_service_stages_for_unapproved_services") or [])
    invalid_approved_services = sorted(approved_fetch_services - set(services))
    if invalid_approved_services:
        errors.append(f"approved Official fetch services are not runtime services: {invalid_approved_services}")

    direct_fetch_modules: list[str] = []
    direct_fetch_services: set[str] = set()
    module_text: dict[str, str] = {}
    for module in sorted(set(active_modules)):
        path = _module_path(module)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8")
        module_text[module] = text
        if "src.sources.official_fpl" not in text:
            continue
        direct_fetch_modules.append(module)
        owners = set(module_owners.get(module) or [])
        direct_fetch_services.update(owners)
        if len(owners) != 1:
            errors.append(f"direct Official fetch module must have one logical service owner: {module}:{sorted(owners)}")
            continue
        owner = next(iter(owners))
        approved = owner in approved_fetch_services
        if not approved:
            errors.append(f"unapproved direct Official public fetch service: {owner}:{module}")
            if module_stage.get(module) in forbidden_fetch_stages:
                errors.append(f"decision/downstream stage directly fetches Official public API: {module_stage.get(module)}:{owner}:{module}")

    detail_forbidden = [str(x) for x in policy_payload.get("official_detail_forbidden_standard_fetch_tokens") or []]
    detail_modules = sorted(module for module, owners in module_owners.items() if "official_detail" in owners)
    detail_endpoint_violations: list[str] = []
    for module in detail_modules:
        text = module_text.get(module)
        if text is None:
            path = _module_path(module)
            text = path.read_text(encoding="utf-8") if path else ""
        for token in detail_forbidden:
            if token in text:
                violation = f"{module}:{token}"
                detail_endpoint_violations.append(violation)
                errors.append(f"official_detail refetches standard snapshot endpoint: {violation}")

    bundle_owners: dict[str, list[str]] = defaultdict(list)
    forbidden_bundle_tokens = [str(x) for x in policy_payload.get("bundle_forbidden_tokens") or []]
    for profile_name, profile in (profiles.get("profiles") or {}).items():
        for service_name, module in (profile.get("command_bundles") or {}).items():
            module = str(module)
            if service_name not in services:
                errors.append(f"{profile_name} bundle references unknown service: {service_name}")
                continue
            bundle_owners[module].append(str(service_name))
            path = _module_path(module)
            if path is None:
                errors.append(f"bundle module path does not resolve: {module}")
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden_bundle_tokens:
                if token in text:
                    errors.append(f"bundle contains forbidden business/source token: {module}:{token}")
    duplicate_bundle_owners = {module: owners for module, owners in sorted(bundle_owners.items()) if len(set(owners)) > 1}
    if duplicate_bundle_owners:
        errors.append(f"bundle modules assigned to multiple logical services: {duplicate_bundle_owners}")

    definitions = _python_symbol_definitions()
    canonical_owners = policy_payload.get("canonical_symbol_owners") or {}
    canonical_symbol_errors: list[str] = []
    for owner_path, symbols in canonical_owners.items():
        owner_path = str(owner_path)
        if not (ROOT / owner_path).exists():
            canonical_symbol_errors.append(f"canonical owner path missing: {owner_path}")
            continue
        for symbol in symbols or []:
            symbol = str(symbol)
            locations = sorted(definitions.get(symbol) or [])
            if owner_path not in locations:
                canonical_symbol_errors.append(f"canonical symbol missing from owner: {symbol}:{owner_path}")
            extras = [location for location in locations if location != owner_path]
            if extras:
                canonical_symbol_errors.append(f"canonical symbol duplicated: {symbol}:owner={owner_path}:extras={extras}")
    errors.extend(canonical_symbol_errors)

    forbidden_runtime_imports = [str(x) for x in policy_payload.get("forbidden_runtime_imports") or []]
    forbidden_import_hits: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_runtime_imports:
            if token in text:
                hit = f"{path.relative_to(ROOT).as_posix()}:{token}"
                forbidden_import_hits.append(hit)
                errors.append(f"forbidden runtime dependency bypasses canonical primitive: {hit}")

    model_ids = _active_model_ids()
    model_value_owners: dict[str, list[str]] = defaultdict(list)
    for location, value in model_ids.items():
        model_value_owners[value].append(location)
    duplicate_model_ids = {value: locations for value, locations in sorted(model_value_owners.items()) if len(locations) > 1}
    if duplicate_model_ids:
        errors.append(f"active intelligence model ids duplicated across config owners: {duplicate_model_ids}")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "logical_services": len(services),
        "active_command_modules": len(active_modules),
        "unique_command_modules": len(set(active_modules)),
        "duplicate_command_module_owners": duplicate_module_owners,
        "bundle_modules": len(bundle_owners),
        "duplicate_bundle_owners": duplicate_bundle_owners,
        "direct_official_fetch_modules": direct_fetch_modules,
        "direct_official_fetch_services": sorted(direct_fetch_services),
        "approved_official_fetch_services": sorted(approved_fetch_services),
        "official_detail_standard_endpoint_refetches": detail_endpoint_violations,
        "canonical_symbol_errors": canonical_symbol_errors,
        "forbidden_primitive_imports": forbidden_import_hits,
        "active_model_ids": len(model_ids),
        "duplicate_model_ids": duplicate_model_ids,
        "policy": {
            "microservice_architecture_preserved": len(services) >= 10 and "collector" not in services,
            "standard_official_fetch_is_logical_service_owned": direct_fetch_services.issubset(approved_fetch_services),
            "official_detail_reuses_standard_snapshot": not detail_endpoint_violations,
            "canonical_rule_and_legality_ownership_is_single": not canonical_symbol_errors and not forbidden_import_hits,
            "architecture_guard_outside_runtime": not runtime_guards,
            "bundles_are_orchestration_only": not any("bundle contains forbidden" in error for error in errors),
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
