import pytest

from src.runtime_v6.wave3_artifact_provenance import (
    NaturalProofProvenanceError,
    resolve_natural_source_run,
    validate_natural_proof_artifact_provenance,
)


REPOSITORY = "iphoenk/FPL-iphoenk-engine"
WORKFLOW_PATH = ".github/workflows/v6-wave3-proof.yml"
SOURCE_WORKFLOW_PATH = ".github/workflows/v6-natural-data-ingestion.yml"


def _artifact(**overrides):
    artifact = {
        "id": 7001,
        "name": "v6-wave3-slot-proof-9001-1",
        "expired": False,
        "workflow_run": {
            "id": 9001,
            "repository_id": 123,
            "head_repository_id": 123,
            "head_sha": "a" * 40,
        },
    }
    artifact.update(overrides)
    return artifact


def _producer_run(**overrides):
    run = {
        "id": 9001,
        "path": WORKFLOW_PATH,
        "event": "issues",
        "status": "completed",
        "conclusion": "success",
        "head_sha": "a" * 40,
        "repository": {"full_name": REPOSITORY, "id": 123},
        "head_repository": {"full_name": REPOSITORY, "id": 123},
    }
    run.update(overrides)
    return run


def _observer_run(**overrides):
    run = {
        "id": 8001,
        "path": WORKFLOW_PATH,
        "event": "issues",
        "created_at": "2026-09-17T08:28:06Z",
        "head_sha": "a" * 40,
        "repository": {"full_name": REPOSITORY, "id": 123},
        "head_repository": {"full_name": REPOSITORY, "id": 123},
    }
    run.update(overrides)
    return run


def _source_run(**overrides):
    run = {
        "id": 9001,
        "path": SOURCE_WORKFLOW_PATH,
        "event": "issues",
        "created_at": "2026-09-17T08:28:06Z",
        "head_sha": "a" * 40,
        "status": "in_progress",
        "conclusion": None,
        "run_attempt": 1,
        "display_title": "MUTABLE_CURRENT_ISSUE_TITLE",
        "repository": {"full_name": REPOSITORY, "id": 123},
        "head_repository": {"full_name": REPOSITORY, "id": 123},
    }
    run.update(overrides)
    return run


def test_resolves_source_by_immutable_event_fanout_not_mutable_display_title():
    stale_same_title = _source_run(
        id=8999,
        created_at="2026-09-17T05:28:17Z",
        display_title="MUTABLE_CURRENT_ISSUE_TITLE",
    )
    exact = _source_run(display_title="SOMETHING_ELSE_NOW")

    result = resolve_natural_source_run(
        observer_run=_observer_run(),
        source_runs=[stale_same_title, exact],
        expected_repository=REPOSITORY,
        expected_source_workflow_path=SOURCE_WORKFLOW_PATH,
    )

    assert result["id"] == 9001
    assert result["created_at"] == "2026-09-17T08:28:06Z"


def test_source_resolution_fails_closed_when_event_fanout_is_ambiguous():
    with pytest.raises(NaturalProofProvenanceError, match="ambiguous"):
        resolve_natural_source_run(
            observer_run=_observer_run(),
            source_runs=[_source_run(id=9001), _source_run(id=9002)],
            expected_repository=REPOSITORY,
            expected_source_workflow_path=SOURCE_WORKFLOW_PATH,
        )


def test_source_resolution_rejects_wrong_event_repo_or_head_sha():
    candidates = [
        _source_run(id=9001, event="workflow_dispatch"),
        _source_run(id=9002, head_sha="b" * 40),
        _source_run(
            id=9003,
            repository={"full_name": "attacker/repo", "id": 999},
            head_repository={"full_name": "attacker/repo", "id": 999},
        ),
    ]
    with pytest.raises(NaturalProofProvenanceError, match="no exact"):
        resolve_natural_source_run(
            observer_run=_observer_run(),
            source_runs=candidates,
            expected_repository=REPOSITORY,
            expected_source_workflow_path=SOURCE_WORKFLOW_PATH,
        )


def test_accepts_only_exact_governed_natural_producer_run():
    result = validate_natural_proof_artifact_provenance(
        artifact=_artifact(),
        producer_run=_producer_run(),
        expected_repository=REPOSITORY,
        expected_workflow_path=WORKFLOW_PATH,
    )
    assert result["valid"] is True
    assert result["producer_run_id"] == 9001
    assert result["event"] == "issues"


@pytest.mark.parametrize(
    ("run_overrides", "reason"),
    [
        ({"path": ".github/workflows/other.yml"}, "workflow"),
        ({"event": "workflow_dispatch"}, "event"),
        ({"event": "workflow_run"}, "event"),
        ({"event": "schedule"}, "event"),
        ({"status": "in_progress"}, "status"),
        ({"conclusion": "failure"}, "conclusion"),
        ({"repository": {"full_name": "attacker/repo", "id": 999}}, "repository"),
        ({"head_repository": {"full_name": "attacker/repo", "id": 999}}, "head_repository"),
    ],
)
def test_rejects_non_natural_or_wrong_producer(run_overrides, reason):
    with pytest.raises(NaturalProofProvenanceError, match=reason):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(),
            producer_run=_producer_run(**run_overrides),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )


def test_rejects_same_name_artifact_bound_to_different_run():
    artifact = _artifact(
        workflow_run={
            "id": 8999,
            "repository_id": 123,
            "head_repository_id": 123,
            "head_sha": "a" * 40,
        }
    )
    with pytest.raises(NaturalProofProvenanceError, match="run_id"):
        validate_natural_proof_artifact_provenance(
            artifact=artifact,
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )


def test_rejects_missing_workflow_run_binding():
    with pytest.raises(NaturalProofProvenanceError, match="workflow_run"):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(workflow_run=None),
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )


def test_rejects_expired_or_wrongly_named_artifact():
    with pytest.raises(NaturalProofProvenanceError, match="expired"):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(expired=True),
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )

    with pytest.raises(NaturalProofProvenanceError, match="artifact name"):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(name="v6-wave3-chaos-proof-9001-1"),
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )


def test_rejects_head_sha_or_repository_id_mismatch():
    with pytest.raises(NaturalProofProvenanceError, match="head_sha"):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(
                workflow_run={
                    "id": 9001,
                    "repository_id": 123,
                    "head_repository_id": 123,
                    "head_sha": "b" * 40,
                }
            ),
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )

    with pytest.raises(NaturalProofProvenanceError, match="repository_id"):
        validate_natural_proof_artifact_provenance(
            artifact=_artifact(
                workflow_run={
                    "id": 9001,
                    "repository_id": 999,
                    "head_repository_id": 999,
                    "head_sha": "a" * 40,
                }
            ),
            producer_run=_producer_run(),
            expected_repository=REPOSITORY,
            expected_workflow_path=WORKFLOW_PATH,
        )
