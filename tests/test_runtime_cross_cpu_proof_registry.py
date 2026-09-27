from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-governance.yml"
PROOF = ROOT / "config" / "performance" / "v12_runtime_cross_cpu_proof.json"


def test_frozen_cross_cpu_registry_points_to_direct_multi_cpu_proof():
    proof = json.loads(PROOF.read_text(encoding="utf-8"))
    assert proof["authority"] == "FPL_V12_RUNTIME_CROSS_CPU_FROZEN_PROOF"
    assert proof["proof_mode"] == "DIRECT_CURRENT_HEAD_MULTI_CPU"
    assert len(proof["proof_head"]) == 40
    assert int(proof["proof_run_id"]) > 0
    assert int(proof["distinct_physical_cpu_models"]) >= 2
    assert len(proof["output_sha256"]) == 64
    assert proof["runtime_cache_identity"]["openblas_num_threads"] == 1


def test_governance_revalidates_registry_against_github_run_and_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions: read" in text
    assert "actions/runs/${PROOF_RUN}" in text
    assert "actions/runs/${PROOF_RUN}/artifacts?per_page=100" in text
    assert "actions/artifacts/${artifact_id}/zip" in text
    assert 'run.get("status") != "completed"' in text
    assert 'run.get("conclusion") != "success"' in text
    assert 'run.get("head_sha") != proof["proof_head"]' in text
    assert 'accepted.get("proof_mode") == "DIRECT_CURRENT_HEAD_MULTI_CPU"' in text
    assert 'accepted.get("current_head") == proof["proof_head"]' in text
    assert 'accepted.get("output_sha256") == proof["output_sha256"]' in text


def test_transitive_proof_requires_ancestry_semantic_identity_and_runtime_output_identity():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'git merge-base --is-ancestor "$PROOF_HEAD" "$HEAD_SHA"' in text
    assert 'git diff --quiet "$PROOF_HEAD" "$HEAD_SHA" -- "${SEMANTIC_PATHS[@]}"' in text
    assert "and proof_is_ancestor" in text
    assert "and semantic_unchanged" in text
    assert "and current_runtime == baseline_runtime_key" in text
    assert "and current_output == baseline_output" in text
    assert '"VERIFIED_TRANSITIVE_DIRECT_PROOF"' in text


def test_semantic_change_still_requires_direct_current_head_multi_cpu():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "direct_multi_cpu = len(models) >= 2" in text
    assert '"DIRECT_CURRENT_HEAD_MULTI_CPU"' in text
    assert "if not direct_multi_cpu and not verified_transitive:" in text
    assert "semantic_unchanged=false" in text
