from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-wave3-proof.yml")
INVENTORY = Path("src/runtime_v6/wave3_artifact_inventory.py")


def test_wave3_observer_uses_bounded_producer_workflow_artifacts():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    inventory = INVENTORY.read_text(encoding="utf-8")
    assert workflow.count("python -m src.runtime_v6.wave3_artifact_inventory") == 2
    assert "wave3_artifact_inventory prior" in workflow
    assert "wave3_artifact_inventory chaos" in workflow
    assert 'gh api --paginate --slurp' not in workflow
    assert '"v6-wave3-proof.yml", "issues", 60' in inventory
    assert '"v6-ci.yml", "push", 40' in inventory
    assert "/actions/workflows/{workflow}/runs" in inventory
    assert "/actions/runs/{run_id}/artifacts?per_page=100" in inventory


def test_wave3_observer_never_uses_global_first_page_artifact_inventory():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    inventory = INVENTORY.read_text(encoding="utf-8")
    assert 'actions/artifacts?per_page=100' not in workflow
    assert 'actions/artifacts?per_page=100' not in inventory
    assert '"artifact / producing workflow run mismatch"' in inventory
