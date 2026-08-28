from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

from src.release import RELEASE_VERSION
from src.utils import CONFIG, DATA, atomic_json, read_json

ROOT = Path(__file__).resolve().parents[2]
OUT = DATA / "architecture_ownership_v4.json"
GUARD_PATH = Path(__file__).resolve()
CANONICAL_SYMBOLS = {
    "SCORING",
    "DEFCON",
    "CHIPS",
    "SQUAD_SIZE",
    "POSITION_COUNTS",
    "POSITION_BY_TYPE",
    "BUDGET_TENTHS",
    "MAX_PER_CLUB",
    "LEGAL_FORMATIONS",
    "LEGAL_FORMATION_TUPLES",
}
CANONICAL_RULE_MODULE = ROOT / "src/engines/fpl_rules_2026.py"
RAW_SNAPSHOT_MODULE = ROOT / "src/services/raw_snapshot_service.py"
OFFICIAL_CLIENT_MODULE = ROOT / "src/sources/official_fpl.py"
BACKTEST_STORE_MODULE = ROOT / "src/engines/v4_backtest_store.py"
RECONCILIATION_MODULE = ROOT / "src/engines/v4_reconciliation_truth.py"
LEGACY_ENGINE_MODULE = ROOT / "src/engine.py"
CANONICAL_METRICS_MODULE = ROOT / "src/models/v4_metrics.py"
PROJECTION_COMPAT_MODULE = ROOT / "src/models/projection.py"
GENERIC_OPTIMIZER_MODULE = ROOT / "src/models/optimizer.py"
WC_OPTIMIZER_BASE_MODULE = ROOT / "src/engines/v4_wc_optimizer.py"
WC_OPTIMIZER_OWNER_MODULE = ROOT / "src/engines/v4_wc_optimizer_fast.py"
PACKAGE_AUDIT_BASE_MODULE = ROOT / "src/engines/v4_wc_package_audit.py"
PACKAGE_AUDIT_OWNER_MODULE = ROOT / "src/engines/v4_wc_package_audit_fast.py"
SKIP_DUP_FN_NAMES = {"main", "run", "cli", "_f", "check", "write", "load", "dump"}
GENERIC_METRIC_FUNCTION_NAMES = {
    "mae",
    "mae_values",
    "mae_rows",
    "brier",
    "brier_values",
    "spearman",
    "spearman_values",
    "spearman_rows",
    "spearman_rank",
    "calibration_error",
    "calibration_error_values",
    "calibration_error_rows",
    "rank",
    "rank_values",
}


def _unique(values):
    values = [str(value) for value in values if value is not None]
    duplicates = sorted(key for key, count in Counter(values).items() if count > 1)
    return len(values) == len(set(values)), duplicates


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _assignment_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _top_level_functions(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _duplicate_functions() -> list[dict]:
    seen: dict[str, str] = {}
    duplicates: list[dict] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.resolve() == GUARD_PATH:
            continue
        tree = _tree(path)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in SKIP_DUP_FN_NAMES:
                continue
            size = sum(1 for _ in ast.walk(node))
            if size < 28:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha256(body.encode()).hexdigest()
            prior = seen.get(digest)
            current = f"{path.relative_to(ROOT)}:{node.name}"
            if prior and prior != current:
                duplicates.append({"first": prior, "second": current})
            else:
                seen[digest] = current
    return duplicates


def _official_fetch_violations() -> list[str]:
    allowed = {RAW_SNAPSHOT_MODULE.resolve(), OFFICIAL_CLIENT_MODULE.resolve()}
    violations: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        resolved = path.resolve()
        if resolved == GUARD_PATH or resolved in allowed:
            continue
        imported = _imports(path)
        text = path.read_text(encoding="utf-8")
        if "src.sources.official_fpl" in imported or "fantasy.premierleague.com/api/" in text:
            violations.append(str(path.relative_to(ROOT)))
    return violations


def _metric_owner_violations() -> list[dict]:
    violations: list[dict] = []
    canonical = CANONICAL_METRICS_MODULE.resolve()
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.resolve() in {canonical, GUARD_PATH}:
            continue
        overlap = sorted(_top_level_functions(path) & GENERIC_METRIC_FUNCTION_NAMES)
        if overlap:
            violations.append({"file": str(path.relative_to(ROOT)), "functions": overlap})
    return violations


def _adapter_contracts() -> dict[str, tuple[bool, list | str]]:
    checks: dict[str, tuple[bool, list | str]] = {}

    projection_text = PROJECTION_COMPAT_MODULE.read_text(encoding="utf-8")
    projection_functions = _top_level_functions(PROJECTION_COMPAT_MODULE)
    projection_allowed = {"_compat_context", "xmins_distribution", "simple_xmins", "project_points"}
    projection_ok = (
        projection_functions <= projection_allowed
        and "from src.models.v4_prediction import" in projection_text
        and "project_fixture(" in projection_text
        and "GOAL_PTS =" not in projection_text
        and "CS_PTS =" not in projection_text
        and "interpretable_projection" not in projection_text
    )
    checks["legacy_projection_is_canonical_adapter"] = (
        projection_ok,
        [] if projection_ok else [{"functions": sorted(projection_functions), "allowed": sorted(projection_allowed)}],
    )

    generic_optimizer_text = GENERIC_OPTIMIZER_MODULE.read_text(encoding="utf-8")
    generic_optimizer_functions = _top_level_functions(GENERIC_OPTIMIZER_MODULE)
    optimizer_allowed = {"legal_counts", "score_squad", "evaluate_package"}
    generic_optimizer_ok = (
        generic_optimizer_functions <= optimizer_allowed
        and "squad_shape_is_legal" in generic_optimizer_text
        and "legacy score_squad is non-authoritative" in generic_optimizer_text
        and "legacy evaluate_package is non-authoritative" in generic_optimizer_text
        and "xpts_by_gw" not in generic_optimizer_text
        and "net_gain" not in generic_optimizer_text
    )
    checks["legacy_generic_optimizer_has_no_decision_authority"] = (
        generic_optimizer_ok,
        [] if generic_optimizer_ok else [{"functions": sorted(generic_optimizer_functions)}],
    )

    wc_base = WC_OPTIMIZER_BASE_MODULE.read_text(encoding="utf-8")
    wc_owner = WC_OPTIMIZER_OWNER_MODULE.read_text(encoding="utf-8")
    wc_ok = (
        "from src.engines.v4_wc_optimizer_fast import optimize_squad_fast" in wc_base
        and "return optimize_squad_fast(" in wc_base
        and "from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast" in wc_base
        and "nlargest" not in wc_base
        and "heappush" not in wc_base
        and "def optimize_squad_fast(" in wc_owner
    )
    checks["wc_optimizer_search_single_owner"] = (
        wc_ok,
        [] if wc_ok else ["base optimizer must delegate; exact-fast module must own search"],
    )

    package_base = PACKAGE_AUDIT_BASE_MODULE.read_text(encoding="utf-8")
    package_owner = PACKAGE_AUDIT_OWNER_MODULE.read_text(encoding="utf-8")
    package_ok = (
        "from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast" in package_base
        and "return audit_packages_from_candidates_fast(" in package_base
        and "from itertools import combinations" not in package_base
        and "def _bounded_ins_states" not in package_base
        and "def _candidate_states" not in package_base
        and "def audit_packages_from_candidates_fast(" in package_owner
    )
    checks["package_audit_search_single_owner"] = (
        package_ok,
        [] if package_ok else ["base package audit must delegate; exact-fast module must own search"],
    )
    return checks


def run() -> dict:
    services = read_json(CONFIG / "service_registry.json", {})
    contracts = read_json(CONFIG / "service_contract_registry.json", {})
    core = read_json(CONFIG / "dss_core_registry.json", {})
    ext = read_json(CONFIG / "dss_extension_registry.json", {})
    enh = read_json(CONFIG / "enhancement_layers_registry.json", {})
    gate = read_json(CONFIG / "gate0_registry.json", {})
    ownership = read_json(CONFIG / "architecture_ownership_registry.json", {})
    release = read_json(CONFIG / "release_manifest.json", {})
    checks: dict[str, tuple[bool, list | str]] = {}

    service_rows = services.get("services") or []
    service_ids = [row.get("id") for row in service_rows]
    checks["unique_service_ids"] = _unique(service_ids)
    produced = [name for row in service_rows for name in (row.get("produces") or [])]
    checks["unique_contract_producers"] = _unique(produced)
    contract_specs = contracts.get("contracts") or {}
    contract_paths = [spec.get("path") for spec in contract_specs.values()]
    checks["contract_paths_complete"] = (all(contract_paths), [name for name, spec in contract_specs.items() if not spec.get("path")])
    checks["unique_contract_paths"] = _unique(contract_paths)

    registry_ids = (
        [row.get("id") for row in core.get("modules") or []]
        + [row.get("id") for row in ext.get("modules") or []]
        + [row.get("id") for row in enh.get("layers") or []]
        + [row.get("id") for row in gate.get("checks") or []]
    )
    checks["unique_registry_ids"] = _unique(registry_ids)

    responsibilities = ownership.get("responsibilities") or []
    shared_primitives = ownership.get("shared_primitives") or []
    responsibility_ids = [row.get("id") for row in responsibilities]
    primitive_ids = [row.get("id") for row in shared_primitives]
    checks["unique_responsibility_ids"] = _unique(responsibility_ids)
    checks["unique_shared_primitive_ids"] = _unique(primitive_ids)
    missing_owners = [row.get("id") for row in responsibilities + shared_primitives if not row.get("owner")]
    checks["all_responsibilities_have_one_owner"] = (not missing_owners, missing_owners)

    duplicate_rule_defs = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == CANONICAL_RULE_MODULE or path.resolve() == GUARD_PATH:
            continue
        overlap = sorted(_assignment_names(path) & CANONICAL_SYMBOLS)
        if overlap:
            duplicate_rule_defs.append({"file": str(path.relative_to(ROOT)), "symbols": overlap})
    checks["canonical_rule_definitions_single_owner"] = (not duplicate_rule_defs, duplicate_rule_defs)

    official_fetch_violations = _official_fetch_violations()
    checks["official_fpl_fetch_single_owner"] = (not official_fetch_violations, official_fetch_violations)

    duplicate_functions = _duplicate_functions()
    checks["no_exact_nontrivial_function_clones"] = (not duplicate_functions, duplicate_functions)

    metric_violations = _metric_owner_violations()
    checks["generic_validation_metrics_single_owner"] = (not metric_violations, metric_violations)
    checks.update(_adapter_contracts())

    engine_functions = _top_level_functions(LEGACY_ENGINE_MODULE)
    engine_imports = _imports(LEGACY_ENGINE_MODULE)
    prohibited_engine_imports = sorted(module for module in engine_imports if module in {
        "src.sources.official_fpl",
        "src.engines.v4_runner",
        "src.engines.team_value",
        "src.engines.fpl_legality",
    })
    thin_engine = engine_functions <= {"run", "cli"} and not prohibited_engine_imports
    checks["legacy_engine_is_thin_adapter"] = (
        thin_engine,
        [] if thin_engine else [{"functions": sorted(engine_functions), "prohibited_imports": prohibited_engine_imports}],
    )

    store_functions = _top_level_functions(BACKTEST_STORE_MODULE)
    reconciliation_functions = _top_level_functions(RECONCILIATION_MODULE)
    duplicate_reconciliation = sorted({"actual_by_element", "reconcile_finished_gw"} & store_functions)
    truth_missing = sorted({"actual_by_element", "reconcile_finished_gw"} - reconciliation_functions)
    checks["reconciliation_truth_single_owner"] = (
        not duplicate_reconciliation and not truth_missing,
        [] if not duplicate_reconciliation and not truth_missing else [{"store_duplicates": duplicate_reconciliation, "truth_missing": truth_missing}],
    )

    raw_text = RAW_SNAPSHOT_MODULE.read_text(encoding="utf-8")
    raw_uses_canonical_legality = "squad_legality_checks" in raw_text
    raw_redefined_rules = sorted(_assignment_names(RAW_SNAPSHOT_MODULE) & {"POSITION_COUNTS", "MAX_PER_CLUB", "SQUAD_SIZE"})
    raw_uses_canonical_legality = raw_uses_canonical_legality and not raw_redefined_rules
    checks["raw_snapshot_reuses_canonical_legality"] = (
        raw_uses_canonical_legality,
        [] if raw_uses_canonical_legality else raw_redefined_rules or ["squad_legality_checks missing"],
    )

    main = (ROOT / ".github/workflows/fpl-engine.yml").read_text(encoding="utf-8")
    recovery = (ROOT / ".github/workflows/fpl-engine-recovery.yml").read_text(encoding="utf-8")
    reusable = ROOT / ".github/workflows/fpl-engine-core.yml"
    workflow_ok = (
        reusable.exists()
        and "uses: ./.github/workflows/fpl-engine-core.yml" in main
        and "uses: ./.github/workflows/fpl-engine-core.yml" in recovery
        and "src.services.orchestrator" not in main
        and "src.services.orchestrator" not in recovery
    )
    checks["single_reusable_production_workflow"] = (workflow_ok, [] if workflow_ok else ["main/recovery must call reusable core"])

    release_ok = release.get("release") == RELEASE_VERSION == services.get("architecture_version") == ownership.get("release")
    checks["release_single_source_coherent"] = (
        release_ok,
        [] if release_ok else [release.get("release"), RELEASE_VERSION, services.get("architecture_version"), ownership.get("release")],
    )

    normalized = {name: {"pass": bool(value[0]), "detail": value[1]} for name, value in checks.items()}
    passed = all(row["pass"] for row in normalized.values())
    out = {
        "schema_version": 4962,
        "release": RELEASE_VERSION,
        "service": "architecture_guard",
        "status": "PASS" if passed else "FAIL",
        "checks": normalized,
        "guardrails": {
            "one_owner_per_artifact": True,
            "one_owner_per_rule": True,
            "shared_primitives_reused_not_reimplemented": True,
            "semantic_duplicate_business_logic_blocked": True,
            "compatibility_adapters_have_no_business_authority": True,
            "validation_metrics_single_owner": True,
            "optimizer_search_single_owner": True,
            "package_audit_search_single_owner": True,
            "official_fpl_single_acquisition_owner": True,
            "reconciliation_single_owner": True,
            "legacy_entrypoint_adapter_only": True,
            "reusable_workflow_single_pipeline": True,
        },
    }
    atomic_json(OUT, out)
    failed_detail = {name: row["detail"] for name, row in normalized.items() if not row["pass"]}
    print(json.dumps({
        "service": "architecture_guard",
        "status": out["status"],
        "checks": {name: row["pass"] for name, row in normalized.items()},
        "failed_detail": failed_detail,
    }, ensure_ascii=False))
    if not passed:
        raise SystemExit(2)
    return out


if __name__ == "__main__":
    run()
