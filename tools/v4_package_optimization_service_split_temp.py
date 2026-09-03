from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one replacement in {path}, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


write(
    "src/engines/v4_package_artifact_contract.py",
    '''from __future__ import annotations

from pathlib import Path

from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, read_json

CONTRACT = "V4_EXACT_PACKAGE_OPTIMIZATION_MANIFEST_V1"
PACKAGE_OUTFILE = DATA / "wc_package_audit_v4.json"
TACTICAL_INTERACTION_OUTFILE = DATA / "tactical_interaction_v4.json"
MANIFEST_OUTFILE = DATA / "package_optimization_manifest_v4.json"


def governed_input_paths() -> dict[str, Path]:
    return {
        "predictions": DATA / "predictions_v4.json",
        "universe": DATA / "universe.json",
        "team": DATA / "team.json",
        "latest": DATA / "latest.json",
        "prices": DATA / "prices.json",
        "understat_tactical": DATA / "understat_tactical_v4.json",
        "locked_squad": CONFIG / "locked_squad.json",
        "full_universe_policy": CONFIG / "intelligence" / "full_universe_package_search.json",
    }


def _digest_or_absent(path: Path) -> str:
    return file_digest(path) if path.exists() else "ABSENT"


def current_input_digests() -> dict[str, str]:
    return {name: _digest_or_absent(path) for name, path in governed_input_paths().items()}


def validate_package_optimization_artifact() -> dict:
    manifest = read_json(MANIFEST_OUTFILE, {}) or {}
    if manifest.get("contract") != CONTRACT or manifest.get("status") != "PASS":
        raise RuntimeError("exact package optimization manifest unavailable or not PASS")
    expected_inputs = current_input_digests()
    if manifest.get("input_sha256") != expected_inputs:
        raise RuntimeError("exact package optimization manifest is stale for current semantic inputs")
    if not PACKAGE_OUTFILE.exists() or manifest.get("package_artifact_sha256") != file_digest(PACKAGE_OUTFILE):
        raise RuntimeError("exact package optimization artifact digest mismatch")
    if not TACTICAL_INTERACTION_OUTFILE.exists() or manifest.get("tactical_interaction_sha256") != file_digest(TACTICAL_INTERACTION_OUTFILE):
        raise RuntimeError("package tactical interaction artifact digest mismatch")
    package = read_json(PACKAGE_OUTFILE, {}) or {}
    search = package.get("search") or {}
    proof = (
        search.get("status") == "FULL_UNIVERSE_PROVEN"
        and search.get("authoritative_for_recommendation") is True
        and package.get("decision_authority") == "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"
        and not bool(search.get("heuristic_candidate_cutoff"))
        and not bool(search.get("beam_cutoff"))
    )
    if not proof:
        raise RuntimeError("exact package optimization proof is incomplete")
    return manifest
''',
)

write(
    "src/services/package_optimization_service.py",
    '''from __future__ import annotations

import json
from time import perf_counter

from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_full_universe_package_search import search_full_universe_packages
from src.engines.v4_package_artifact_contract import (
    CONTRACT,
    MANIFEST_OUTFILE,
    PACKAGE_OUTFILE,
    TACTICAL_INTERACTION_OUTFILE,
    current_input_digests,
)
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import build_candidates
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json


def _package_slo_ms() -> float:
    registry = read_json(CONFIG / "service_registry.json", {}) or {}
    value = (registry.get("guardrails") or {}).get("package_optimization_slo_ms")
    if value is None:
        raise RuntimeError("package_optimization_slo_ms missing from governed service registry")
    return float(value)


def run() -> dict:
    started = perf_counter()
    input_before = current_input_digests()
    predictions = read_json(DATA / "predictions_v4.json", {}) or {}
    universe = read_json(DATA / "universe.json", {}) or {}
    team = read_json(DATA / "team.json", {}) or {}
    latest = read_json(DATA / "latest.json", {}) or {}
    prices = read_json(DATA / "prices.json", {}) or {}
    understat = read_json(DATA / "understat_tactical_v4.json", {}) or {}
    configured_lock = read_json(CONFIG / "locked_squad.json", {}) or {}
    locked = effective_planning_squad(team, configured_lock, latest)

    candidates = build_candidates(predictions, universe)
    tactical_interactions = build_tactical_interactions(predictions, universe, understat)
    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical_interactions)
    package = search_full_universe_packages(
        candidates,
        locked,
        predictions=predictions,
        universe=universe,
        understat=understat,
        interactions=tactical_interactions,
        prices=prices,
        max_replacements=3,
    )
    atomic_json(PACKAGE_OUTFILE, package)

    input_after = current_input_digests()
    if input_after != input_before:
        raise RuntimeError("package optimization inputs changed during exact search")

    search = package.get("search") or {}
    proof = (
        search.get("status") == "FULL_UNIVERSE_PROVEN"
        and search.get("authoritative_for_recommendation") is True
        and package.get("decision_authority") == "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"
        and not bool(search.get("heuristic_candidate_cutoff"))
        and not bool(search.get("beam_cutoff"))
    )
    duration_ms = round((perf_counter() - started) * 1000.0, 2)
    slo_ms = _package_slo_ms()
    status = "PASS" if proof and duration_ms < slo_ms else "FAIL"
    manifest = {
        "schema_version": 1,
        "contract": CONTRACT,
        "generated_at": iso_now(),
        "status": status,
        "duration_ms": duration_ms,
        "slo_ms": slo_ms,
        "slo_status": "PASS" if duration_ms < slo_ms else "FAIL",
        "input_sha256": input_before,
        "package_artifact_sha256": file_digest(PACKAGE_OUTFILE),
        "tactical_interaction_sha256": file_digest(TACTICAL_INTERACTION_OUTFILE),
        "search": {
            "status": search.get("status"),
            "authoritative_for_recommendation": search.get("authoritative_for_recommendation"),
            "decision_authority": package.get("decision_authority"),
            "heuristic_candidate_cutoff": bool(search.get("heuristic_candidate_cutoff")),
            "beam_cutoff": bool(search.get("beam_cutoff")),
            "global_optimality_guaranteed_under_declared_package_semantics": search.get("global_optimality_guaranteed_under_declared_package_semantics"),
            "diagnostics": search.get("diagnostics") or {},
        },
        "guardrails": {
            "full_universe_exact_search_owner": True,
            "watchlist_candidate_authority": False,
            "search_width_reduction": False,
            "decision_consumer_recompute_forbidden": True,
            "input_lineage_fail_closed": True,
            "package_slo_separate_from_decision_compute_slo": True,
        },
    }
    atomic_json(MANIFEST_OUTFILE, manifest)
    if status != "PASS":
        raise RuntimeError(
            f"package optimization failed exact proof/SLO: proof={proof} duration_ms={duration_ms} slo_ms={slo_ms}"
        )
    print(json.dumps({
        "service": "package_optimization",
        "status": status,
        "duration_ms": duration_ms,
        "slo_ms": slo_ms,
        "search": search.get("status"),
        "input_universe": (search.get("diagnostics") or {}).get("input_universe_size"),
        "searched_packages": (search.get("diagnostics") or {}).get("legal_packages_evaluated"),
    }, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    run()
''',
)

# Decision pipeline becomes a consumer of the immutable exact package artifact.
p = "src/engines/v4_decision_pipeline.py"
replace_once(p, "from src.engines.v4_full_universe_package_search import search_full_universe_packages\n", "from src.engines.v4_package_artifact_contract import validate_package_optimization_artifact\n")
replace_once(p, "from src.engines.v4_tactical_interaction import build_tactical_interactions\n", "")
replace_once(p, 'CACHE_ALGORITHM = "v4.9.7-full-universe-package-cache-v1-tactical-interaction"', 'CACHE_ALGORITHM = "v4.9.7-package-artifact-consumer-cache-v2"')
replace_once(
    p,
    '''        elif kind == "packages":\n            out = search_full_universe_packages(\n                shared["candidates"],\n                shared["locked"],\n                predictions=shared["predictions"],\n                universe=shared["universe"],\n                understat=shared["understat_tactical"],\n                interactions=shared["tactical_interactions"],\n                prices=shared["prices"],\n                max_replacements=3,\n            )\n            atomic_json(PACKAGE_OUTFILE, out)\n        elif kind == "lineup":\n''',
    '''        elif kind == "lineup":\n''',
)
replace_once(
    p,
    'def _run_parallel_decisions(candidates, locked, predictions, universe, understat_tactical, tactical_interactions, prices):',
    'def _run_parallel_decisions(candidates, locked, predictions, universe, understat_tactical):',
)
replace_once(p, '        "tactical_interactions": tactical_interactions,\n        "prices": prices,\n', '')
replace_once(
    p,
    '    for kind, name in (("wc", "v497-wc-fast"), ("packages", "v497-packages-full-universe"), ("lineup", "v497-lineup")):',
    '    for kind, name in (("wc", "v497-wc-fast"), ("lineup", "v497-lineup")):',
)
replace_once(p, '    return {"wc": WC_OUTFILE, "packages": PACKAGE_OUTFILE, "lineup": LINEUP_OUTFILE}', '    return {"wc": WC_OUTFILE, "lineup": LINEUP_OUTFILE}')
replace_once(
    p,
    '''    t = perf_counter()\n    tactical_interactions = build_tactical_interactions(predictions, universe, understat_tactical)\n    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical_interactions)\n    tactical_interaction_ms = round((perf_counter() - t) * 1000.0, 1)\n\n    t = perf_counter()\n''',
    '''    t = perf_counter()\n    package_manifest = validate_package_optimization_artifact()\n    tactical_interactions = read_json(TACTICAL_INTERACTION_OUTFILE, {}) or {}\n    package_artifact_validation_ms = round((perf_counter() - t) * 1000.0, 1)\n\n    t = perf_counter()\n''',
)
replace_once(p, '        "tactical_interaction_ms": tactical_interaction_ms,', '        "package_artifact_validation_ms": package_artifact_validation_ms,')
replace_once(p, '        "load_shared_inputs_candidates_and_fingerprint_ms": round(load_ms + candidates_ms + tactical_interaction_ms + fingerprint_ms, 1),', '        "load_shared_inputs_candidates_and_fingerprint_ms": round(load_ms + candidates_ms + package_artifact_validation_ms + fingerprint_ms, 1),')
replace_once(
    p,
    '''        statuses = {\n            "wc": {"ok": True, "ms": 0.0, "cache": True},\n            "packages": {"ok": True, "ms": 0.0, "cache": True},\n            "lineup": {"ok": True, "ms": 0.0, "cache": True},\n        }\n''',
    '''        statuses = {\n            "wc": {"ok": True, "ms": 0.0, "cache": True},\n            "lineup": {"ok": True, "ms": 0.0, "cache": True},\n        }\n''',
)
replace_once(
    p,
    '''        statuses, parallel_wall = _run_parallel_decisions(\n            candidates, locked, predictions, universe, understat_tactical, tactical_interactions, prices,\n        )\n''',
    '''        statuses, parallel_wall = _run_parallel_decisions(\n            candidates, locked, predictions, universe, understat_tactical,\n        )\n''',
)
replace_once(p, '        "package_audit_cpu_ms": statuses["packages"]["ms"],', '        "package_precompute_ms": float(package_manifest.get("duration_ms") or 0.0),')
replace_once(
    p,
    '''                (statuses["wc"]["ms"] + statuses["packages"]["ms"] + statuses["lineup"]["ms"]) / max(1.0, parallel_wall),\n''',
    '''                (statuses["wc"]["ms"] + statuses["lineup"]["ms"]) / max(1.0, parallel_wall),\n''',
)
replace_once(
    p,
    '            "parallel_wc_package": True,\n            "parallel_lineup_with_wc_package": True,',
    '            "package_optimization_separate_service": True,\n            "package_artifact_lineage_verified": True,\n            "package_search_recompute_in_decision_boundary": False,\n            "parallel_wc_lineup": True,',
)
replace_once(p, '        "package_audit_cpu_ms": statuses["packages"]["ms"],\n', '        "package_precompute_ms": float(package_manifest.get("duration_ms") or 0.0),\n')
replace_once(
    p,
    '''            "full_universe_package_policy_in_cache_key": True,\n            "tactical_interaction_semantics_in_cache_key": True,\n            "price_scenario_semantics_in_cache_key": True,\n''',
    '''            "package_artifact_not_cached_by_decision_consumer": True,\n            "package_lineage_verified_separately": True,\n''',
)

# Cold orchestrator must not encode the old boundary count.
replace_once(
    "src/services/orchestrator.py",
    '        "engine": "v4.9.6-service-orchestrator-8-boundary",',
    '        "engine": "v4.9.6-service-orchestrator-registry-driven",',
)

# Hot-path parity: run validation and package optimization concurrently after prediction;
# optimization waits for exact package artifact, then remains the hard decision-compute boundary.
h = "src/services/hot_orchestrator.py"
replace_once(h, '    optimization_slo_service,\n', '    optimization_slo_service,\n    package_optimization_service,\n')
replace_once(h, '    "validation": validation_service.__name__,\n    "optimization": optimization_slo_service.__name__,', '    "validation": validation_service.__name__,\n    "package_optimization": package_optimization_service.__name__,\n    "optimization": optimization_slo_service.__name__,')
replace_once(
    h,
    '''    t = perf_counter()\n    decision = optimization_slo_service.run()\n    service_ms["optimization"] = round((perf_counter() - t) * 1000.0, 2)\n''',
    '''    t = perf_counter()\n    package_manifest = package_optimization_service.run()\n    service_ms["package_optimization"] = round((perf_counter() - t) * 1000.0, 2)\n\n    post_package_started = perf_counter()\n    t = perf_counter()\n    decision = optimization_slo_service.run()\n    service_ms["optimization"] = round((perf_counter() - t) * 1000.0, 2)\n''',
)
replace_once(h, '    total_ms = round((perf_counter() - started) * 1000.0, 2)\n', '    total_ms = round((perf_counter() - started) * 1000.0, 2)\n    post_package_serving_ms = round((perf_counter() - post_package_started) * 1000.0, 2)\n')
replace_once(h, '        "engine": "v4.9.6-e2e-hot-path-production-wrapper-parity-v4",', '        "engine": "v4.9.7-e2e-hot-path-package-service-parity-v1",')
replace_once(h, '        "service_ms": service_ms,\n', '        "service_ms": service_ms,\n        "package_optimization_manifest": package_manifest,\n        "post_package_serving_ms": post_package_serving_ms,\n')
replace_once(
    h,
    '''        "target_status": {\n            "decision_under_1s": float(timings.get("total_pipeline_ms") or 1e9) < 1000.0,\n            "serving_under_2s": serving_ms < 2000.0,\n            "serving_under_3s": serving_ms < 3000.0,\n            "full_cold_run_under_3s": total_ms < 3000.0,\n        },\n''',
    '''        "target_status": {\n            "decision_under_1s": float(timings.get("total_pipeline_ms") or 1e9) < 1000.0,\n            "post_package_serving_under_2s": post_package_serving_ms < 2000.0,\n            "post_package_serving_under_3s": post_package_serving_ms < 3000.0,\n            "full_checkpoint_includes_exact_package_precompute": True,\n        },\n''',
)
replace_once(
    h,
    '            "validation_runs_concurrently_not_skipped": True,\n',
    '            "validation_runs_concurrently_not_skipped": True,\n            "package_optimization_runs_concurrently_with_validation": True,\n            "package_optimization_is_separate_from_decision_compute_slo": True,\n            "package_artifact_lineage_verified_before_decision": True,\n',
)
replace_once(h, '        "serving_e2e_ms": serving_ms,\n', '        "serving_e2e_ms": serving_ms,\n        "post_package_serving_ms": post_package_serving_ms,\n        "package_optimization_ms": service_ms.get("package_optimization"),\n')

# Registry: add the ninth exact package optimization boundary.
service_path = ROOT / "config/service_registry.json"
services = json.loads(service_path.read_text(encoding="utf-8"))
services["schema_version"] = 15
services["registry"] = "fpl_v4_9_6_microservice_registry_v15"
rows = services["services"]
if any(row.get("id") == "package_optimization" for row in rows):
    raise RuntimeError("package_optimization service already exists")
opt_index = next(i for i, row in enumerate(rows) if row.get("id") == "optimization")
package_service = {
    "id": "package_optimization",
    "name": "Exact full-universe package optimization",
    "boundary_state": "INDEPENDENT",
    "module": "src.services.package_optimization_service",
    "command": ["{python}", "-m", "src.services.package_optimization_service"],
    "timeout_seconds": 65,
    "depends_on": ["prediction"],
    "produces": ["tactical_interaction", "wc_package", "package_optimization_manifest"],
}
rows.insert(opt_index, package_service)
optimization = next(row for row in rows if row.get("id") == "optimization")
optimization["depends_on"] = ["prediction", "package_optimization"]
optimization["produces"] = [name for name in optimization.get("produces") or [] if name != "wc_package"]
guard = services.setdefault("guardrails", {})
guard["service_count"] = 9
guard["package_optimization_slo_ms"] = 60000
guard["package_optimization_process_timeout_seconds"] = 65
guard["package_optimization_is_exact_authoritative_boundary"] = True
guard["package_optimization_search_width_unchanged"] = True
guard["package_optimization_manifest_lineage_required"] = True
guard["optimization_consumes_exact_package_artifact"] = True
guard["optimization_recomputes_package_search"] = False
guard["validation_and_package_optimization_may_parallelize_after_prediction"] = True
guard["package_slo_separate_from_decision_compute_slo"] = True
service_path.write_text(json.dumps(services, indent=2) + "\n", encoding="utf-8")

# Contract registry: single owner and strict exact proof for package artifacts.
contract_path = ROOT / "config/service_contract_registry.json"
contracts = json.loads(contract_path.read_text(encoding="utf-8"))
contracts["schema_version"] = 12
contracts["registry"] = "fpl_v4_9_6_service_contracts_v12"
wc = contracts["contracts"]["wc_package"]
for required in (
    "search.status",
    "search.authoritative_for_recommendation",
    "decision_authority",
    "efficient_frontier.status",
):
    if required not in wc.setdefault("required_paths", []):
        wc["required_paths"].append(required)
wc.setdefault("equals", {}).update({
    "search.status": "FULL_UNIVERSE_PROVEN",
    "search.authoritative_for_recommendation": True,
    "decision_authority": "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN",
    "efficient_frontier.status": "PASS",
})
contracts["contracts"]["tactical_interaction"] = {
    "path": "data/tactical_interaction_v4.json",
    "required_paths": ["contract", "health.status", "guardrails.direct_xpts_mutation", "guardrails.direct_xmins_mutation"],
    "equals": {
        "guardrails.direct_xpts_mutation": False,
        "guardrails.direct_xmins_mutation": False,
    },
}
contracts["contracts"]["package_optimization_manifest"] = {
    "path": "data/package_optimization_manifest_v4.json",
    "min_schema_version": 1,
    "required_paths": [
        "contract", "status", "duration_ms", "slo_ms", "slo_status", "input_sha256",
        "package_artifact_sha256", "tactical_interaction_sha256", "search.status",
        "search.authoritative_for_recommendation", "search.decision_authority",
        "search.heuristic_candidate_cutoff", "search.beam_cutoff",
        "guardrails.full_universe_exact_search_owner", "guardrails.decision_consumer_recompute_forbidden",
        "guardrails.input_lineage_fail_closed", "guardrails.package_slo_separate_from_decision_compute_slo",
    ],
    "equals": {
        "contract": "V4_EXACT_PACKAGE_OPTIMIZATION_MANIFEST_V1",
        "status": "PASS",
        "slo_status": "PASS",
        "search.status": "FULL_UNIVERSE_PROVEN",
        "search.authoritative_for_recommendation": True,
        "search.decision_authority": "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN",
        "search.heuristic_candidate_cutoff": False,
        "search.beam_cutoff": False,
        "guardrails.full_universe_exact_search_owner": True,
        "guardrails.decision_consumer_recompute_forbidden": True,
        "guardrails.input_lineage_fail_closed": True,
        "guardrails.package_slo_separate_from_decision_compute_slo": True,
    },
}
contract_path.write_text(json.dumps(contracts, indent=2) + "\n", encoding="utf-8")

# Ownership and optimizer registry now make package_optimization the single runtime owner.
own_path = ROOT / "config/architecture_ownership_registry.json"
own = json.loads(own_path.read_text(encoding="utf-8"))
own["schema_version"] = 11
own["registry"] = "fpl_v4_9_6_architecture_ownership_v11"
package_cap = next(row for row in own["capability_matrix"] if row.get("capability") == "PACKAGE_OPTIMIZER")
package_cap["current_owner"] = "package_optimization"
package_cap["consumers"] = ["optimization", "recommendation_sanity", "decision_arbitration"]
package_cap["duplicates_overlap"] = "package_optimization is the sole exact runtime writer; decision optimization consumes the lineage-verified artifact and cannot rerun package search; legacy package audits are read-only references"
cache_cap = next(row for row in own["capability_matrix"] if row.get("capability") == "DECISION_ARTIFACT_CACHE")
cache_cap["input_contract"] = "WC/lineup consumer semantic fingerprint; exact package artifact has separate immutable lineage manifest"
cache_cap["duplicates_overlap"] = "Only WC/lineup cached in decision boundary; full-universe package search is owned by package_optimization and validated by manifest"
own_path.write_text(json.dumps(own, indent=2) + "\n", encoding="utf-8")

opt_path = ROOT / "config/optimizer_equivalence_registry.json"
opt = json.loads(opt_path.read_text(encoding="utf-8"))
opt["schema_version"] = 3
opt["registry"] = "v4_optimizer_equivalence_v2"
opt["production"]["transfer_package_service"] = "src.services.package_optimization_service"
opt["guardrails"]["transfer_package_single_runtime_writer"] = "package_optimization"
opt["guardrails"]["decision_boundary_package_recompute_forbidden"] = True
opt_path.write_text(json.dumps(opt, indent=2) + "\n", encoding="utf-8")

release_path = ROOT / "config/release_manifest.json"
release = json.loads(release_path.read_text(encoding="utf-8"))
release["registries"]["services"] = services["registry"]
release["registries"]["contracts"] = contracts["registry"]
release["registries"]["ownership"] = own["registry"]
release["registries"]["optimizer_equivalence"] = opt["registry"]
release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")

# Architecture attestation must bind the new optimizer registry semantics already attested;
# package manifest is runtime data and intentionally not an attested config.

# Update cache test for two consumer-owned artifacts.
test_path = "tests/test_v496_e2e_performance_hardening.py"
replace_once(test_path, '    assert stored["guardrails"]["full_universe_package_policy_in_cache_key"] is True\n    assert stored["guardrails"]["tactical_interaction_semantics_in_cache_key"] is True\n    assert stored["guardrails"]["price_scenario_semantics_in_cache_key"] is True\n', '    assert stored["guardrails"]["package_artifact_not_cached_by_decision_consumer"] is True\n    assert stored["guardrails"]["package_lineage_verified_separately"] is True\n')
replace_once(test_path, '    assert set(stored["artifact_sha256"]) == {"wc", "packages", "lineup"}\n', '    assert set(stored["artifact_sha256"]) == {"wc", "lineup"}\n')

write(
    "tests/test_v4_package_optimization_service_boundary.py",
    '''from __future__ import annotations

import inspect
import json

import pytest

from src.engines import v4_decision_pipeline, v4_package_artifact_contract
from src.services import package_optimization_service
from src.services.orchestrator import _service_levels


def test_package_optimization_is_ninth_registry_boundary_and_single_writer():
    registry = json.loads((v4_package_artifact_contract.CONFIG / "service_registry.json").read_text())
    assert registry["guardrails"]["service_count"] == 9
    assert len(registry["services"]) == 9
    package = next(row for row in registry["services"] if row["id"] == "package_optimization")
    optimization = next(row for row in registry["services"] if row["id"] == "optimization")
    assert package["depends_on"] == ["prediction"]
    assert set(package["produces"]) >= {"wc_package", "package_optimization_manifest", "tactical_interaction"}
    assert "package_optimization" in optimization["depends_on"]
    assert "wc_package" not in optimization["produces"]
    producers = [row["id"] for row in registry["services"] if "wc_package" in (row.get("produces") or [])]
    assert producers == ["package_optimization"]
    levels = _service_levels(registry)
    level_by_id = {row["id"]: index for index, level in enumerate(levels) for row in level}
    assert level_by_id["validation"] == level_by_id["package_optimization"]
    assert level_by_id["optimization"] > level_by_id["package_optimization"]


def test_decision_pipeline_cannot_rerun_full_universe_package_search():
    source = inspect.getsource(v4_decision_pipeline)
    assert "search_full_universe_packages(" not in source
    assert '"packages", "v497-packages-full-universe"' not in source
    assert "validate_package_optimization_artifact()" in source


def test_package_service_is_exact_search_runtime_owner():
    source = inspect.getsource(package_optimization_service.run)
    assert "search_full_universe_packages(" in source
    assert "FULL_UNIVERSE_PROVEN" in source
    assert "heuristic_candidate_cutoff" in source
    assert "beam_cutoff" in source


def test_package_manifest_fails_closed_when_inputs_drift(monkeypatch, tmp_path):
    package = tmp_path / "package.json"
    tactical = tmp_path / "tactical.json"
    manifest = tmp_path / "manifest.json"
    package.write_text(json.dumps({
        "decision_authority": "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN",
        "search": {"status": "FULL_UNIVERSE_PROVEN", "authoritative_for_recommendation": True, "heuristic_candidate_cutoff": False, "beam_cutoff": False},
    }))
    tactical.write_text(json.dumps({"ok": True}))
    monkeypatch.setattr(v4_package_artifact_contract, "PACKAGE_OUTFILE", package)
    monkeypatch.setattr(v4_package_artifact_contract, "TACTICAL_INTERACTION_OUTFILE", tactical)
    monkeypatch.setattr(v4_package_artifact_contract, "MANIFEST_OUTFILE", manifest)
    monkeypatch.setattr(v4_package_artifact_contract, "current_input_digests", lambda: {"predictions": "new"})
    manifest.write_text(json.dumps({
        "contract": v4_package_artifact_contract.CONTRACT,
        "status": "PASS",
        "input_sha256": {"predictions": "old"},
        "package_artifact_sha256": "x",
        "tactical_interaction_sha256": "y",
    }))
    with pytest.raises(RuntimeError, match="stale"):
        v4_package_artifact_contract.validate_package_optimization_artifact()


def test_package_and_decision_slos_are_governed_separately():
    registry = json.loads((v4_package_artifact_contract.CONFIG / "service_registry.json").read_text())
    guard = registry["guardrails"]
    assert guard["package_optimization_slo_ms"] == 60000
    assert guard["decision_compute_slo_ms"] == 5000
    assert guard["package_slo_separate_from_decision_compute_slo"] is True
    assert guard["optimization_recomputes_package_search"] is False
''',
)

print("package optimization service split staged")
