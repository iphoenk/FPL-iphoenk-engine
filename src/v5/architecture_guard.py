from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.v5.config_cache import ROOT, load_json_config
from src.v5.module_registry import module_specs
from src.v5.service_registry import module_owners, service_specs, validate_registry

CONFIG = "config/v5_architecture_ownership_registry.json"
_SELF = Path(__file__).resolve()


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if data.get("contract") != "V5_ARCHITECTURE_OWNERSHIP_V1":
        raise RuntimeError("invalid V5 architecture ownership contract")
    return data


def _runtime_python_files() -> list[Path]:
    return [path for path in sorted((ROOT / "src/v5").rglob("*.py")) if path.resolve() != _SELF]


def _unique(values: list[Any]) -> tuple[bool, list[str]]:
    normalized = [str(value) for value in values if value is not None]
    duplicates = sorted(key for key, count in Counter(normalized).items() if count > 1)
    return not duplicates, duplicates


def _strict_json_duplicates(path: Path) -> list[str]:
    duplicates: list[str] = []

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        counts = Counter(key for key, _value in pairs)
        duplicates.extend(sorted(key for key, count in counts.items() if count > 1))
        return dict(pairs)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    return sorted(set(duplicates))


def _json_registry_duplicate_keys(scope: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for pattern in scope.get("json_registry_globs") or []:
        for path in sorted(ROOT.glob(str(pattern))):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            duplicate_keys = _strict_json_duplicates(path)
            if duplicate_keys:
                rows.append({"file": str(path.relative_to(ROOT)), "keys": duplicate_keys})
    return rows


def _assignment_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _canonical_rule_redefinitions(scope: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = {str(value) for value in scope.get("canonical_rule_symbols") or []}
    rows: list[dict[str, Any]] = []
    for path in _runtime_python_files():
        overlap = sorted(_assignment_names(path) & canonical)
        if overlap:
            rows.append({"file": str(path.relative_to(ROOT)), "symbols": overlap})
    return rows


def _function_clones(scope: dict[str, Any]) -> list[dict[str, str]]:
    minimum_nodes = max(1, int(scope.get("exact_clone_min_ast_nodes") or 40))
    ignored = {str(value) for value in scope.get("exact_clone_ignored_function_names") or []}
    seen: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    for path in _runtime_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in ignored:
                continue
            if sum(1 for _ in ast.walk(node)) < minimum_nodes:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            current = f"{path.relative_to(ROOT)}:{node.name}"
            prior = seen.get(digest)
            if prior and prior != current:
                duplicates.append({"first": prior, "second": current})
            else:
                seen[digest] = current
    return duplicates


def _official_fpl_fetch_violations(scope: dict[str, Any]) -> list[dict[str, str]]:
    public_owner = str(scope.get("official_public_network_owner") or "")
    public_callers = {str(value) for value in scope.get("official_public_fetch_callers") or []}
    auth_owner = str(scope.get("official_authenticated_network_owner") or "")
    auth_callers = {str(value) for value in scope.get("official_authenticated_fetch_callers") or []}
    violations: list[dict[str, str]] = []

    for path in _runtime_python_files():
        relative = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        if "fantasy.premierleague.com/api" in text and relative not in {public_owner, auth_owner}:
            violations.append({"file": relative, "reason": "literal Official FPL API endpoint outside network owner"})

        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.v5.public_api":
                imported = {alias.name for alias in node.names}
                if imported & {"fetch_many", "get", "_get_path"} and relative not in public_callers:
                    violations.append({"file": relative, "reason": "Official public fetch call imported outside ingestion owner"})
            if isinstance(node, ast.ImportFrom) and node.module == "src.v5.official_auth":
                imported = {alias.name for alias in node.names}
                if "safe_get" in imported and relative not in auth_callers:
                    violations.append({"file": relative, "reason": "authenticated Official fetch call imported outside authenticated acquisition owner"})
    return violations


def _cross_service_import_violations(scope: dict[str, Any]) -> list[dict[str, str]]:
    allowed = {
        (str(pair[0]), str(pair[1]))
        for pair in scope.get("allowed_service_import_pairs") or []
        if isinstance(pair, list) and len(pair) == 2
    }
    violations: list[dict[str, str]] = []
    for path in sorted((ROOT / "src/v5/services").glob("*.py")):
        relative = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src.v5.services.") and not alias.name.endswith(".common"):
                        if (relative, alias.name) not in allowed:
                            violations.append({"file": relative, "import": alias.name})
                continue
            if module and module.startswith("src.v5.services.") and not module.endswith(".common"):
                if (relative, module) not in allowed:
                    violations.append({"file": relative, "import": module})
    return violations


def _hardcoded_service_topology(scope: dict[str, Any]) -> list[dict[str, Any]]:
    bounds = scope.get("service_port_range") or [8100, 8199]
    low, high = int(bounds[0]), int(bounds[1])
    violations: list[dict[str, Any]] = []
    for path in _runtime_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int) and low <= node.value <= high:
                violations.append({"file": str(path.relative_to(ROOT)), "literal": node.value})
    return violations


def _dss_registry_ids() -> tuple[list[str], dict[str, list[str]]]:
    files = {
        "dss_core": "config/dss_core_registry.json",
        "dss_extension": "config/dss_extension_registry.json",
        "enhancement": "config/enhancement_layers_registry.json",
        "gate0": "config/gate0_registry.json",
    }
    all_ids: list[str] = []
    by_registry: dict[str, list[str]] = {}
    for namespace, config in files.items():
        data = load_json_config(config)
        rows = data.get("modules") or data.get("layers") or data.get("checks") or []
        ids = [str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id") is not None]
        by_registry[namespace] = ids
        all_ids.extend(ids)
    return all_ids, by_registry


def _module_entrypoint_cross_owner_conflicts() -> list[dict[str, Any]]:
    owners = module_owners()
    entrypoints: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for spec in module_specs():
        entrypoints[str(spec.entrypoint)].append((spec.name, owners.get(spec.name, "")))
    conflicts: list[dict[str, Any]] = []
    for entrypoint, rows in sorted(entrypoints.items()):
        service_owners = sorted({owner for _module, owner in rows if owner})
        if len(service_owners) > 1:
            conflicts.append(
                {
                    "entrypoint": entrypoint,
                    "owners": service_owners,
                    "modules": sorted(module for module, _owner in rows),
                }
            )
    return conflicts


def run_audit() -> dict[str, Any]:
    cfg = _cfg()
    scope = cfg.get("guard_scope") if isinstance(cfg.get("guard_scope"), dict) else {}
    checks: dict[str, tuple[bool, Any]] = {}

    service_rows = list(service_specs())
    service_ids = [row.service_id for row in service_rows]
    registry_errors = validate_registry()
    checks["service_registry_valid"] = (not registry_errors, registry_errors)
    checks["unique_service_ids"] = _unique(service_ids)
    checks["unique_service_ports"] = _unique([row.port for row in service_rows])
    checks["unique_bounded_contexts"] = _unique([row.bounded_context for row in service_rows])
    checks["unique_service_handlers"] = _unique([row.handler for row in service_rows])

    modules = list(module_specs())
    checks["unique_module_ids"] = _unique([row.name for row in modules])
    entrypoint_conflicts = _module_entrypoint_cross_owner_conflicts()
    checks["module_entrypoints_do_not_cross_owners"] = (not entrypoint_conflicts, entrypoint_conflicts)

    ownership = cfg.get("responsibilities") or []
    primitives = cfg.get("shared_primitives") or []
    checks["unique_responsibility_ids"] = _unique([row.get("id") for row in ownership if isinstance(row, dict)])
    checks["unique_shared_primitive_ids"] = _unique([row.get("id") for row in primitives if isinstance(row, dict)])
    unknown_owners = sorted(
        {
            str(row.get("owner"))
            for row in [*ownership, *primitives]
            if isinstance(row, dict) and str(row.get("owner")) not in set(service_ids)
        }
    )
    checks["ownership_references_registered_services"] = (not unknown_owners, unknown_owners)

    orchestrator = load_json_config("config/v5_orchestrator_registry.json")
    routes = orchestrator.get("routing") if isinstance(orchestrator.get("routing"), dict) else {}
    unknown_route_services = sorted(
        {str(row.get("service")) for row in routes.values() if isinstance(row, dict) and str(row.get("service")) not in set(service_ids)}
    )
    checks["routes_reference_registered_services"] = (not unknown_route_services, unknown_route_services)
    targets = [f"{row.get('service')}.{row.get('operation')}" for row in routes.values() if isinstance(row, dict)]
    allowed_aliases = {str(value) for value in scope.get("allowed_route_target_aliases") or []}
    _target_ok, target_dupes = _unique(targets)
    target_dupes = [value for value in target_dupes if value not in allowed_aliases]
    checks["unique_route_targets"] = (not target_dupes, target_dupes)

    artifact_mapping = orchestrator.get("artifact_mapping") if isinstance(orchestrator.get("artifact_mapping"), dict) else {}
    checks["unique_orchestrator_artifact_targets"] = _unique(list(artifact_mapping.values()))
    persistence = load_json_config("config/v5_persistence_registry.json")
    persistent_artifacts = persistence.get("artifacts") if isinstance(persistence.get("artifacts"), dict) else {}
    checks["unique_persistence_paths"] = _unique(list(persistent_artifacts.values()))
    unknown_artifacts = sorted(set(str(value) for value in artifact_mapping.values()) - set(str(key) for key in persistent_artifacts))
    checks["orchestrator_artifacts_registered_for_persistence"] = (not unknown_artifacts, unknown_artifacts)

    payloads = load_json_config("config/v5_payload_contract_registry.json")
    contracts = payloads.get("contracts") if isinstance(payloads.get("contracts"), dict) else {}
    payload_owner_errors: list[dict[str, str]] = []
    for contract_id, row in contracts.items():
        owner = str((row or {}).get("owner") or "") if isinstance(row, dict) else ""
        prefix = str(contract_id).split(".", 1)[0]
        if owner not in set(service_ids) or owner != prefix:
            payload_owner_errors.append({"contract": str(contract_id), "owner": owner, "expected": prefix})
    checks["payload_contract_owner_matches_target_service"] = (not payload_owner_errors, payload_owner_errors)

    dss_ids, dss_by_registry = _dss_registry_ids()
    dss_ok, dss_duplicates = _unique(dss_ids)
    checks["unique_dss_enhancement_gate_ids"] = (dss_ok, {"duplicates": dss_duplicates, "registries": dss_by_registry})

    json_duplicates = _json_registry_duplicate_keys(scope)
    checks["no_duplicate_json_registry_keys"] = (not json_duplicates, json_duplicates)

    rule_redefinitions = _canonical_rule_redefinitions(scope)
    checks["canonical_rules_single_owner"] = (not rule_redefinitions, rule_redefinitions)

    official_fetch = _official_fpl_fetch_violations(scope)
    checks["official_fpl_fetch_single_bounded_context_owner"] = (not official_fetch, official_fetch)

    cross_service = _cross_service_import_violations(scope)
    checks["no_direct_cross_service_business_imports"] = (not cross_service, cross_service)

    hardcoded_topology = _hardcoded_service_topology(scope)
    checks["no_hardcoded_service_ports_in_runtime_code"] = (not hardcoded_topology, hardcoded_topology)

    clones = _function_clones(scope)
    checks["no_exact_nontrivial_function_clones"] = (not clones, clones)

    normalized = {
        name: {"pass": bool(result[0]), "detail": result[1]}
        for name, result in checks.items()
    }
    passed = all(row["pass"] for row in normalized.values())
    return {
        "schema_version": 2,
        "contract": cfg.get("contract"),
        "service": "architecture_guard",
        "status": "PASS" if passed else "FAIL",
        "checks": normalized,
        "guardrails": {
            "one_owner_per_business_responsibility": True,
            "one_owner_per_module": True,
            "shared_primitives_reused_not_reimplemented": True,
            "duplicate_ids_fail_closed": True,
            "duplicate_output_paths_fail_closed": True,
            "official_fpl_acquisition_single_bounded_context": True,
            "canonical_rules_single_owner": True,
            "hardcoded_service_topology_forbidden": True,
            "exact_nontrivial_function_clones_forbidden": True,
            "user_hot_path_dependency": False,
        },
    }
