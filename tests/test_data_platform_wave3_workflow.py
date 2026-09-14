from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-wave3-proof.yml")


def test_wave3_observer_is_event_driven_and_never_a_scheduler_or_publisher():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" in text
    assert 'workflows: ["FPL V6 hourly fresh-data acquisition"]' in text
    assert "types: [completed]" in text
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "/v6-master-acquire" not in text
    assert "/v6-report-prefetch" not in text


def test_wave3_observer_is_bound_to_exact_triggering_workflow_run_and_attempt():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.workflow_run.id" in text
    assert "github.event.workflow_run.run_attempt" in text
    assert "github.event.workflow_run.head_sha" in text
    assert "v6-runtime-publication-${SOURCE_RUN_ID}-${SOURCE_RUN_ATTEMPT}" in text
    assert "--source-run-id" in text
    assert "--source-run-attempt" in text


def test_wave3_observer_only_counts_verified_natural_core_slots():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'control.get("schedule_kind") == "chatgpt_scheduler"' in text
    assert 'control.get("chatgpt_scheduler_proof") is True' in text
    assert 'control.get("counts_as_completed_operational_slot") is True' in text
    assert "candidate_freeze.lock" in text
    assert "runtime branch advanced or source run not promoted" in text
    assert "runtime branch attempt mismatch" in text


def test_wave3_observer_builds_proof_only_after_runtime_branch_match():
    text = WORKFLOW.read_text(encoding="utf-8")
    verify = text.index("Verify promoted runtime still matches source run")
    build = text.index("Build Wave 3 natural slot proof")
    upload = text.index("Upload Wave 3 natural slot proof")
    assert verify < build < upload
    assert "--production-validated" in text
    assert "v6-wave3-slot-proof-${{ github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}" in text


def test_wave3_observer_noops_on_successful_source_run_without_publication_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "No verified runtime publication artifact for source run; idempotent/no-publication source is not countable." in text
    assert "available=false" in text
    assert "if: steps.source_artifact.outputs.available == 'true'" in text
