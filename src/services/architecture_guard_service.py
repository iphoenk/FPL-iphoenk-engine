from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from functools import lru_cache
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
MOVING_OPERATIONAL_SYMBOLS = {"CURRENT_GW", "CURRENT_SEASON", "CURRENT_DEADLINE", "SOURCE_COMMIT", "RELEASE_VERSION"}
REQUIRED_CAPABILITIES = {
    "OFFICIAL_PUBLIC_ACQUISITION",
    "AUTHENTICATED_PERSONAL_STATE",
    "PHASE_GW_DEADLINE_AUTHORITY",
    "SUBMITTED_LIVE_STATE",
    "IDENTITY_RESOLVER",
    "HISTORICAL_PRIORS",
    "ADVANCED_STATS",
    "XMINS_START_DNP",
    "XPTS",
    "OPPONENT_MODEL",
    "TACTICAL_SYSTEM_FIT",
    "COMPETITIVE_LOAD",
    "SET_PIECES_PENALTIES",
    "PRICE_SELL_VALUE_AFFORDABILITY",
    "WATCHLIST_DISCOVERY",
    "OWNED_VS_CHALLENGER_COMPARATOR",
    "PACKAGE_OPTIMIZER",
    "XI_BENCH",
    "CAPTAINCY",
    "CHIP",
    "EXTERNAL_CONSENSUS",
    "VALIDATION_CALIBRATION",
    "LEGALITY_RULES",
    "REPORTING_SERVING",
    "BASE_PREDICTION_CACHE",
    "DECISION_ARTIFACT_CACHE",
    "HEALTH_TELEMETRY",
    "SCHEDULING",
}
VALID_OVERLAP_ACTIONS = {
    "KEEP_CANONICAL",
    "MERGE_INTO_CANONICAL",
    "RETIRE_LEGACY",
    "READ_ONLY_ALIAS_REQUIRED",
    "NO_ACTION",
}
CANONICAL_RULE_MODULE = ROOT / "src/engines/fpl_rules_2026.py"
RAW_SNAPSHOT_MODULE = ROOT / "src/services/raw_snapshot_service.py"
OFFICIAL_CLIENT_MODULE = ROOT / "src/sources/official_fpl.py"
BACKTEST_STORE_MODULE = ROOT / "src/engines/v4_backtest_store.py"
RECONCILIATION_MODULE = ROOT / "src/engines/v4_reconciliation_truth.py"
LEGACY_ENGINE_MODULE = ROOT / "src/engine.py"
REPORT_GOVERNANCE_MODULE = ROOT / "src/engines/v4_checkpoint_governance.py"
SERVING_MODULE = ROOT / "src/engines/v4_serving_contract.py"
REFERENCE_READ_ONLY_MODULES = (
    ROOT / "src/engines/v4_wc_package_audit.py",
    ROOT / "src/engines/v4_lineup_optimizer.py",
)
RELEASE_MODULE = ROOT / "src/release.py"
SKIP_DUP_FN_NAMES = {"main", "run", "cli", "_f", "check", "write", "load", "dump"}
ATTESTATION_PATH = CONFIG / "architecture_guard_attestation.json"
ATTESTATION_SCHEMA_VERSION = 1
ATTESTED_CONFIG_PATHS = (
    CONFIG / "service_registry.json",
    CONFIG / "service_contract_registry.json",
    CONFIG / "dss_core_registry.json",
    CONFIG / "dss_extension_registry.json",
    CONFIG / "enhancement_layers_registry.json",
    CONFIG / "gate0_registry.json",
    CONFIG / "architecture_ownership_registry.json",
    CONFIG / "release_manifest.json",
    CONFIG / "runtime_artifact_policy.json",
    CONFIG / "intelligence/owned_challenger_decision_v4.json",
    CONFIG / "optimizer_equivalence_registry.json",
    CONFIG / "intelligence/full_universe_package_search.json",
)
ATTESTED_WORKFLOW_PATHS = (
    ROOT / ".github/workflows/fpl-engine.yml",
    ROOT / ".github/workflows/fpl-engine-recovery.yml",
    ROOT / ".github/workflows/fpl-engine-core.yml",
)


def _unique(values):
    values = [str(value) for value in values if value is not None]
    duplicates = sorted(key for key, count in Counter(values).items() if count > 1)
    return len(values) == len(set(values)), duplicates


def _attestation_inputs() -> tuple[Path, ...]:
    paths = list((ROOT / "src").rglob("*.py"))
    paths.extend(ATTESTED_CONFIG_PATHS)
    paths.extend(ATTESTED_WORKFLOW_PATHS)
    return tuple(sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix()))


def repository_fingerprint() -> str:
    """Cryptographically bind the build-time guard result to every governed byte."""
    digest = hashlib.sha256()
    for path in _attestation_inputs():
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _attested_result() -> dict | None:
    attestation = read_json(ATTESTATION_PATH, {})
    if attestation.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        return None
    if attestation.get("release") != RELEASE_VERSION:
        return None
    if attestation.get("fingerprint") != repository_fingerprint():
        return None
    result = attestation.get("result")
    if not isinstance(result, dict) or result.get("status") != "PASS":
        return None
    checks = result.get("checks") or {}
    if not checks or not all(isinstance(row, dict) and row.get("pass") is True for row in checks.values()):
        return None
    return result


@lru_cache(maxsize=None)
def _text(path: Path) -> str:
    """Read immutable repository source once during a single guard invocation."""
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _tree(path: Path) -> ast.Module:
    """Parse each immutable Python source at most once per guard invocation."""
    return ast.parse(_text(path))


@lru_cache(maxsize=None)
def _analysis(path: Path) -> dict[str, frozenset[str]]:
    """Derive common AST facts in one walk per immutable source file."""
    tree = _tree(path)
    assignment_names: set[str] = set()
    called_names: set[str] = set()
    imported: set[str] = set()
    top_level_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assignment_names.add(target.id)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return {
        "assignments": frozenset(assignment_names),
        "top_level_functions": frozenset(top_level_functions),
        "called_names": frozenset(called_names),
        "imports": frozenset(imported),
    }


def _assignment_names(path: Path) -> set[str]:
    return set(_analysis(path)["assignments"])


def _top_level_functions(path: Path) -> set[str]:
    return set(_analysis(path)["top_level_functions"])


def _called_names(path: Path) -> set[str]:
    return set(_analysis(path)["called_names"])


def _imports(path: Path) -> set[str]:
    return set(_analysis(path)["imports"])


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
        text = _text(path)
        if "src.sources.official_fpl" in imported or "fantasy.premierleague.com/api/" in text:
            violations.append(str(path.relative_to(ROOT)))
    return violations


def _moving_operational_literal_violations() -> list[dict]:
    violations: list[dict] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.resolve() in {GUARD_PATH, RELEASE_MODULE.resolve()}:
            continue
        overlap = sorted(_assignment_names(path) & MOVING_OPERATIONAL_SYMBOLS)
        if overlap:
            violations.append({"file": str(path.relative_to(ROOT)), "symbols": overlap})
    return violations


def run(*, force_full_scan: bool = False) -> dict:
    if not force_full_scan:
        attested = _attested_result()
        if attested is not None:
            atomic_json(OUT, attested)
            print(json.dumps({
                "service": "architecture_guard",
                "status": attested["status"],
                "checks": {name: row["pass"] for name, row in (attested.get("checks") or {}).items()},
                "failed_detail": {},
                "attestation": "CONTENT_ADDRESS_MATCH",
            }, ensure_ascii=False))
            return attested

    # Repository source can never become stale inside one guard run, but clear the
    # memoized source/AST view before every invocation so a subsequent invocation
    # still observes any real checkout/source change.
    _analysis.cache_clear()
    _tree.cache_clear()
    _text.cache_clear()

    services = read_json(CONFIG / "service_registry.json", {})
    contracts = read_json(CONFIG / "service_contract_registry.json", {})
    core = read_json(CONFIG / "dss_core_registry.json", {})
    ext = read_json(CONFIG / "dss_extension_registry.json", {})
    enh = read_json(CONFIG / "enhancement_layers_registry.json", {})
    gate = read_json(CONFIG / "gate0_registry.json", {})
    ownership = read_json(CONFIG / "architecture_ownership_registry.json", {})
    release = read_json(CONFIG / "release_manifest.json", {})
    challenger_policy = read_json(CONFIG / "intelligence/owned_challenger_decision_v4.json", {})
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

    matrix = list(ownership.get("capability_matrix") or [])
    capability_ids = [row.get("capability") for row in matrix]
    matrix_unique, matrix_duplicates = _unique(capability_ids)
    missing_capabilities = sorted(REQUIRED_CAPABILITIES - set(capability_ids))
    missing_fields = []
    invalid_actions = []
    for row in matrix:
        capability = row.get("capability")
        required = ("current_owner", "input_contract", "output_artifact", "consumers", "duplicates_overlap", "action")
        missing = [field for field in required if not row.get(field)]
        if missing:
            missing_fields.append({"capability": capability, "fields": missing})
        if row.get("action") not in VALID_OVERLAP_ACTIONS:
            invalid_actions.append({"capability": capability, "action": row.get("action")})
    checks["capability_matrix_unique"] = (matrix_unique, matrix_duplicates)
    checks["capability_matrix_required_coverage"] = (not missing_capabilities, missing_capabilities)
    checks["capability_matrix_contract_complete"] = (not missing_fields, missing_fields)
    checks["capability_matrix_overlap_actions_governed"] = (not invalid_actions, invalid_actions)

    optimization_row = next((row for row in service_rows if row.get("id") == "optimization"), {})
    challenger_contract = contract_specs.get("owned_challenger_decision") or {}
    challenger_responsibility = next((row for row in responsibilities if row.get("id") == "OWNED_CHALLENGER_EVIDENCE"), {})
    challenger_authority_ok = (
        challenger_policy.get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"
        and (challenger_policy.get("governance") or {}).get("canonical_decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"
        and "owned_challenger_decision" in (optimization_row.get("produces") or [])
        and challenger_contract.get("path") == "data/owned_challenger_decision_v4.json"
        and (challenger_contract.get("equals") or {}).get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"
        and challenger_responsibility.get("owner") == "optimization"
        and challenger_responsibility.get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"
    )
    checks["owned_challenger_single_decision_authority"] = (
        challenger_authority_ok,
        [] if challenger_authority_ok else [{
            "policy": challenger_policy.get("decision_authority"),
            "service_produces": optimization_row.get("produces") or [],
            "contract": challenger_contract,
            "responsibility": challenger_responsibility,
        }],
    )

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

    raw_text = _text(RAW_SNAPSHOT_MODULE)
    raw_uses_canonical_legality = "squad_legality_checks" in raw_text
    raw_redefined_rules = sorted(_assignment_names(RAW_SNAPSHOT_MODULE) & {"POSITION_COUNTS", "MAX_PER_CLUB", "SQUAD_SIZE"})
    raw_uses_canonical_legality = raw_uses_canonical_legality and not raw_redefined_rules
    checks["raw_snapshot_reuses_canonical_legality"] = (
        raw_uses_canonical_legality,
        [] if raw_uses_canonical_legality else raw_redefined_rules or ["squad_legality_checks missing"],
    )

    report_calls = _called_names(REPORT_GOVERNANCE_MODULE)
    serving_imports = _imports(SERVING_MODULE)
    serving_text = _text(SERVING_MODULE)
    forbidden_serving_imports = sorted(module for module in serving_imports if module.startswith("src.sources.official_fpl") or module in {
        "src.models.v4_prediction",
        "src.engines.v4_lineup_optimizer",
        "src.engines.v4_wc_optimizer",
        "src.engines.v4_wc_package_audit_fast",
        "src.engines.v4_decision_arbitration",
    })
    reporting_ok = "resolve_decision" not in report_calls and not forbidden_serving_imports and "fantasy.premierleague.com/api/" not in serving_text
    checks["reporting_composition_only"] = (
        reporting_ok,
        [] if reporting_ok else [{"governance_forbidden_calls": sorted(report_calls & {"resolve_decision"}), "serving_forbidden_imports": forbidden_serving_imports}],
    )

    reference_writer_violations = [
        str(path.relative_to(ROOT))
        for path in REFERENCE_READ_ONLY_MODULES
        if "atomic_json(" in _text(path)
    ]
    checks["reference_modules_read_only"] = (
        not reference_writer_violations, reference_writer_violations
    )

    moving_literals = _moving_operational_literal_violations()
    checks["moving_operational_identity_single_owner"] = (not moving_literals, moving_literals)

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

    registries = release.get("registries") or {}
    release_ok = (
        release.get("release") == RELEASE_VERSION == services.get("architecture_version") == ownership.get("release")
        and registries.get("services") == services.get("registry")
        and registries.get("contracts") == contracts.get("registry")
        and registries.get("ownership") == ownership.get("registry")
        and registries.get("owned_challenger_policy") == challenger_policy.get("registry")
    )
    checks["release_single_source_coherent"] = (
        release_ok,
        [] if release_ok else [{"manifest": release.get("release"), "runtime": RELEASE_VERSION, "service_release": services.get("architecture_version"), "ownership_release": ownership.get("release"), "registry_manifest": registries, "service_registry": services.get("registry"), "contract_registry": contracts.get("registry"), "ownership_registry": ownership.get("registry")}],
    )

    normalized = {name: {"pass": bool(value[0]), "detail": value[1]} for name, value in checks.items()}
    passed = all(row["pass"] for row in normalized.values())
    out = {
        "schema_version": 497,
        "release": RELEASE_VERSION,
        "service": "architecture_guard",
        "status": "PASS" if passed else "FAIL",
        "checks": normalized,
        "ownership_matrix": matrix,
        "guardrails": {
            "one_owner_per_artifact": True,
            "one_owner_per_rule": True,
            "shared_primitives_reused_not_reimplemented": True,
            "official_fpl_single_acquisition_owner": True,
            "reconciliation_single_owner": True,
            "legacy_entrypoint_adapter_only": True,
            "reusable_workflow_single_pipeline": True,
            "audit_first_capability_matrix_enforced": True,
            "reporting_composition_only": True,
            "moving_operational_identity_single_owner": True,
            "owned_challenger_single_decision_authority": True,
            "reference_modules_read_only": True,
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
