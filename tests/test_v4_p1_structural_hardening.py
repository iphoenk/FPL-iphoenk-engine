from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _json(path: str) -> dict:
    return json.loads(_text(path))


def test_legacy_quality_gate_is_thin_compatibility_shim_without_assertion_ownership():
    path = ROOT / "src/engines/v4_quality_gate_legacy.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert functions == ["run"]
    assert "assert " not in source
    assert "v4_quality_gate_core" in source
    assert "v4_quality_gate_runner" in source
    assert "core._assert_framework_health =" not in source
    assert "core._assert_orchestration =" not in source
    assert "core._assert_prediction_and_validation =" not in source


def test_quality_gate_runner_uses_explicit_dependencies_without_module_monkeypatching():
    source = _text("src/engines/v4_quality_gate_runner.py")
    tree = ast.parse(source)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    kwonly = {arg.arg for arg in run.args.kwonlyargs}
    assert kwonly == {
        "assert_framework_health",
        "assert_orchestration",
        "assert_prediction_and_validation",
    }
    assert "core._assert_framework_health =" not in source
    assert "core._assert_orchestration =" not in source
    assert "core._assert_prediction_and_validation =" not in source


def test_optimizer_runtime_owner_is_full_universe_for_transfer_packages_and_reference_is_equivalence_only():
    registry = _json("config/optimizer_equivalence_registry.json")
    manifest = _json("config/release_manifest.json")
    decision_source = _text("src/engines/v4_decision_pipeline.py")
    assert manifest["registries"]["optimizer_equivalence"] == registry["registry"]
    assert "from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast" in decision_source
    assert "from src.engines.v4_full_universe_package_search import search_full_universe_packages" in decision_source
    assert "decision_report_from_candidates_fast(" in decision_source
    assert "search_full_universe_packages(" in decision_source
    assert "audit_packages_from_candidates_fast(" not in decision_source
    assert registry["production"]["transfer_package_optimizer"] == "src.engines.v4_full_universe_package_search.search_full_universe_packages"
    assert registry["production"]["full_squad_optimizer_state"] == "RESTRICTED_BEAM_FULL_SQUAD"
    assert registry["reference"]["runtime_authority"] is False
    assert registry["reference"]["purpose"] == "read_only_semantic_equivalence_oracle"
    assert registry["guardrails"]["optimizer_search_width_reduction_forbidden"] is True
    assert registry["guardrails"]["fast_path_semantic_drift_forbidden"] is True
    assert registry["guardrails"]["watchlist_candidate_authority_forbidden"] is True
    assert registry["guardrails"]["transfer_package_beam_cutoff_forbidden"] is True
    assert registry["guardrails"]["full_universe_optimality_claim_requires_safe_pruning_proof"] is True
    assert registry["guardrails"]["legacy_package_audit_cannot_own_transfer_recommendation"] is True
    for relative in registry["required_equivalence_suites"]:
        assert (ROOT / relative).is_file(), relative


def test_runtime_artifact_authority_is_separate_from_source_seed():
    policy = _json("config/runtime_artifact_policy.json")
    manifest = _json("config/release_manifest.json")
    workflow = _text(".github/workflows/fpl-engine-core.yml")
    gitignore = _text(".gitignore")

    assert manifest["registries"]["runtime_artifact_authority"] == policy["registry"]
    assert manifest["runtime_branch"] == policy["runtime_branch"]["branch"]
    assert policy["source_branch"]["mutable_runtime_freshness_authority"] is False
    assert policy["runtime_branch"]["branch"] == "runtime-data-v4"
    assert policy["runtime_branch"]["mutable_runtime_freshness_authority"] is True
    assert policy["runtime_branch"]["publication_mode"] == "orphan_atomic_replace"
    assert policy["guardrails"]["file_exists_is_not_freshness_proof"] is True
    assert policy["guardrails"]["source_seed_cannot_override_runtime_snapshot"] is True

    assert 'RUNTIME_BRANCH: runtime-data-v4' in workflow
    assert 'git checkout --orphan runtime-snapshot' in workflow
    assert 'git rm -rf . >/dev/null 2>&1 || true' in workflow
    assert 'tar -C "$GITHUB_WORKSPACE" -cf "$RUNNER_TEMP/v4-runtime-data.tar" data' in workflow
    assert 'tar -xf "$RUNNER_TEMP/v4-runtime-publication/v4-runtime-data.tar"' in workflow
    assert 'git add -f data/' in workflow
    assert 'git push --force origin HEAD:"$RUNTIME_BRANCH"' in workflow
    assert 'environment: v4-runtime-publisher' in workflow
    assert 'actions/create-github-app-token@fee1f7d63c2ff003460e3d139729b119787bc349' in workflow
    assert 'app-id: ${{ vars.V4_RUNTIME_APP_ID }}' in workflow
    assert 'private-key: ${{ secrets.V4_RUNTIME_APP_PRIVATE_KEY }}' in workflow
    assert 'permission-contents: write' in workflow
    assert 'token: ${{ steps.runtime_app_token.outputs.token }}' in workflow
    assert "data/runtime/" in gitignore


def test_source_runtime_materializations_are_seed_only_not_freshness_authority():
    policy = _json("config/runtime_artifact_policy.json")
    runtime_materialization = policy["artifact_classes"]["runtime_materialization"]
    assert runtime_materialization["allowed_in_source_branch_as_seed_only"] is True
    assert runtime_materialization["current_authority_branch"] == "runtime-data-v4"
    assert runtime_materialization["freshness_must_be_proven_by_runtime_metadata"] is True
