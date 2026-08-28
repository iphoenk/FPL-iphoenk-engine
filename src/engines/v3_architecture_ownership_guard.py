from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.utils import ROOT

OWNERSHIP_PATH = ROOT / "config" / "v3_architecture_ownership_registry.json"
SERVICE_PATH = ROOT / "config" / "v3_service_registry.json"
FRAMEWORK_PATHS = {
    "dss_core": ROOT / "config" / "dss_core_registry.json",
    "dss_extensions": ROOT / "config" / "dss_extension_registry.json",
    "enhancements": ROOT / "config" / "enhancement_layers_registry.json",
    "gate0": ROOT / "config" / "gate0_registry.json",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry must be an object: {path}")
    return payload


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def _framework_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "layers", "checks"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _duplicates(values: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return sorted(value for value, count in counts.items() if count > 1)


def _active_modules(services: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for service, spec in services.items():
        result[service] = {
            str(command.get("module"))
            for command in spec.get("commands") or []
            if command.get("module")
        }
    return result


def _artifact_writers(services: dict[str, Any]) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = defaultdict(set)
    for service, spec in services.items():
        for artifact in spec.get("artifacts") or []:
            writers[str(artifact)].add(service)
    return writers


def _scan_official_fetches(active: dict[str, set[str]]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = defaultdict(list)
    needles = ("src.sources.official_fpl", "from src.sources import official_fpl", "get_json(")
    for service, modules in active.items():
        for module in modules:
            path = _module_path(module)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if any(needle in text for needle in needles):
                hits[service].append(module)
    return {service: sorted(modules) for service, modules in sorted(hits.items())}


def run() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    ownership = _load(OWNERSHIP_PATH)
    service_registry = _load(SERVICE_PATH)
    services = service_registry.get("services") or {}
    if ownership.get("registry") != "V3_ARCHITECTURE_OWNERSHIP_V1":
        errors.append("unexpected V3 architecture ownership registry")
    if not isinstance(services, dict) or not services:
        errors.append("V3 service registry has no services")
        services = {}

    responsibilities = list(ownership.get("responsibilities") or [])
    responsibility_ids = [str(row.get("id")) for row in responsibilities]
    duplicate_responsibilities = _duplicates(responsibility_ids)
    if duplicate_responsibilities:
        errors.append(f"duplicate architecture responsibilities: {duplicate_responsibilities}")
    for row in responsibilities:
        rid = str(row.get("id") or "")
        owner = str(row.get("owner_service") or "")
        implementation = str(row.get("implementation") or "")
        if not rid or not owner or not implementation:
            errors.append(f"invalid responsibility row: {row}")
            continue
        if owner not in services:
            errors.append(f"responsibility {rid} owner service missing: {owner}")
        if implementation.startswith("src.") and not _module_path(implementation).is_file():
            errors.append(f"responsibility {rid} implementation missing: {implementation}")

    primitive_rows = list(ownership.get("shared_primitives") or [])
    primitive_ids = [str(row.get("id")) for row in primitive_rows]
    duplicate_primitives = _duplicates(primitive_ids)
    if duplicate_primitives:
        errors.append(f"duplicate shared primitive ids: {duplicate_primitives}")
    for row in primitive_rows:
        consumers = [str(value) for value in row.get("consumers") or []]
        dup_consumers = _duplicates(consumers)
        if dup_consumers:
            errors.append(f"shared primitive {row.get('id')} repeats consumers: {dup_consumers}")
        implementation = str(row.get("implementation") or "")
        if implementation.startswith("src.") and not _module_path(implementation).is_file():
            errors.append(f"shared primitive {row.get('id')} implementation missing: {implementation}")

    all_framework_ids: list[str] = []
    framework_counts: dict[str, int] = {}
    legacy_modules = {str(value) for value in ownership.get("legacy_business_implementations_to_retire") or []}
    legacy_paths = {module.replace(".", "/") + ".py" for module in legacy_modules}
    legacy_registry_refs: list[str] = []
    for name, path in FRAMEWORK_PATHS.items():
        payload = _load(path)
        rows = _framework_rows(payload)
        ids = [str(row.get("id")) for row in rows]
        framework_counts[name] = len(ids)
        dup = _duplicates(ids)
        if dup:
            errors.append(f"{name} duplicate ids: {dup}")
        all_framework_ids.extend(ids)
        expected = int(payload.get("expected_count") or 0)
        if expected and expected != len(rows):
            errors.append(f"{name} expected_count={expected} declared={len(rows)}")
        for row in rows:
            for required in row.get("required_files") or []:
                required_text = str(required)
                if required_text in legacy_paths:
                    legacy_registry_refs.append(f"{row.get('id')}:{required_text}")
    cross_duplicate_ids = _duplicates(all_framework_ids)
    if cross_duplicate_ids:
        errors.append(f"cross-framework duplicate ids: {cross_duplicate_ids}")
    if legacy_registry_refs:
        errors.append(f"framework registries still point at legacy business implementations: {sorted(legacy_registry_refs)}")

    active = _active_modules(services)
    compatibility = {str(value) for value in ownership.get("compatibility_only_modules") or []}
    forbidden_active = compatibility | legacy_modules
    active_forbidden: list[str] = []
    module_services: dict[str, set[str]] = defaultdict(set)
    for service, modules in active.items():
        for module in modules:
            module_services[module].add(service)
            if module in forbidden_active:
                active_forbidden.append(f"{service}:{module}")
    if active_forbidden:
        errors.append(f"compatibility/legacy modules active in runtime services: {sorted(active_forbidden)}")
    cross_service_module_duplicates = {
        module: sorted(owners)
        for module, owners in module_services.items()
        if len(owners) > 1
    }
    if cross_service_module_duplicates:
        errors.append(f"same executable module owned by multiple services: {cross_service_module_duplicates}")

    writers = _artifact_writers(services)
    staged = ownership.get("declared_staged_artifacts") or {}
    undeclared_multiwriters: dict[str, list[str]] = {}
    bad_staged: dict[str, Any] = {}
    for artifact, owners in sorted(writers.items()):
        if len(owners) <= 1:
            continue
        declaration = staged.get(artifact)
        if not isinstance(declaration, dict):
            undeclared_multiwriters[artifact] = sorted(owners)
            continue
        allowed = {str(value) for value in declaration.get("allowed_writers") or []}
        final_owner = str(declaration.get("final_owner") or "")
        if final_owner not in owners or owners - allowed or not final_owner:
            bad_staged[artifact] = {
                "actual": sorted(owners),
                "allowed": sorted(allowed),
                "final_owner": final_owner,
            }
    if undeclared_multiwriters:
        errors.append(f"undeclared multi-writer artifacts: {undeclared_multiwriters}")
    if bad_staged:
        errors.append(f"invalid staged artifact ownership: {bad_staged}")

    official_hits = _scan_official_fetches(active)
    allowed_fetch_services = {str(value) for value in ownership.get("official_fetch_allowed_services") or []}
    forbidden_fetches = {
        service: modules
        for service, modules in official_hits.items()
        if service not in allowed_fetch_services
    }
    if forbidden_fetches:
        errors.append(f"Official FPL fetch detected outside declared owner/exception services: {forbidden_fetches}")
    transitional_fetches = {
        service: modules
        for service, modules in official_hits.items()
        if service in allowed_fetch_services and service != "official_snapshot"
    }
    if transitional_fetches:
        warnings.append(f"declared non-snapshot Official fetch exceptions remain: {transitional_fetches}")

    status = "PASS" if not errors else "FAIL"
    result = {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "responsibilities": len(responsibilities),
        "shared_primitives": len(primitive_rows),
        "framework_counts": framework_counts,
        "service_count": len(services),
        "multiwriter_artifacts": {
            artifact: sorted(owners)
            for artifact, owners in writers.items()
            if len(owners) > 1
        },
        "official_fetch_services": official_hits,
        "legacy_registry_references": legacy_registry_refs,
        "policy": ownership.get("policy") or {},
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
