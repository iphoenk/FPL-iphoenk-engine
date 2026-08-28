from __future__ import annotations

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
        "decision_and_evaluation_layers_consume_artifacts_not_standard_official_network",
        "bundle_modules_are_orchestration_only",
        "bundle_modules_must_not_duplicate_business_formulas",
        "version_stamped_modules_are_not_active_runtime_owners",
        "microservice_boundaries_follow_artifact_and_failure_ownership",
        "policy_thresholds_belong_in_config_or_rules",
    ):
        if policy.get(key) is not True:
            errors.append(f"logic ownership policy missing {key}=true")

    if "collector" in services:
        errors.append("monolithic collector service is forbidden")
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

    duplicate_module_owners = {module: owners for module, owners in sorted(module_owners.items()) if len(set(owners)) > 1}
    if duplicate_module_owners:
        errors.append(f"active service command modules have multiple owners: {duplicate_module_owners}")

    approved_fetch = set(str(x) for x in policy_payload.get("approved_direct_official_fetch_modules") or [])
    forbidden_fetch_stages = set(str(x) for x in policy_payload.get("forbidden_direct_official_fetch_service_stages") or [])
    direct_fetch_modules: list[str] = []
    for module in sorted(set(active_modules)):
        path = _module_path(module)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8")
        direct = "src.sources.official_fpl" in text
        if direct:
            direct_fetch_modules.append(module)
            approved = module in approved_fetch
            if not approved:
                errors.append(f"unapproved direct Official public fetch owner: {module}")
                if module_stage.get(module) in forbidden_fetch_stages:
                    errors.append(f"decision/downstream stage directly fetches Official public API: {module_stage.get(module)}:{module}")
    unexpected_approved = sorted(approved_fetch - set(active_modules))
    if unexpected_approved:
        errors.append(f"approved Official fetch modules are not active runtime commands: {unexpected_approved}")

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
        "active_model_ids": len(model_ids),
        "duplicate_model_ids": duplicate_model_ids,
        "policy": {
            "microservice_architecture_preserved": len(services) >= 10 and "collector" not in services,
            "standard_official_fetch_is_explicitly_owned": set(direct_fetch_modules).issubset(approved_fetch),
            "bundles_are_orchestration_only": not any("bundle contains forbidden" in error for error in errors),
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
