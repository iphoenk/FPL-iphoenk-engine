from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/v4_package_optimization_service_split_runner_v3_temp.py"), run_name="__main__")


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:160]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Package optimization is a targeted :15 precompute boundary. Keep the hard decision
# composition SLO at 5s; give the exact full-universe precompute its own governed
# budget that is still tiny relative to the 15-minute checkpoint lead time.
service_path = ROOT / "config/service_registry.json"
registry = json.loads(service_path.read_text(encoding="utf-8"))
registry["schema_version"] = 16
registry["registry"] = "fpl_v4_9_6_microservice_registry_v16"
package = next(row for row in registry["services"] if row.get("id") == "package_optimization")
package["name"] = "Exact full-universe package precompute service"
package["timeout_seconds"] = 105
package["execution_role"] = "TARGETED_PRECOMPUTE"
package["checkpoint_lead_minutes"] = 15

guard = registry["guardrails"]
guard["package_optimization_slo_ms"] = 90000
guard["package_optimization_process_timeout_seconds"] = 105
guard["package_precompute_target_lead_minutes"] = 15
guard["package_precompute_scheduler_role"] = "PRECOMPUTE_NEXT_CHECKPOINT"
guard["package_precompute_must_complete_before_optimization"] = True
guard["package_precompute_semantic_fingerprint_reuse_required"] = True
guard["package_precompute_raw_file_digests_provenance_only"] = True
guard["package_optimization_not_part_of_decision_compute_slo"] = True
guard["decision_compute_slo_ms"] = 5000
service_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

# Release registry must point at the accepted service registry version.
release_path = ROOT / "config/release_manifest.json"
release = json.loads(release_path.read_text(encoding="utf-8"))
release["registries"]["services"] = registry["registry"]
release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")

# Use the existing exact semantic fingerprint rather than raw JSON digests for reuse
# authority. Raw digests remain manifest provenance and still detect mid-search writes.
contract_path = "src/engines/v4_package_artifact_contract.py"
replace_once(
    contract_path,
    "\ndef validate_package_optimization_artifact() -> dict:\n",
    '''\ndef current_semantic_fingerprint() -> str:\n    # Local imports avoid a module-import cycle: decision_pipeline imports this\n    # contract, while validation calls back only after decision_pipeline is loaded.\n    from src.engines.v4_decision_pipeline import _semantic_fingerprint, effective_planning_squad\n    from src.engines.v4_tactical_interaction import build_tactical_interactions\n    from src.engines.v4_wc_optimizer import build_candidates\n\n    predictions = read_json(DATA / "predictions_v4.json", {}) or {}\n    universe = read_json(DATA / "universe.json", {}) or {}\n    team = read_json(DATA / "team.json", {}) or {}\n    latest = read_json(DATA / "latest.json", {}) or {}\n    understat = read_json(DATA / "understat_tactical_v4.json", {}) or {}\n    prices = read_json(DATA / "prices.json", {}) or {}\n    configured_lock = read_json(CONFIG / "locked_squad.json", {}) or {}\n    locked = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n    return _semantic_fingerprint(\n        predictions, universe, locked, understat, candidates=candidates,\n        tactical_interactions=tactical, prices=prices,\n    )\n\n\ndef validate_package_optimization_artifact() -> dict:\n''',
)
replace_once(
    contract_path,
    '''    expected_inputs = current_input_digests()\n    if manifest.get("input_sha256") != expected_inputs:\n        raise RuntimeError("exact package optimization manifest is stale for current semantic inputs")\n''',
    '''    expected_semantic = current_semantic_fingerprint()\n    if manifest.get("semantic_fingerprint") != expected_semantic:\n        raise RuntimeError("exact package optimization manifest is stale for current semantic inputs")\n''',
)

service_impl = "src/services/package_optimization_service.py"
replace_once(
    service_impl,
    "from src.engines.v4_decision_pipeline import effective_planning_squad\n",
    "from src.engines.v4_decision_pipeline import _semantic_fingerprint, effective_planning_squad\n",
)
replace_once(
    service_impl,
    '''    tactical_interactions = build_tactical_interactions(predictions, universe, understat)\n    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical_interactions)\n    package = search_full_universe_packages(\n''',
    '''    tactical_interactions = build_tactical_interactions(predictions, universe, understat)\n    semantic_fingerprint = _semantic_fingerprint(\n        predictions, universe, locked, understat, candidates=candidates,\n        tactical_interactions=tactical_interactions, prices=prices,\n    )\n    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical_interactions)\n    package = search_full_universe_packages(\n''',
)
replace_once(
    service_impl,
    '        "input_sha256": input_before,\n',
    '        "input_sha256": input_before,\n        "semantic_fingerprint": semantic_fingerprint,\n',
)
replace_once(
    service_impl,
    '            "package_slo_separate_from_decision_compute_slo": True,\n',
    '            "package_slo_separate_from_decision_compute_slo": True,\n            "raw_input_digests_are_provenance_only": True,\n            "semantic_fingerprint_is_reuse_authority": True,\n            "targeted_precompute_lead_minutes": 15,\n',
)

# Contract registry must require semantic lineage explicitly.
contracts_path = ROOT / "config/service_contract_registry.json"
contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
manifest_contract = contracts["contracts"]["package_optimization_manifest"]
required = manifest_contract.setdefault("required_paths", [])
for item in (
    "semantic_fingerprint",
    "guardrails.raw_input_digests_are_provenance_only",
    "guardrails.semantic_fingerprint_is_reuse_authority",
    "guardrails.targeted_precompute_lead_minutes",
):
    if item not in required:
        required.append(item)
manifest_contract.setdefault("equals", {}).update({
    "guardrails.raw_input_digests_are_provenance_only": True,
    "guardrails.semantic_fingerprint_is_reuse_authority": True,
    "guardrails.targeted_precompute_lead_minutes": 15,
})
contracts_path.write_text(json.dumps(contracts, indent=2) + "\n", encoding="utf-8")

# Hot lane consumes an already-computed exact package artifact. It must never spend
# 65s recomputing it; semantic drift is a fail-closed hot-path miss handled by the
# scheduled/core precompute path.
hot_path = "src/services/hot_orchestrator.py"
replace_once(
    hot_path,
    '''    t = perf_counter()\n    package_manifest = package_optimization_service.run()\n    service_ms["package_optimization"] = round((perf_counter() - t) * 1000.0, 2)\n\n    post_package_started = perf_counter()\n''',
    '''    t = perf_counter()\n    from src.engines.v4_package_artifact_contract import validate_package_optimization_artifact\n    package_manifest = validate_package_optimization_artifact()\n    service_ms["package_optimization_manifest_validation"] = round((perf_counter() - t) * 1000.0, 2)\n    service_ms["package_optimization"] = 0.0\n\n    post_package_started = perf_counter()\n''',
)
replace_once(
    hot_path,
    '            "package_optimization_runs_concurrently_with_validation": True,\n',
    '            "package_optimization_precomputed_before_hot_path": True,\n            "package_optimization_not_recomputed_in_hot_path": True,\n',
)

# Version generated tests to the precompute SLO and semantic-lineage contract.
boundary_test = "tests/test_v4_package_optimization_service_boundary.py"
replace_once(boundary_test, '    assert guard["package_optimization_slo_ms"] == 60000\n', '    assert guard["package_optimization_slo_ms"] == 90000\n')
replace_once(
    boundary_test,
    '    monkeypatch.setattr(v4_package_artifact_contract, "current_input_digests", lambda: {"predictions": "new"})\n',
    '    monkeypatch.setattr(v4_package_artifact_contract, "current_semantic_fingerprint", lambda: "new")\n',
)
replace_once(
    boundary_test,
    '        "input_sha256": {"predictions": "old"},\n',
    '        "input_sha256": {"predictions": "old"},\n        "semantic_fingerprint": "old",\n',
)

# CI language and acceptance must be registry-driven rather than hardcoded to eight.
replace_once(
    ".github/workflows/fpl-engine-core.yml",
    "      - name: Run 8 bounded DAG-parallel V4 services\n",
    "      - name: Run registry-driven DAG V4 services with exact package precompute\n",
)

print("v4 targeted-precompute architecture staged: 90s exact precompute SLO, 5s decision SLO, semantic reuse")
