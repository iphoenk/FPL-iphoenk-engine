from __future__ import annotations

"""Fail-closed provenance validation for Wave 3 natural proof artifacts.

Artifact names are routing hints, not trust anchors. Natural-soak evidence is
countable only when the repository artifact is cryptographically associated by
GitHub metadata with the exact governed Wave 3 observer workflow run, and that
producer run is a completed successful natural issue event in this repository.
"""

from collections.abc import Mapping
from typing import Any


NATURAL_PROOF_ARTIFACT_PREFIX = "v6-wave3-slot-proof-"
NATURAL_PROOF_EVENT = "issues"


class NaturalProofProvenanceError(ValueError):
    """Raised when an artifact cannot be trusted as natural-soak evidence."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NaturalProofProvenanceError(f"missing or invalid {field}")
    return value


def _integer(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise NaturalProofProvenanceError(f"missing or invalid {field}") from exc
    if parsed <= 0:
        raise NaturalProofProvenanceError(f"missing or invalid {field}")
    return parsed


def _sha(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise NaturalProofProvenanceError(f"missing or invalid {field}")
    return text.lower()


def validate_natural_proof_artifact_provenance(
    *,
    artifact: Mapping[str, Any],
    producer_run: Mapping[str, Any],
    expected_repository: str,
    expected_workflow_path: str,
) -> dict[str, Any]:
    """Validate a candidate natural proof artifact against its GitHub run.

    The function intentionally rejects synthetic/manual/replay/chaos runs even
    if they reuse the natural artifact naming convention or forge proof JSON.
    """

    name = str(artifact.get("name") or "")
    if not name.startswith(NATURAL_PROOF_ARTIFACT_PREFIX):
        raise NaturalProofProvenanceError("artifact name is not a natural proof artifact")
    if artifact.get("expired") is True:
        raise NaturalProofProvenanceError("artifact is expired")

    artifact_run = _mapping(artifact.get("workflow_run"), "workflow_run")
    artifact_run_id = _integer(artifact_run.get("id"), "workflow_run.run_id")
    producer_run_id = _integer(producer_run.get("id"), "producer run_id")
    if artifact_run_id != producer_run_id:
        raise NaturalProofProvenanceError(
            f"artifact workflow run_id mismatch: artifact={artifact_run_id} producer={producer_run_id}"
        )

    workflow_path = str(producer_run.get("path") or "")
    if workflow_path != expected_workflow_path:
        raise NaturalProofProvenanceError(
            f"producer workflow mismatch: expected={expected_workflow_path!r} actual={workflow_path!r}"
        )

    event = str(producer_run.get("event") or "")
    if event != NATURAL_PROOF_EVENT:
        raise NaturalProofProvenanceError(
            f"producer event is not natural: expected={NATURAL_PROOF_EVENT!r} actual={event!r}"
        )

    status = str(producer_run.get("status") or "")
    if status != "completed":
        raise NaturalProofProvenanceError(f"producer status is not completed: {status!r}")
    conclusion = str(producer_run.get("conclusion") or "")
    if conclusion != "success":
        raise NaturalProofProvenanceError(f"producer conclusion is not success: {conclusion!r}")

    repository = _mapping(producer_run.get("repository"), "repository")
    repository_name = str(repository.get("full_name") or "")
    if repository_name != expected_repository:
        raise NaturalProofProvenanceError(
            f"producer repository mismatch: expected={expected_repository!r} actual={repository_name!r}"
        )

    head_repository = _mapping(producer_run.get("head_repository"), "head_repository")
    head_repository_name = str(head_repository.get("full_name") or "")
    if head_repository_name != expected_repository:
        raise NaturalProofProvenanceError(
            f"producer head_repository mismatch: expected={expected_repository!r} actual={head_repository_name!r}"
        )

    repository_id = _integer(repository.get("id"), "repository_id")
    head_repository_id = _integer(head_repository.get("id"), "head_repository_id")
    artifact_repository_id = _integer(artifact_run.get("repository_id"), "artifact repository_id")
    artifact_head_repository_id = _integer(
        artifact_run.get("head_repository_id"), "artifact head_repository_id"
    )
    if artifact_repository_id != repository_id:
        raise NaturalProofProvenanceError(
            f"artifact repository_id mismatch: artifact={artifact_repository_id} producer={repository_id}"
        )
    if artifact_head_repository_id != head_repository_id:
        raise NaturalProofProvenanceError(
            "artifact head_repository_id mismatch: "
            f"artifact={artifact_head_repository_id} producer={head_repository_id}"
        )
    if repository_id != head_repository_id:
        raise NaturalProofProvenanceError(
            f"producer repository_id/head_repository_id mismatch: {repository_id}!={head_repository_id}"
        )

    artifact_head_sha = _sha(artifact_run.get("head_sha"), "artifact head_sha")
    producer_head_sha = _sha(producer_run.get("head_sha"), "producer head_sha")
    if artifact_head_sha != producer_head_sha:
        raise NaturalProofProvenanceError(
            f"artifact head_sha mismatch: artifact={artifact_head_sha} producer={producer_head_sha}"
        )

    return {
        "valid": True,
        "artifact_id": _integer(artifact.get("id"), "artifact id"),
        "artifact_name": name,
        "producer_run_id": producer_run_id,
        "workflow_path": workflow_path,
        "event": event,
        "repository": repository_name,
        "head_sha": producer_head_sha,
    }
