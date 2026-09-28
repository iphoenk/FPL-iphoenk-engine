from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p6_workflow_is_dispatch_only_zero_cost_and_not_scheduler_authority():
    workflow = (ROOT / ".github" / "workflows" / "v12-p6-warm-worker.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow
    assert "workflow_run:" not in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "timeout-minutes: 350" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref_name == 'main'" in workflow
    assert "FPL_MASTER_SLOT" not in workflow
    assert "/v6-master-acquire" not in workflow


def test_p6_private_plane_never_publishes_manager_plaintext_publicly():
    workflow = (ROOT / ".github" / "workflows" / "v12-p6-warm-worker.yml").read_text(encoding="utf-8")
    assert "repository: iphoenk/fpl-reports-private" in workflow
    assert "FPL_PRIVATE_REPORTS_TOKEN" in workflow
    assert "FPL_V12_PRIVATE_CACHE_KEY_B64" in workflow
    assert "actions/upload-artifact" not in workflow
    assert "git push origin HEAD:main" not in workflow
