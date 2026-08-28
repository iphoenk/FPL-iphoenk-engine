import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_contract_version_and_release_registry_are_explicit():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    services = json.loads((ROOT / "config/service_registry.json").read_text())
    release = json.loads((ROOT / "config/release_manifest.json").read_text())
    source = (ROOT / "src/services/raw_snapshot_service.py").read_text()

    min_version = int(contracts["contracts"]["raw_snapshot"]["min_schema_version"])
    match = re.search(r'"schema_version"\s*:\s*(\d+)', source)
    assert match is not None
    assert int(match.group(1)) >= min_version
    assert services["architecture_version"] == release["release"]
    assert services["guardrails"]["advanced_ablation_observational_outside_decision_chain"] is True
    assert services["guardrails"]["advanced_ablation_full_shadow_parity_required"] is True
    assert services["guardrails"]["advanced_ablation_failure_cannot_block_core_publish"] is True


def test_redundant_manual_implementation_status_is_removed():
    assert not (ROOT / "IMPLEMENTATION_STATUS.json").exists()


def test_core_data_publish_precedes_strict_ablation_diagnostic():
    workflow = (ROOT / ".github/workflows/fpl-engine-core.yml").read_text()

    core_gate = workflow.index("Centralized V4 core quality gate")
    core_summary = workflow.index("Core acceptance summary")
    core_publish = workflow.index("Publish core branch data")
    ablation = workflow.index("Advanced enrichment ablation post-publish diagnostic gate")
    ablation_publish = workflow.index("Publish ablation diagnostic data")

    assert core_gate < core_summary < core_publish < ablation < ablation_publish
    assert "continue-on-error" not in workflow
    assert "assert a['ablation']['full_shadow_parity']['ok'] is True" in workflow
    assert "git add data/advanced_ablation_v4.json" in workflow
