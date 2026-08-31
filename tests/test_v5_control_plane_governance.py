import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_AUTHORITY = "v5-shadow-runtime:data/v5/shadow/acceptance_summary.json"


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_runtime_acceptance_has_one_declared_evidence_authority():
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    parity = _load("config/v5_capability_parity_registry.json")
    status = _load("IMPLEMENTATION_STATUS.json")
    assert manifest["operational_acceptance_evidence"]["authority"] == EVIDENCE_AUTHORITY
    assert manifest["operational_acceptance_evidence"]["materialized_status_snapshot_only"] is True
    assert manifest["production_promotion"]["operational_evidence_authority"] == EVIDENCE_AUTHORITY
    assert manifest["production_promotion"]["materialized_status_snapshot_only"] is True
    assert acceptance["convergence"]["operational_acceptance_evidence_authority"] == EVIDENCE_AUTHORITY
    assert acceptance["convergence"]["static_acceptance_counters_must_not_be_runtime_authority"] is True
    assert parity["governance"]["operational_acceptance_evidence_authority"] == EVIDENCE_AUTHORITY
    assert status["acceptance"]["authority"] == EVIDENCE_AUTHORITY
    assert status["acceptance"]["materialized_status_snapshot_only"] is True


def test_on_demand_uses_deployed_runtime_source_and_registry_hydration():
    source = (ROOT / ".github/workflows/v5-on-demand-report.yml").read_text(encoding="utf-8")
    assert "data/runtime_manifest.json" in source
    assert "['source_commit']" in source
    assert 'git merge-base --is-ancestor "$SOURCE_SHA"' in source
    assert "runtime_publish_registry.json" in source
    assert "hydrate_paths" in source
    assert 'SOURCE_SHA=$(git rev-parse "origin/$PRODUCTION_SOURCE_BRANCH")' not in source
    assert "for file in price_cache.json" not in source
    assert "for stat_file in" not in source


def test_v5_branch_scheduler_has_no_dead_cron_and_delegates_policy_to_script():
    workflow = (ROOT / ".github/workflows/v5-evidence-scheduler.yml").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/v5_evidence_scheduler_gate.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "scripts/v5_dispatch_shadow_trigger.py").read_text(encoding="utf-8")
    assert "  schedule:" not in workflow
    assert "v5_evidence_scheduler_gate.py" in workflow
    assert "v5_dispatch_shadow_trigger.py" in workflow
    assert "production_main_sha" in gate
    assert "data/runtime_manifest.json" in gate
    assert "merge-base" in gate
    assert "config/v5_shadow_trigger.json" in dispatch
    assert "default-branch-thin-dispatcher" in dispatch
