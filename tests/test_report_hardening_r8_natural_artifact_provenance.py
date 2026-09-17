import pytest

from src.runtime_v6.wave3_artifact_provenance import (
    NaturalProofProvenanceError,
    validate_natural_proof_artifact_provenance,
)


REPOSITORY = "iphoenk/FPL-iphoenk-engine"
WORKFLOW_PATH = ".github/workflows/v6-wave3-proof.yml"


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
