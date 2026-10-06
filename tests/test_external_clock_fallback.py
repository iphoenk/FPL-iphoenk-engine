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
    assert "gh run watch" in text
    assert "Exact external-clock V6 child run was not created" in text


def test_v6_dispatch_exposes_governed_master_orchestrated_fallback():
    text = V6.read_text(encoding="utf-8")
    assert "          - master_orchestrated" in text
    assert "V6_DISPATCH_LOGICAL_SLOT: ${{ inputs.logical_slot }}" in text


def test_occurrence_orchestrator_accepts_external_fallback_without_new_cron():
    text = ORCH.read_text(encoding="utf-8")
    assert "inputs.scheduler_authority == 'EXTERNAL_CLOCK_FALLBACK'" in text
    assert "\n  schedule:" not in text

def test_github_clock_smoke_trigger_is_owner_only_and_non_natural():
    text = (ROOT / ".github" / "workflows" / "fpl-github-clock.yml").read_text(encoding="utf-8")
    assert "issue_comment:" in text
    assert "github.event.issue.number == 431" in text
    assert "github.actor == github.repository_owner" in text
    assert "github.event.comment.body == '/fpl-clock-test'" in text
    assert "github.event_name == 'schedule' && 'true' || 'false'" in text

def test_clock_run_discovery_uses_real_jq_not_unsupported_gh_formatter_flags():
    clock = (ROOT / ".github" / "workflows" / "fpl-github-clock.yml").read_text(encoding="utf-8")
    fallback = ENTRY.read_text(encoding="utf-8")
    for text in (clock, fallback):
        assert "--jq --arg" not in text
        assert "| jq -r --arg" in text


def test_master_dispatch_uses_governed_timestamp_parser():
    control = (ROOT / "src" / "runtime_v6" / "domains" / "control_plane" / "workflow_control.py").read_text(
        encoding="utf-8"
    )
    assert 'label="master_orchestrated logical_slot"' in control
    assert "_parse_dt(" not in control

