from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.utils import ROOT

OWNERSHIP_PATH = ROOT / "config" / "v3_architecture_ownership_registry.json"
SERVICE_PATH = ROOT / "config" / "v3_service_registry.json"
INTERACTIVE_SERVICE_PATH = ROOT / "config" / "runtime" / "interactive_service_registry.json"
REC_PATH = ROOT / "config" / "rec_registry.json"
IMPLEMENTATION_STATUS_PATH = ROOT / "IMPLEMENTATION_STATUS.json"
OFFICIAL_FIRST_PATH = ROOT / "config" / "sources" / "official_first_coverage.json"
OFFICIAL_ENDPOINT_OWNERSHIP_PATH = ROOT / "config" / "sources" / "official_endpoint_ownership.json"
OFFICIAL_FPL_MODULE = "src.sources.official_fpl"
CORE_OFFICIAL_ENDPOINTS = {"bootstrap-static/", "fixtures/", "event-status/"}
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


def _interactive_modules(services: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for service, spec in services.items():
        module = str(spec.get("module") or "")
        result[service] = {module} if module else set()
    return result


def _artifact_writers(services: dict[str, Any]) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = defaultdict(set)
    for service, spec in services.items():
        for artifact in spec.get("artifacts") or []:
            writers[str(artifact)].add(service)
    return writers


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _static_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left, constants)
        right = _static_string(node.right, constants)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _ast_official_fetch_calls(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_aliases: set[str] = {OFFICIAL_FPL_MODULE}
    direct_get_json_aliases: set[str] = set()
    constants: dict[str, str] = {}
    wildcard_import = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == OFFICIAL_FPL_MODULE:
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "src.sources":
                for alias in node.names:
                    if alias.name == "official_fpl":
                        module_aliases.add(alias.asname or alias.name)
            elif node.module == OFFICIAL_FPL_MODULE:
                for alias in node.names:
                    if alias.name == "*":
                        wildcard_import = True
                    elif alias.name == "get_json":
                        direct_get_json_aliases.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            static = _static_string(value, constants)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if static is not None:
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = static

    if wildcard_import:
        raise RuntimeError(f"wildcard import from {OFFICIAL_FPL_MODULE} is forbidden in active module: {path}")

    def is_official_get_json_target(name: str | None) -> bool:
        if not name:
            return False
        if name in direct_get_json_aliases:
            return True
        if name == f"{OFFICIAL_FPL_MODULE}.get_json":
            return True
        return any(name == f"{alias}.get_json" for alias in module_aliases)

    # Resolve simple function aliases such as fetch = official_fpl.get_json.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        if not is_official_get_json_target(_dotted_name(node.value)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                direct_get_json_aliases.add(target.id)

    calls: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_official_get_json_target(_dotted_name(node.func)):
            continue
        endpoint = _static_string(node.args[0], constants) if node.args else None
        calls.append({
            "line": int(getattr(node, "lineno", 0) or 0),
            "endpoint": endpoint if endpoint is not None else "<dynamic>",
            "target": _dotted_name(node.func),
        })
    return sorted(calls, key=lambda row: (int(row["line"]), str(row["target"])))


def _scan_official_fetch_calls(active: dict[str, set[str]]) -> dict[str, list[dict[str, Any]]]:
    findings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for service, modules in active.items():
        for module in sorted(modules):
            path = _module_path(module)
            if not path.is_file():
                continue
            for call in _ast_official_fetch_calls(path):
                findings[service].append({"module": module, **call})
    return {service: rows for service, rows in sorted(findings.items())}


def _official_fetch_services(findings: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        service: sorted({str(row.get("module")) for row in rows})
        for service, rows in sorted(findings.items())
        if rows
    }


def _scan_core_refetches(findings: dict[str, list[dict[str, Any]]]) -> list[str]:
    hits: list[str] = []
    for service, calls in findings.items():
        if service == "official_snapshot":
            continue
        for call in calls:
            endpoint = str(call.get("endpoint") or "")
            normalized = endpoint.lstrip("/")
            if normalized in CORE_OFFICIAL_ENDPOINTS:
                hits.append(f"{service}:{call.get('module')}:{call.get('line')}:{normalized}")
    return sorted(hits)


def _validate_official_endpoint_ownership(errors: list[str], service_names: set[str]) -> dict[str, Any]:
    payload = _load(OFFICIAL_ENDPOINT_OWNERSHIP_PATH)
    if payload.get("registry") != "OFFICIAL_ENDPOINT_OWNERSHIP_V1":
        errors.append("unexpected Official endpoint ownership registry")
    rows = list(payload.get("network_purposes") or [])
    ids = [str(row.get("id") or "") for row in rows]
    duplicate_ids = _duplicates(ids)
    if duplicate_ids:
        errors.append(f"duplicate Official network purpose ids: {duplicate_ids}")
    endpoint_families: list[str] = []
    owners: set[str] = set()
    invalid: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row.get("id") or "")
        owner = str(row.get("owner_service") or "")
        scope = str(row.get("scope") or "")
        families = [str(value) for value in row.get("endpoint_families") or []]
        if not rid or not owner or not scope or not families:
            invalid.append(row)
            continue
        if owner not in service_names:
            errors.append(f"Official network purpose {rid} owner service missing: {owner}")
        owners.add(owner)
        endpoint_families.extend(families)
        dup_local = _duplicates(families)
        if dup_local:
            errors.append(f"Official network purpose {rid} duplicate endpoint families: {dup_local}")
    if invalid:
        errors.append(f"invalid Official endpoint ownership rows: {invalid}")
    duplicate_families = _duplicates(endpoint_families)
    if duplicate_families:
        errors.append(f"Official endpoint family owned by multiple network purposes: {duplicate_families}")
    return {
        "registry": payload.get("registry"),
        "network_purpose_count": len(rows),
        "owners": sorted(owners),
        "duplicate_purpose_ids": duplicate_ids,
        "duplicate_endpoint_families": duplicate_families,
    }


def _validate_rec_registry(errors: list[str], service_names: set[str]) -> dict[str, Any]:
    rec = _load(REC_PATH)
    impl = _load(IMPLEMENTATION_STATUS_PATH)
    official = _load(OFFICIAL_FIRST_PATH)
    if rec.get("registry") != "V3_REC_REGISTRY_V1":
        errors.append("unexpected V3 REC registry")
    rows = list(rec.get("records") or [])
    ids = [str(row.get("id") or "") for row in rows]
    dup_ids = _duplicates(ids)
    if dup_ids:
        errors.append(f"duplicate REC ids: {dup_ids}")
    expected = int(rec.get("expected_count") or 0)
    if expected != len(rows):
        errors.append(f"REC expected_count={expected} declared={len(rows)}")

    allowed_non_service = {str(v) for v in rec.get("non_service_owners") or []}
    allowed_relations = {str(v) for v in rec.get("allowed_relations") or []}
    invalid_rows: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row.get("id") or "")
        title = str(row.get("title") or "")
        status = str(row.get("status") or "")
        owner = str(row.get("owner") or "")
        relation = str(row.get("relation") or "")
        if not rid or not title or not status or not owner or relation not in allowed_relations:
            invalid_rows.append(row)
            continue
        if owner not in service_names and owner not in allowed_non_service:
            errors.append(f"REC {rid} owner is neither service nor declared governance owner: {owner}")
        if relation == "EXTENDS_EXISTING_OWNER" and owner not in service_names:
            errors.append(f"REC {rid} EXTENDS_EXISTING_OWNER must point to runtime/interactive service: {owner}")
        if relation == "GOVERNANCE_ONLY" and owner not in allowed_non_service:
            errors.append(f"REC {rid} GOVERNANCE_ONLY must point to declared governance owner: {owner}")
    if invalid_rows:
        errors.append(f"invalid REC rows: {invalid_rows}")

    canonical = {str(row["id"]): row for row in rows if row.get("id")}
    impl_status = impl.get("rec_status") if isinstance(impl.get("rec_status"), dict) else {}
    official_rows = official.get("recommendations") if isinstance(official.get("recommendations"), dict) else {}
    canonical_ids = set(canonical)
    impl_ids = set(map(str, impl_status))
    official_ids = set(map(str, official_rows))
    if impl_ids != canonical_ids:
        errors.append(f"IMPLEMENTATION_STATUS REC set drift: missing={sorted(canonical_ids-impl_ids)} extra={sorted(impl_ids-canonical_ids)}")
    if official_ids != canonical_ids:
        errors.append(f"Official-first REC set drift: missing={sorted(canonical_ids-official_ids)} extra={sorted(official_ids-canonical_ids)}")

    status_drift: dict[str, dict[str, str]] = {}
    for rid, row in canonical.items():
        projected = impl_status.get(rid) if isinstance(impl_status.get(rid), dict) else {}
        canonical_status = str(row.get("status") or "")
        projected_status = str(projected.get("status") or "")
        if canonical_status != projected_status:
            status_drift[rid] = {"canonical": canonical_status, "implementation_status": projected_status}
    if status_drift:
        errors.append(f"REC status projection drift: {status_drift}")

    return {
        "registry": rec.get("registry"),
        "count": len(rows),
        "duplicate_ids": dup_ids,
        "status_projection_sync": not bool(status_drift),
        "official_first_set_sync": official_ids == canonical_ids,
        "implementation_status_set_sync": impl_ids == canonical_ids,
        "governance_owners": sorted(allowed_non_service),
    }


def run() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    ownership = _load(OWNERSHIP_PATH)
    service_registry = _load(SERVICE_PATH)
    interactive_registry = _load(INTERACTIVE_SERVICE_PATH)
    services = service_registry.get("services") or {}
    interactive_services = interactive_registry.get("services") or {}
    if ownership.get("registry") != "V3_ARCHITECTURE_OWNERSHIP_V1":
        errors.append("unexpected V3 architecture ownership registry")
    if interactive_registry.get("registry") != "V3_INTERACTIVE_SERVICES_V1":
        errors.append("unexpected interactive service registry")
    if not isinstance(services, dict) or not services:
        errors.append("V3 service registry has no services")
        services = {}
    if not isinstance(interactive_services, dict) or not interactive_services:
        errors.append("V3 interactive service registry has no services")
        interactive_services = {}
    overlapping_service_names = sorted(set(services) & set(interactive_services))
    if overlapping_service_names:
        errors.append(f"background and interactive service names overlap: {overlapping_service_names}")
    service_names = set(services) | set(interactive_services)

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
        if owner not in service_names:
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
        expected_count = int(payload.get("expected_count") or 0)
        if expected_count and expected_count != len(rows):
            errors.append(f"{name} expected_count={expected_count} declared={len(rows)}")
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
    interactive_active = _interactive_modules(interactive_services)
    combined_active = {**active, **interactive_active}
    compatibility = {str(value) for value in ownership.get("compatibility_only_modules") or []}
    forbidden_active = compatibility | legacy_modules
    active_forbidden: list[str] = []
    module_services: dict[str, set[str]] = defaultdict(set)
    for service, modules in combined_active.items():
        for module in modules:
            module_services[module].add(service)
            if module in forbidden_active:
                active_forbidden.append(f"{service}:{module}")
    if active_forbidden:
        errors.append(f"compatibility/legacy modules active in services: {sorted(active_forbidden)}")
    cross_service_module_duplicates = {module: sorted(owners) for module, owners in module_services.items() if len(owners) > 1}
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
            bad_staged[artifact] = {"actual": sorted(owners), "allowed": sorted(allowed), "final_owner": final_owner}
    if undeclared_multiwriters:
        errors.append(f"undeclared multi-writer artifacts: {undeclared_multiwriters}")
    if bad_staged:
        errors.append(f"invalid staged artifact ownership: {bad_staged}")

    endpoint_state = _validate_official_endpoint_ownership(errors, service_names)
    try:
        official_findings = _scan_official_fetch_calls(combined_active)
    except (SyntaxError, RuntimeError) as exc:
        official_findings = {}
        errors.append(f"Official FPL AST authority scan failed closed: {exc}")
    official_hits = _official_fetch_services(official_findings)
    declared_network_owners = set(endpoint_state.get("owners") or [])
    architecture_allowed = {str(value) for value in ownership.get("official_fetch_allowed_services") or []}
    if architecture_allowed != declared_network_owners:
        errors.append(
            f"Official fetch owner registry drift: architecture={sorted(architecture_allowed)} endpoint_registry={sorted(declared_network_owners)}"
        )
    forbidden_fetches = {service: modules for service, modules in official_hits.items() if service not in declared_network_owners}
    if forbidden_fetches:
        errors.append(f"Official FPL fetch detected outside scoped network owner: {forbidden_fetches}")
    core_refetches = _scan_core_refetches(official_findings)
    if core_refetches:
        errors.append(f"core Official snapshot endpoints refetched downstream: {core_refetches}")

    rec_state = _validate_rec_registry(errors, service_names)
    status = "PASS" if not errors else "FAIL"
    result = {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "responsibilities": len(responsibilities),
        "shared_primitives": len(primitive_rows),
        "framework_counts": framework_counts,
        "rec": rec_state,
        "official_endpoint_ownership": endpoint_state,
        "official_fetch_authority_guard": {
            "scanner": "AST_V1",
            "call_count": sum(len(rows) for rows in official_findings.values()),
            "dynamic_endpoint_call_count": sum(
                1 for rows in official_findings.values() for row in rows if row.get("endpoint") == "<dynamic>"
            ),
        },
        "background_service_count": len(services),
        "interactive_service_count": len(interactive_services),
        "total_bounded_service_count": len(service_names),
        "multiwriter_artifacts": {artifact: sorted(owners) for artifact, owners in writers.items() if len(owners) > 1},
        "official_fetch_services": official_hits,
        "core_official_refetches": core_refetches,
        "legacy_registry_references": legacy_registry_refs,
        "policy": ownership.get("policy") or {},
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()