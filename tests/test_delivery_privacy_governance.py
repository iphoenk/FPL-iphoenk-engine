from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p6_workflow_is_zero_cost_bounded_and_not_scheduler_authority():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-p6-warm-worker.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow
    assert "workflow_run:" not in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "timeout-minutes: 350" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref_name == 'main'" in workflow
    assert "FPL_MASTER_SLOT" not in workflow
    assert "/v6-master-acquire" not in workflow
    assert "actions/upload-artifact" not in workflow


def test_p6_private_plane_is_explicit_and_no_public_manager_artifact_exists():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-p6-warm-worker.yml"
    ).read_text(encoding="utf-8")
    assert "repository: iphoenk/fpl-reports-private" in workflow
    assert "FPL_PRIVATE_REPORTS_TOKEN" in workflow
    assert "FPL_V12_PRIVATE_CACHE_KEY_B64" in workflow
    assert "persist-credentials: true" in workflow
    assert "v12_p6_runtime" in workflow
    assert "app/artifacts/v12-p6-public" in workflow
    assert "upload-artifact" not in workflow


def test_dp2_wires_p6_without_becoming_scheduler_or_natural_proof():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-precompute-control.yml"
    ).read_text(encoding="utf-8")
    assert "issue_comment:" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow
    assert "p6-warm:" in workflow
    assert "uses: ./.github/workflows/v12-p6-warm-worker.yml" in workflow
    assert 'plan["counts_as_core_slot"] is False' in workflow
    assert 'plan["advances_scheduler_proof"] is False' in workflow
