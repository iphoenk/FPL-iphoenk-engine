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


def test_wave3_observer_resolves_exact_source_run_from_immutable_event_fanout():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'actions/runs/${GITHUB_RUN_ID}' in text
    assert "v6-natural-data-ingestion.yml/runs?event=issues" in text
    assert "resolve_natural_source_run" in text
    assert 'expected_source_workflow_path=".github/workflows/v6-natural-data-ingestion.yml"' in text
    assert "TARGET_TITLE" not in text
    assert 'run.get("display_title") == ' not in text
    assert "run_id={run['id']}" in text
    assert "run_attempt={run.get('run_attempt', 1)}" in text
    assert "head_sha={run.get('head_sha', '')}" in text


def test_wave3_observer_requires_successful_collect_publish_and_fulfillment_before_proof():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'collect_row = jobs.get("collect") or {}' in text
    assert 'publish_row = jobs.get("publish") or {}' in text
    assert 'fulfillment_row = jobs.get("orchestration-fulfillment") or {}' in text
    assert 'collect != "success" or fulfillment != "success"' in text
    assert 'countable = publish == "success"' in text
    assert '"collect_job_id": collect_row.get("id")' in text
    assert '"publish_job_id": publish_row.get("id")' in text
    assert '"fulfillment_job_id": fulfillment_row.get("id")' in text
    assert 'publish not in {"success", "skipped"}' in text


def test_wave3_observer_binds_proof_to_exact_immutable_source_publication_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "v6-runtime-publication-${SOURCE_RUN_ID}-${SOURCE_RUN_ATTEMPT}" in text
    assert "expected exactly one immutable source publication artifact" in text
    assert "gh run download \"$SOURCE_RUN_ID\"" in text
    assert "--source-run-id \"${{ steps.source.outputs.run_id }}\"" in text
    assert "--source-run-attempt \"${{ steps.source.outputs.run_attempt }}\"" in text
    assert "--collect-job-id \"${{ steps.promotion.outputs.collect_job_id }}\"" in text
    assert "--publish-job-id \"${{ steps.promotion.outputs.publish_job_id }}\"" in text
    assert "--fulfillment-job-id \"${{ steps.promotion.outputs.fulfillment_job_id }}\"" in text
    assert "--source-commit \"${{ steps.source.outputs.head_sha }}\"" in text
    assert "--production-validated" in text
    assert "--promotion-verified" in text


def test_wave3_observer_binds_source_generation_to_exact_published_runtime_commit():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Resolve exact published runtime commit" in text
    assert "/branches/runtime-data-v6" in text
    assert "candidate_freeze.lock?ref={sha}" in text
    assert "runtime-freeze-history.json" in text
    assert "resolve_published_runtime_commit" in text
    assert "branch_advanced_after_publication" in text
    assert 'freeze.get("run_id")' in text
    assert 'freeze.get("run_attempt")' in text
    assert "expected_freeze_bytes=source_bytes" in text
    assert "--published-runtime-sha \"${{ steps.runtime.outputs.sha }}\"" in text


def test_wave3_observer_aggregates_only_immutable_prior_slot_proof_artifacts():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Collect prior immutable Wave 3 slot proofs" in text
    assert 'name.startswith("v6-wave3-slot-proof-")' in text
    assert "rows = rows[:64]" not in text
    assert "accepted_proof_count=0" in text
    assert "accepted_proof_count=$((accepted_proof_count + 1))" in text
    assert "if (( accepted_proof_count >= 64 )); then" in text
    assert "gh run download \"$proof_run_id\"" in text
    assert "python -m src.runtime_v6.wave3_window" in text
    assert "--current \"$RUNNER_TEMP/wave3-slot-proof.json\"" in text
    assert "v6-wave3-window-${{ steps.source.outputs.run_id }}-${{ steps.source.outputs.run_attempt }}" in text


def test_wave3_observer_verifies_github_producer_run_before_downloading_prior_proof():
    text = WORKFLOW.read_text(encoding="utf-8")
    artifact_lookup = 'gh api "/repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}"'
    run_lookup = 'gh api "/repos/${GITHUB_REPOSITORY}/actions/runs/${proof_run_id}"'
    guard = "validate_natural_proof_artifact_provenance"
    download = 'gh run download "$proof_run_id"'
    assert artifact_lookup in text
    assert run_lookup in text
    assert "from src.runtime_v6.wave3_artifact_provenance import" in text
    assert guard in text
    assert 'expected_workflow_path=".github/workflows/v6-wave3-proof.yml"' in text
    assert text.index(artifact_lookup) < text.index(guard) < text.index(download)
    assert text.index(run_lookup) < text.index(guard)


def test_wave3_observer_caps_only_after_provenance_and_download_acceptance():
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = text.index("validate_natural_proof_artifact_provenance")
    copy = text.index('cp "$target/wave3-slot-proof.json"')
    increment = text.index("accepted_proof_count=$((accepted_proof_count + 1))")
    cap = text.index("if (( accepted_proof_count >= 64 )); then")
    assert guard < copy < increment < cap


def test_wave3_observer_uploads_proof_but_never_mutates_runtime_tree():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Upload Wave 3 natural slot proof" in text
    assert "Upload Wave 3 proof-window summary" in text
    assert "v6-wave3-slot-proof-${{ steps.source.outputs.run_id }}-${{ steps.source.outputs.run_attempt }}" in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "git commit" not in text
    assert "git checkout runtime-data-v6" not in text


def test_wave3_observer_noops_on_idempotent_source_publish_skip():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Source natural slot was an idempotent no-op; no new publication proof is counted." in text
    assert "if: steps.promotion.outputs.countable == 'false'" in text


def test_wave3_immutable_runtime_publication_lookup_survives_newer_branch_generation():
    import json
    from src.runtime_v6.wave3_artifact_provenance import resolve_published_runtime_commit

    source = json.dumps({"run_id": 101, "run_attempt": 1}, sort_keys=True).encode()
    other = json.dumps({"run_id": 202, "run_attempt": 1}, sort_keys=True).encode()
    current = "b" * 40
    natural = "a" * 40
    result = resolve_published_runtime_commit(
        candidate_commits=[{"sha": current}, {"sha": natural}],
        expected_freeze_bytes=source,
        source_run_id=101,
        source_run_attempt=1,
        read_remote_freeze_bytes=lambda sha: {current: other, natural: source}[sha],
    )
    assert result == natural


def test_wave3_immutable_runtime_publication_fails_closed_if_natural_commit_missing():
    import json
    import pytest
    from src.runtime_v6.wave3_artifact_provenance import (
        NaturalProofProvenanceError, resolve_published_runtime_commit,
    )

    source = json.dumps({"run_id": 101, "run_attempt": 1}).encode()
    with pytest.raises(NaturalProofProvenanceError, match="no immutable source commit"):
        resolve_published_runtime_commit(
            candidate_commits=[{"sha": "b" * 40}],
            expected_freeze_bytes=source,
            source_run_id=101,
            source_run_attempt=1,
            read_remote_freeze_bytes=lambda _: b'{"run_id":202,"run_attempt":1}',
        )
    with pytest.raises(NaturalProofProvenanceError, match="lock identity mismatch"):
        resolve_published_runtime_commit(
            candidate_commits=[{"sha": "a" * 40}],
            expected_freeze_bytes=source,
            source_run_id=999,
            source_run_attempt=1,
            read_remote_freeze_bytes=lambda _: source,
        )
