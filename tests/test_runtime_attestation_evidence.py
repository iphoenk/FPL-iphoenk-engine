from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from src.runtime_v3 import runtime_hydration_guard as guard


SOURCE_SHA = "a" * 40
DIGEST = "b" * 64
RUN_ID = 123456
RUN_ATTEMPT = 1


def _attestation(workflow_name: str = guard.EXPECTED_WORKFLOW) -> dict:
    return {
        "registry": guard.ATTESTATION_REGISTRY,
        "digest_contract": guard.ATTESTATION_DIGEST_CONTRACT,
        "workflow_name": workflow_name,
        "workflow_run_id": RUN_ID,
        "workflow_run_attempt": RUN_ATTEMPT,
        "source_commit": SOURCE_SHA,
        "snapshot_sha256": DIGEST,
    }


def _logs(attestation: dict, *, include_marker: bool = True) -> bytes:
    marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "compute/19_Materialize.txt",
            (marker if include_marker else "no attestation here") + "\n",
        )
    return buf.getvalue()


def _wire_success(monkeypatch: pytest.MonkeyPatch, attestation: dict) -> None:
    monkeypatch.setattr(guard, "_production_actions_context", lambda: True)
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: {
            "id": RUN_ID,
            "name": attestation["workflow_name"],
            "head_branch": "main",
            "head_sha": SOURCE_SHA,
            "conclusion": "success",
            "run_attempt": RUN_ATTEMPT,
        },
    )
    monkeypatch.setattr(guard, "_fetch_bytes", lambda url: _logs(attestation))


def test_immutable_workflow_evidence_accepts_exact_successful_run_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result["workflow_run_success_verified"] is True
    assert result["immutable_log_attestation_verified"] is True
    assert result["workflow_run_attempt"] == RUN_ATTEMPT
    assert result["legacy_attempt_migration"] is False


def test_immutable_workflow_evidence_accepts_package_precompute_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation("V3 Package Precompute")
    _wire_success(monkeypatch, attestation)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result["workflow_run_success_verified"] is True
    assert result["immutable_log_attestation_verified"] is True
    assert result["workflow_run_attempt"] == RUN_ATTEMPT


def test_immutable_workflow_evidence_rejects_unsuccessful_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)
    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: {
            "id": RUN_ID,
            "name": guard.EXPECTED_WORKFLOW,
            "head_branch": "main",
            "head_sha": SOURCE_SHA,
            "conclusion": "failure",
            "run_attempt": RUN_ATTEMPT,
        },
    )

    with pytest.raises(RuntimeError, match="attempt did not complete successfully"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_immutable_workflow_evidence_rejects_missing_exact_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)
    monkeypatch.setattr(
        guard,
        "_fetch_bytes",
        lambda url: _logs(attestation, include_marker=False),
    )

    with pytest.raises(RuntimeError, match="immutable workflow attestation marker missing"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_embedded_attestation_rejects_unapproved_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_production_actions_context", lambda: True)
    manifest = {
        "schema_version": 4,
        "source_commit": SOURCE_SHA,
        "publication": {"paths": []},
        "attestation": _attestation("V3 CI"),
    }

    with pytest.raises(RuntimeError, match="attestation workflow mismatch"):
        guard._verify_embedded_attestation(Path("."), manifest, [])


def test_production_actions_rejects_legacy_unattested_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_production_actions_context", lambda: True)
    manifest = {
        "schema_version": 2,
        "source_commit": SOURCE_SHA,
        "publication": {"paths": []},
    }

    with pytest.raises(RuntimeError, match="production snapshot attestation required"):
        guard._verify_embedded_attestation(Path("."), manifest, [])
