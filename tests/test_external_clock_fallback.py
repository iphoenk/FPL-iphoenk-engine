from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / ".github" / "workflows" / "fpl-external-clock-fallback.yml"
V6 = ROOT / ".github" / "workflows" / "v6-natural-data-ingestion.yml"
ORCH = ROOT / ".github" / "workflows" / "fpl-master-occurrence-orchestrator.yml"


def test_external_clock_entrypoint_is_dispatch_only_and_non_natural():
    text = ENTRY.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "\n  schedule:" not in text
    assert "mode=master_orchestrated" in text
    assert "reason=EXTERNAL_CLOCK_FALLBACK" in text
    assert "scheduler_authority=EXTERNAL_CLOCK_FALLBACK" in text
    assert "natural_proof=false" in text


def test_v6_dispatch_exposes_governed_master_orchestrated_fallback():
    text = V6.read_text(encoding="utf-8")
    assert "          - master_orchestrated" in text
    assert "V6_DISPATCH_LOGICAL_SLOT: ${{ inputs.logical_slot }}" in text


def test_occurrence_orchestrator_accepts_external_fallback_without_new_cron():
    text = ORCH.read_text(encoding="utf-8")
    assert "inputs.scheduler_authority == 'EXTERNAL_CLOCK_FALLBACK'" in text
    assert "\n  schedule:" not in text
