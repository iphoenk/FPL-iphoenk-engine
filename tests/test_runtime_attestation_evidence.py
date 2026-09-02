from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3 import runtime_hydration_guard as guard


SOURCE_SHA = "a" * 40
DIGEST = "b" * 64
RUN_ID = 123456
JOB_ID = 654321


def _attestation() -> dict:
    return {
        "registry": guard.ATTESTATION_REGISTRY,
        "digest_contract": guard.ATTESTATION_DIGEST_CONTRACT,
        "workflow_name": guard.EXPECTED_WORKFLOW,
        "workflow_run_id": RUN_ID,
        "source_commit": SOURCE_SHA,
        "snapshot_sha256": DIGEST,
    }


def _job_log(attestation: dict, *, include_marker: bool = True) -> bytes:
    marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )
    return ((marker if include_marker else "no attestation here") + "\n").encode("utf-8")


def _wire_success(monkeypatch: pytest.MonkeyPatch, attestation: dict) -> None:
    monkeypatch.setattr(guard, "_production_actions_context", lambda: True)
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")

    def fake_json(url: str) -> dict:
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return {
                "id": RUN_ID,
                "name": guard.EXPECTED_WORKFLOW,
                "head_branch": "main",
                "head_sha": SOURCE_SHA,
                "conclusion": "success",
                "run_attempt": 2,
            }
        if f"/actions/runs/{RUN_ID}/jobs?" in url:
            return {
                "jobs": [
                    {
                        "id": JOB_ID - 1,
                        "name": "compute",
                        "run_id": RUN_ID,
                        "run_attempt": 1,
                        "conclusion": "failure",
                    },
                    {
                        "id": JOB_ID,
                        "name": "compute",
                        "run_id": RUN_ID,
                        "run_attempt": 2,
                        "conclusion": "success",
                    },
                ]
            }
        raise AssertionError(f"unexpected json URL: {url}")

    monkeypatch.setattr(guard, "_fetch_json", fake_json)
    monkeypatch.setattr(guard, "_fetch_bytes", lambda url: _job_log(attestation))


def test_immutable_workflow_evidence_accepts_exact_successful_compute_job_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result["workflow_run_success_verified"] is True
    assert result["immutable_log_attestation_verified"] is True


def test_immutable_workflow_evidence_uses_successful_rerun_compute_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)
    requested = []

    def fake_bytes(url: str) -> bytes:
        requested.append(url)
        assert url.endswith(f"/actions/jobs/{JOB_ID}/logs")
        return _job_log(attestation)

    monkeypatch.setattr(guard, "_fetch_bytes", fake_bytes)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result["immutable_log_attestation_verified"] is True
    assert requested == [
        f"https://api.github.com/repos/iphoenk/FPL-iphoenk-engine/actions/jobs/{JOB_ID}/logs"
    ]


def test_immutable_workflow_evidence_rejects_unsuccessful_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)

    def fake_json(url: str) -> dict:
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return {
                "id": RUN_ID,
                "name": guard.EXPECTED_WORKFLOW,
                "head_branch": "main",
                "head_sha": SOURCE_SHA,
                "conclusion": "failure",
            }
        raise AssertionError(f"unexpected json URL: {url}")

    monkeypatch.setattr(guard, "_fetch_json", fake_json)

    with pytest.raises(RuntimeError, match="did not complete successfully"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_immutable_workflow_evidence_rejects_missing_exact_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)
    monkeypatch.setattr(
        guard,
        "_fetch_bytes",
        lambda url: _job_log(attestation, include_marker=False),
    )

    with pytest.raises(RuntimeError, match="immutable workflow attestation marker missing"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_immutable_workflow_evidence_rejects_no_successful_compute_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attestation = _attestation()
    _wire_success(monkeypatch, attestation)

    def fake_json(url: str) -> dict:
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return {
                "id": RUN_ID,
                "name": guard.EXPECTED_WORKFLOW,
                "head_branch": "main",
                "head_sha": SOURCE_SHA,
                "conclusion": "success",
            }
        if f"/actions/runs/{RUN_ID}/jobs?" in url:
            return {
                "jobs": [
                    {
                        "id": JOB_ID,
                        "name": "compute",
                        "run_id": RUN_ID,
                        "run_attempt": 2,
                        "conclusion": "failure",
                    }
                ]
            }
        raise AssertionError(f"unexpected json URL: {url}")

    monkeypatch.setattr(guard, "_fetch_json", fake_json)

    with pytest.raises(RuntimeError, match="immutable workflow attestation marker missing"):
        guard._verify_immutable_workflow_evidence(attestation)


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
