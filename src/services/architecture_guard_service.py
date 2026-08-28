from __future__ import annotations
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from src.release import RELEASE_VERSION
from src.utils import CONFIG, DATA, atomic_json, read_json

ROOT = Path(__file__).resolve().parents[2]
OUT = DATA / "architecture_ownership_v4.json"
CANONICAL_SYMBOLS = {"SCORING", "DEFCON", "CHIPS", "POSITION_COUNTS", "BUDGET_TENTHS", "MAX_PER_CLUB", "LEGAL_FORMATIONS", "LEGAL_FORMATION_TUPLES"}
CANONICAL_RULE_MODULE = ROOT / "src/engines/fpl_rules_2026.py"
ALLOWED_OFFICIAL_FETCH = {ROOT / "src/services/raw_snapshot_service.py", ROOT / "src/sources/official_fpl.py"}
SKIP_DUP_FN_NAMES = {"main", "run", "_f", "check", "write", "load", "dump"}

def _unique(values):
    values = [str(v) for v in values if v is not None]
    return len(values) == len(set(values)), sorted(k for k, n in Counter(values).items() if n > 1)

def _assignment_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name): names.add(target.id)
    return names

def _duplicate_functions() -> list[dict]:
    seen = {}
    duplicates = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
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

def run() -> dict:
    services = read_json(CONFIG / "service_registry.json", {})
    contracts = read_json(CONFIG / "service_contract_registry.json", {})
    core = read_json(CONFIG / "dss_core_registry.json", {})
    ext = read_json(CONFIG / "dss_extension_registry.json", {})
    enh = read_json(CONFIG / "enhancement_layers_registry.json", {})
    gate = read_json(CONFIG / "gate0_registry.json", {})
    ownership = read_json(CONFIG / "architecture_ownership_registry.json", {})
    release = read_json(CONFIG / "release_manifest.json", {})
    checks = {}

    service_rows = services.get("services") or []
    service_ids = [row.get("id") for row in service_rows]
    checks["unique_service_ids"] = _unique(service_ids)
    produced = [name for row in service_rows for name in (row.get("produces") or [])]
    checks["unique_contract_producers"] = _unique(produced)
    contract_paths = [spec.get("path") for spec in (contracts.get("contracts") or {}).values()]
    checks["unique_contract_paths"] = _unique(contract_paths)

    registry_ids = [row.get("id") for row in core.get("modules") or []] + [row.get("id") for row in ext.get("modules") or []] + [row.get("id") for row in enh.get("layers") or []] + [row.get("id") for row in gate.get("checks") or []]
    checks["unique_registry_ids"] = _unique(registry_ids)

    responsibility_ids = [row.get("id") for row in ownership.get("responsibilities") or []]
    primitive_ids = [row.get("id") for row in ownership.get("shared_primitives") or []]
    checks["unique_responsibility_ids"] = _unique(responsibility_ids)
    checks["unique_shared_primitive_ids"] = _unique(primitive_ids)

    duplicate_rule_defs = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == CANONICAL_RULE_MODULE:
            continue
        overlap = sorted(_assignment_names(path) & CANONICAL_SYMBOLS)
        if overlap:
            duplicate_rule_defs.append({"file": str(path.relative_to(ROOT)), "symbols": overlap})
    checks["canonical_rule_definitions_single_owner"] = (not duplicate_rule_defs, duplicate_rule_defs)

    official_fetch_violations = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path in ALLOWED_OFFICIAL_FETCH:
            continue
        text = path.read_text(encoding="utf-8")
        if "fantasy.premierleague.com/api" in text or "src.sources.official_fpl" in text:
            official_fetch_violations.append(str(path.relative_to(ROOT)))
    checks["official_fpl_fetch_single_owner"] = (not official_fetch_violations, official_fetch_violations)

    duplicate_functions = _duplicate_functions()
    checks["no_exact_nontrivial_function_clones"] = (not duplicate_functions, duplicate_functions)

    main = (ROOT / ".github/workflows/fpl-engine.yml").read_text(encoding="utf-8")
    recovery = (ROOT / ".github/workflows/fpl-engine-recovery.yml").read_text(encoding="utf-8")
    reusable = ROOT / ".github/workflows/fpl-engine-core.yml"
    workflow_ok = reusable.exists() and "uses: ./.github/workflows/fpl-engine-core.yml" in main and "uses: ./.github/workflows/fpl-engine-core.yml" in recovery and "src.services.orchestrator" not in main and "src.services.orchestrator" not in recovery
    checks["single_reusable_production_workflow"] = (workflow_ok, [] if workflow_ok else ["main/recovery must call reusable core"])

    release_ok = release.get("release") == RELEASE_VERSION == services.get("architecture_version") == ownership.get("release")
    checks["release_single_source_coherent"] = (release_ok, [] if release_ok else [release.get("release"), RELEASE_VERSION, services.get("architecture_version"), ownership.get("release")])

    normalized = {name: {"pass": bool(value[0]), "detail": value[1]} for name, value in checks.items()}
    passed = all(row["pass"] for row in normalized.values())
    out = {"schema_version": 496, "release": RELEASE_VERSION, "service": "architecture_guard", "status": "PASS" if passed else "FAIL", "checks": normalized, "guardrails": {"one_owner_per_artifact": True, "one_owner_per_rule": True, "shared_primitives_reused_not_reimplemented": True, "official_fpl_single_acquisition_owner": True, "reusable_workflow_single_pipeline": True}}
    atomic_json(OUT, out)
    print(json.dumps({"service": "architecture_guard", "status": out["status"], "checks": {k:v["pass"] for k,v in normalized.items()}}, ensure_ascii=False))
    if not passed:
        raise SystemExit(2)
    return out

if __name__ == "__main__": run()
