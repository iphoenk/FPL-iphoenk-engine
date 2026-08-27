import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_contract_version_and_release_registry_are_explicit():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    services = json.loads((ROOT / "config/service_registry.json").read_text())
    source = (ROOT / "src/services/raw_snapshot_service.py").read_text()

    assert contracts["contracts"]["raw_snapshot"]["min_schema_version"] == 492
    assert '"schema_version": 492' in source
    assert services["architecture_version"] == "4.9.4.2"
    assert services["guardrails"]["advanced_ablation_observational_outside_decision_chain"] is True
    assert services["guardrails"]["advanced_ablation_full_shadow_parity_required"] is True
    assert services["guardrails"]["advanced_ablation_failure_cannot_block_core_publish"] is True


def test_redundant_manual_implementation_status_is_removed():
    assert not (ROOT / "IMPLEMENTATION_STATUS.json").exists()


def test_core_data_publish_precedes_strict_ablation_diagnostic():
    workflow = (ROOT / ".github/workflows/fpl-engine.yml").read_text()

    core_gate = workflow.index("Centralized V4.9.4.2 core quality gate")
    core_summary = workflow.index("Concise core acceptance summary")
    core_publish = workflow.index("Publish core branch data")
    ablation = workflow.index("Advanced enrichment ablation post-publish diagnostic gate")
    ablation_summary = workflow.index("Concise ablation diagnostic summary")
    ablation_publish = workflow.index("Publish ablation diagnostic data")

    assert core_gate < core_summary < core_publish < ablation < ablation_summary < ablation_publish
    assert "continue-on-error" not in workflow
    assert "assert a['ablation']['full_shadow_parity']['ok'] is True" in workflow
    assert "git add data/advanced_ablation_v4.json" in workflow
