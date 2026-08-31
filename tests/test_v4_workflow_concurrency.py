from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_pr_validation_cannot_cancel_production_scheduler() -> None:
    gate = (WORKFLOWS / "fpl-engine.yml").read_text(encoding="utf-8")
    assert "fpl-iphoenk-v4-pr-{0}" in gate
    assert "|| 'fpl-iphoenk-v4-gate'" in gate
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in gate


def test_non_default_canonical_branch_has_no_duplicate_scheduled_owner() -> None:
    recovery = (WORKFLOWS / "fpl-engine-recovery.yml").read_text(encoding="utf-8")
    assert "schedule:" not in recovery
    assert "cron:" not in recovery
    assert "uses: ./.github/workflows/fpl-engine-core.yml" in recovery
    assert "cancel-in-progress: false" in recovery
    assert not (WORKFLOWS / "fpl-engine-timing-probe.yml").exists()
