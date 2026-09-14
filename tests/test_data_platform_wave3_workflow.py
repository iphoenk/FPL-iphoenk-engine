from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-wave3-proof.yml")


def test_wave3_observer_uses_natural_issue_title_event_not_scheduler_or_workflow_chaining():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "issues:" in text
    assert "types: [edited]" in text
    assert "FPL_MASTER_SLOT " in text
    assert "workflow_run:" not in text
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "/v6-master-acquire" not in text
    assert "/v6-report-prefetch" not in text


def test_wave3_observer_reuses_existing_governed_title_authorization():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.issue.number == 431" in text
    assert "github.actor == github.repository_owner" in text
    assert "github.event.changes.title" in text
    assert "workflow_control authorize-issue-edit" in text


def test_wave3_observer_resolves_exact_source_run_from_unique_title():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "TARGET_TITLE: ${{ github.event.issue.title }}" in text
    assert "v6-natural-data-ingestion.yml/runs?event=issues" in text
    assert 'run.get("display_title") == os.environ["TARGET_TITLE"]' in text
    assert "run_id={run['id']}" in text
    assert "run_attempt={run.get('run_attempt', 1)}" in text
    assert "head_sha={run.get('head_sha', '')}" in text


def test_wave3_observer_requires_successful_collect_publish_and_fulfillment_before_proof():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'collect = jobs.get("collect")' in text
    assert 'publish = jobs.get("publish")' in text
    assert 'fulfillment = jobs.get("orchestration-fulfillment")' in text
    assert 'collect != "success" or fulfillment != "success"' in text
    assert 'countable = publish == "success"' in text
    assert 'publish not in {"success", "skipped"}' in text


def test_wave3_observer_binds_proof_to_exact_immutable_source_publication_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "v6-runtime-publication-${SOURCE_RUN_ID}-${SOURCE_RUN_ATTEMPT}" in text
    assert "expected exactly one immutable source publication artifact" in text
    assert "gh run download \"$SOURCE_RUN_ID\"" in text
    assert "--source-run-id \"${{ steps.source.outputs.run_id }}\"" in text
    assert "--source-run-attempt \"${{ steps.source.outputs.run_attempt }}\"" in text
    assert "--source-commit \"${{ steps.source.outputs.head_sha }}\"" in text
    assert "--production-validated" in text
    assert "--promotion-verified" in text


def test_wave3_observer_uploads_proof_but_never_mutates_runtime_tree():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Upload Wave 3 natural slot proof" in text
    assert "v6-wave3-slot-proof-${{ steps.source.outputs.run_id }}-${{ steps.source.outputs.run_attempt }}" in text
    assert "runtime-data-v6" not in text
    assert "git push" not in text
    assert "contents: write" not in text


def test_wave3_observer_noops_on_idempotent_source_publish_skip():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Source natural slot was an idempotent no-op; no new publication proof is counted." in text
    assert "if: steps.promotion.outputs.countable == 'false'" in text
