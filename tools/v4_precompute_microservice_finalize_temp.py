from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/v4_package_optimization_service_split_runner_v4_temp.py"), run_name="__main__")


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:180]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Govern the expensive exact stage as precompute, distinct from the <5s decision boundary.
service_path = ROOT / "config/service_registry.json"
registry = json.loads(service_path.read_text(encoding="utf-8"))
registry["schema_version"] = 17
registry["registry"] = "fpl_v4_9_7_microservice_registry_v17"
package = next(row for row in registry["services"] if row.get("id") == "package_optimization")
package.update({
    "name": "Exact full-universe package precompute service",
    "timeout_seconds": 240,
    "execution_role": "TARGETED_PRECOMPUTE_WITH_FAST_REUSE",
    "checkpoint_lead_minutes": 15,
    "reuse_authority": "SEMANTIC_FINGERPRINT",
})
guard = registry["guardrails"]
guard.update({
    "service_count": len(registry["services"]),
    "package_optimization_slo_ms": 210000,
    "package_optimization_process_timeout_seconds": 240,
    "package_precompute_target_lead_minutes": 15,
    "package_precompute_scheduler_role": "PRECOMPUTE_NEXT_CHECKPOINT",
    "package_precompute_must_complete_before_optimization": True,
    "package_precompute_semantic_fingerprint_reuse_required": True,
    "package_precompute_raw_file_digests_provenance_only": True,
    "package_optimization_not_part_of_decision_compute_slo": True,
    "package_service_fast_reuse_before_recompute": True,
    "service_count_hardcode_in_orchestrator_forbidden": True,
    "workflow_business_semantics_forbidden": True,
    "decision_compute_slo_ms": 5000,
})
service_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

release_path = ROOT / "config/release_manifest.json"
release = json.loads(release_path.read_text(encoding="utf-8"))
release["registries"]["services"] = registry["registry"]
release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")

# The service itself is registry/policy-driven and validates a reusable exact artifact first.
service_impl = "src/services/package_optimization_service.py"
replace_once(
    service_impl,
    "    current_input_digests,\n)",
    "    current_input_digests,\n    validate_package_optimization_artifact,\n)",
)
replace_once(
    service_impl,
    "def run() -> dict:\n    started = perf_counter()\n",
    '''def run() -> dict:\n    # Hot/checkpoint execution must reuse a semantically identical proven artifact.\n    # A miss falls through to the exact precompute path; it never degrades to a beam/top-N search.\n    try:\n        reusable = validate_package_optimization_artifact()\n    except RuntimeError:\n        reusable = None\n    if reusable is not None:\n        print(json.dumps({\n            "service": "package_optimization",\n            "status": "PASS",\n            "execution": "REUSED_EXACT_ARTIFACT",\n            "duration_ms": 0.0,\n            "search": (reusable.get("search") or {}).get("status"),\n        }, ensure_ascii=False))\n        return reusable\n\n    started = perf_counter()\n''',
)
replace_once(
    service_impl,
    '''    package = search_full_universe_packages(\n        candidates,\n        locked,\n        predictions=predictions,\n        universe=universe,\n        understat=understat,\n        interactions=tactical_interactions,\n        prices=prices,\n        max_replacements=3,\n    )\n''',
    '''    search_policy = read_json(CONFIG / "intelligence" / "full_universe_package_search.json", {}) or {}\n    max_replacements = int(((search_policy.get("search") or {}).get("maximum_replacements") or 0))\n    if max_replacements < 1:\n        raise RuntimeError("maximum_replacements missing/invalid in governed full-universe search policy")\n    package = search_full_universe_packages(\n        candidates,\n        locked,\n        predictions=predictions,\n        universe=universe,\n        understat=understat,\n        interactions=tactical_interactions,\n        prices=prices,\n        max_replacements=max_replacements,\n    )\n''',
)
replace_once(
    service_impl,
    '            "targeted_precompute_lead_minutes": 15,\n',
    '            "targeted_precompute_lead_minutes": int((read_json(CONFIG / "service_registry.json", {}) or {}).get("guardrails", {}).get("package_precompute_target_lead_minutes") or 0),\n            "max_replacements_from_policy": True,\n            "fast_reuse_before_recompute": True,\n',
)

# CI/production core: exact precompute runs once before the registry DAG. The DAG service
# then validates/reuses the same semantic artifact, proving no expensive recompute at checkpoint.
core_workflow = ".github/workflows/fpl-engine-core.yml"
replace_once(
    core_workflow,
    '''      - name: Run registry-driven DAG V4 services with exact package precompute\n        run: python -m src.services.orchestrator daily --stats --deep-stats\n''',
    '''      - name: Precompute exact full-universe package artifact\n        run: python -m src.services.package_optimization_service\n\n      - name: Run registry-driven DAG V4 services with exact package precompute\n        run: python -m src.services.orchestrator daily --stats --deep-stats\n''',
)

# Structural acceptance: no exact search in the decision consumer and no source hardcode for package width/SLO.
write_test = ROOT / "tests/test_v4_precompute_microservice_governance.py"
write_test.write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _text(path: str) -> str:\n    return (ROOT / path).read_text(encoding="utf-8")\n\n\ndef _json(path: str):\n    return json.loads(_text(path))\n\n\ndef test_package_precompute_is_registry_driven_and_decision_consumer_is_read_only():\n    registry = _json("config/service_registry.json")\n    package = next(row for row in registry["services"] if row["id"] == "package_optimization")\n    decision = next(row for row in registry["services"] if row["id"] == "optimization")\n    source = _text("src/services/package_optimization_service.py")\n    decision_source = _text("src/engines/v4_decision_pipeline.py")\n    assert package["execution_role"] == "TARGETED_PRECOMPUTE_WITH_FAST_REUSE"\n    assert package["reuse_authority"] == "SEMANTIC_FINGERPRINT"\n    assert package["timeout_seconds"] == registry["guardrails"]["package_optimization_process_timeout_seconds"]\n    assert registry["guardrails"]["package_optimization_not_part_of_decision_compute_slo"] is True\n    assert registry["guardrails"]["decision_compute_slo_ms"] == 5000\n    assert "validate_package_optimization_artifact()" in source\n    assert "maximum_replacements" in source and "max_replacements=3" not in source\n    assert "search_full_universe_packages(" not in decision_source\n    assert "validate_package_optimization_artifact()" in decision_source\n    assert "package_optimization" in decision["depends_on"]\n\n\ndef test_workflow_orchestrates_precompute_without_encoding_search_semantics():\n    workflow = _text(".github/workflows/fpl-engine-core.yml")\n    assert "python -m src.services.package_optimization_service" in workflow\n    assert "maximum_replacements" not in workflow\n    assert "beam" not in workflow.lower()\n    assert "candidate" not in workflow.lower() or "candidate_state" in workflow\n''', encoding="utf-8")

print("final registry-driven precompute microservice architecture staged")
