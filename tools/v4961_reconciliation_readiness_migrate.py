from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


services_path = CONFIG / "service_registry.json"
services = load(services_path)
services["schema_version"] = 10
services["registry"] = "fpl_v4_9_6_microservice_registry_v10"
rows = services["services"]
if not any(row["id"] == "reconciliation_readiness" for row in rows):
    idx = next(i for i, row in enumerate(rows) if row["id"] == "validation_lifecycle") + 1
    rows.insert(idx, {
        "id": "reconciliation_readiness",
        "name": "GW Reconciliation Readiness Audit Service",
        "boundary_state": "INDEPENDENT",
        "module": "src.services.reconciliation_readiness_service",
        "command": ["{python}", "-m", "src.services.reconciliation_readiness_service"],
        "timeout_seconds": 20,
        "depends_on": ["validation_lifecycle", "architecture_guard"],
        "produces": ["reconciliation_readiness"],
        "critical": True,
    })
preflight = next(row for row in rows if row["id"] == "framework_preflight")
if "reconciliation_readiness" not in preflight["depends_on"]:
    preflight["depends_on"].append("reconciliation_readiness")
services["guardrails"].update({
    "reconciliation_readiness_process_isolated": True,
    "reconciliation_readiness_read_only": True,
    "reconciliation_readiness_no_official_refetch": True,
    "reconciliation_readiness_reuses_validation_integrity": True,
    "service_count": len(rows),
})
save(services_path, services)

contracts_path = CONFIG / "service_contract_registry.json"
contracts = load(contracts_path)
contracts["schema_version"] = 8
contracts["registry"] = "fpl_v4_9_6_service_contracts_v8"
contracts["contracts"]["reconciliation_readiness"] = {
    "path": "data/validation/reconciliation_readiness_v4.json",
    "min_schema_version": 4961,
    "version_field": "release",
    "version_prefix": "4.9.6",
    "required_paths": [
        "status", "target_gw", "stage", "ready_for_reconciliation_now",
        "checks.snapshot_integrity.pass", "checks.validation_lifecycle.pass",
        "checks.ownership_chain.pass", "blockers", "pending",
        "guardrails.read_only_audit", "guardrails.official_api_refetch",
        "guardrails.reconciliation_truth_not_reimplemented",
    ],
    "equals": {
        "status": "PASS",
        "checks.snapshot_integrity.pass": True,
        "checks.validation_lifecycle.pass": True,
        "checks.ownership_chain.pass": True,
        "guardrails.read_only_audit": True,
        "guardrails.official_api_refetch": False,
        "guardrails.reconciliation_truth_not_reimplemented": True,
    },
}
save(contracts_path, contracts)

ownership_path = CONFIG / "architecture_ownership_registry.json"
ownership = load(ownership_path)
ownership["schema_version"] = 4
ownership["registry"] = "fpl_v4_9_6_architecture_ownership_v4"
if not any(row["id"] == "RECONCILIATION_READINESS" for row in ownership["responsibilities"]):
    ownership["responsibilities"].append({
        "id": "RECONCILIATION_READINESS",
        "owner": "reconciliation_readiness",
        "implementation": "src.services.reconciliation_readiness_service",
    })
if not any(row["id"] == "VALIDATION_INTEGRITY" for row in ownership["shared_primitives"]):
    ownership["shared_primitives"].append({
        "id": "VALIDATION_INTEGRITY",
        "owner": "validation_store",
        "implementation": "src.engines.v4_backtest_store.snapshot_integrity+reconciled_integrity",
        "consumers": ["validation_lifecycle", "reconciliation_truth", "reconciliation_readiness"],
    })
save(ownership_path, ownership)

manifest_path = CONFIG / "release_manifest.json"
manifest = load(manifest_path)
manifest["status"] = "GW2_RECONCILIATION_READINESS"
manifest["registries"] = {
    "services": services["registry"],
    "contracts": contracts["registry"],
    "ownership": ownership["registry"],
}
save(manifest_path, manifest)

quality_path = ROOT / "src/engines/v4_quality_gate.py"
quality = quality_path.read_text(encoding="utf-8")
old_levels = '''    assert levels and set(levels[0]) == {"architecture_guard", "raw_snapshot"}\n    assert any(set(level) == {"validation_lifecycle", "rules_compliance", "optimization"} for level in levels)\n    assert any(set(level) == {"framework_preflight", "user_decision_overlay"} for level in levels)\n    assert any(set(level) == {"personal_gw_scorecard", "framework_postflight"} for level in levels)\n'''
new_levels = '''    assert levels and set(levels[0]) == {"architecture_guard", "raw_snapshot"}\n    level_index = {service_id: idx for idx, level in enumerate(levels) for service_id in level}\n    for row in registry.get("services") or []:\n        for dependency in row.get("depends_on") or []:\n            assert level_index[dependency] < level_index[row["id"]], (dependency, row["id"], levels)\n    assert level_index["reconciliation_readiness"] > level_index["validation_lifecycle"]\n    assert level_index["framework_preflight"] > level_index["reconciliation_readiness"]\n'''
if old_levels not in quality:
    raise SystemExit("quality-gate level block changed; refusing blind edit")
quality = quality.replace(old_levels, new_levels)
old_validation = '''    lifecycle = _load("validation/lifecycle_v4.json")\n    predictions = _load("predictions_v4.json")\n'''
new_validation = '''    lifecycle = _load("validation/lifecycle_v4.json")\n    readiness = _load("validation/reconciliation_readiness_v4.json")\n    predictions = _load("predictions_v4.json")\n    assert readiness.get("status") == "PASS"\n    assert readiness.get("blockers") == []\n    assert (readiness.get("checks") or {}).get("snapshot_integrity", {}).get("pass") is True\n    assert (readiness.get("checks") or {}).get("ownership_chain", {}).get("pass") is True\n    assert (readiness.get("guardrails") or {}).get("read_only_audit") is True\n    assert (readiness.get("guardrails") or {}).get("official_api_refetch") is False\n    assert (readiness.get("guardrails") or {}).get("reconciliation_truth_not_reimplemented") is True\n'''
if old_validation not in quality:
    raise SystemExit("quality-gate validation block changed; refusing blind edit")
quality = quality.replace(old_validation, new_validation)
quality_path.write_text(quality, encoding="utf-8")

readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8")
heading = "## V4.9.6 GW2 reconciliation readiness closeout"
if heading not in readme:
    readme += f'''\n\n{heading}\n\n- A thirteenth process-isolated `reconciliation_readiness` service audits the frozen deadline snapshot → Official submitted-picks → finished-GW actuals → immutable reconciliation → calibration-entry chain without performing reconciliation itself.\n- The readiness audit is read-only and performs zero Official FPL refetches; Official acquisition remains owned only by `raw_snapshot`.\n- Snapshot and reconciliation integrity are reused from the canonical validation-store primitives rather than reimplemented.\n- Expected future states are reported as pending (`PREDEADLINE_READY`, `WAITING_SUBMITTED_PICKS`, `WAITING_GW_FINISH`) rather than falsely treated as failures; structural integrity/ownership failures remain fail-closed.\n- `READY_TO_RECONCILE` is emitted only when a valid frozen target-GW snapshot and the target GW's Official event-live actuals are simultaneously present; `RECONCILED` requires the immutable reconciliation archive.\n'''
readme_path.write_text(readme, encoding="utf-8")

print(json.dumps({"services": len(rows), "service_registry": services["registry"], "contract_registry": contracts["registry"], "ownership_registry": ownership["registry"]}))
