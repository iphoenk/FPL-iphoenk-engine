from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shadow_cycle_is_reusable_and_pins_canonical_v5_checkout():
    workflow = _read(".github/workflows/v5-shadow-cycle.yml")
    assert "workflow_call:" in workflow
    assert "ref: v5-unified-engine" in workflow
    assert "config/v5_shadow_trigger.json" not in workflow


def test_manual_scheduler_calls_shadow_workflow_directly():
    workflow = _read(".github/workflows/v5-evidence-scheduler.yml")
    assert "uses: ./.github/workflows/v5-shadow-cycle.yml" in workflow
    assert "v5_dispatch_shadow_trigger.py" not in workflow
    assert "Enforce V5 canonical merged-PR provenance" in workflow
