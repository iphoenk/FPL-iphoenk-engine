import io
import json
import zipfile

import pytest

from src.runtime_v3 import runtime_hydration_guard as guard


def _zip_log(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("compute/19_Materialize.txt", text)
    return buffer.getvalue()


def _attestation() -> dict:
    return {
        "registry": "V3_RUNTIME_WORKFLOW_ATTESTATION_V1",
        "digest_contract": "MANIFEST_CORE_PLUS_DECLARED_PAYLOAD_V1",
        "workflow_name": "V3 Runtime",
        "workflow_run_id": 123456,
        "source_commit": "a" * 40,
        "snapshot_sha256": "b" * 64,
    }


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Runtime")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.test")


def test_immutable_attestation_survives_publish_job_rerun(monkeypatch):
    _production_env(monkeypatch)
    attestation = _attestation()
    expected_marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )

    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: {
            "id": attestation["workflow_run_id"],
            "name": "V3 Runtime",
            "head_branch": "main",
            "head_sha": attestation["source_commit"],
            "conclusion": "success",
            "run_attempt": 2,
        },
    )

    requested = []

    def fake_fetch_bytes(url: str) -> bytes:
        requested.append(url)
        if "/attempts/2/logs" in url:
            return _zip_log("publish-only rerun without compute attestation marker")
        if "/attempts/1/logs" in url:
            return _zip_log(expected_marker)
        raise AssertionError(f"unexpected log URL: {url}")

    monkeypatch.setattr(guard, "_fetch_bytes", fake_fetch_bytes)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result == {
        "workflow_run_success_verified": True,
        "immutable_log_attestation_verified": True,
    }
    assert any("/attempts/2/logs" in url for url in requested)
    assert any("/attempts/1/logs" in url for url in requested)


def test_immutable_attestation_still_rejects_when_marker_absent(monkeypatch):
    _production_env(monkeypatch)
    attestation = _attestation()

    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: {
            "id": attestation["workflow_run_id"],
            "name": "V3 Runtime",
            "head_branch": "main",
            "head_sha": attestation["source_commit"],
            "conclusion": "success",
            "run_attempt": 2,
        },
    )
    monkeypatch.setattr(guard, "_fetch_bytes", lambda url: _zip_log("no marker here"))

    with pytest.raises(RuntimeError, match="immutable workflow attestation marker missing"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_immutable_attestation_does_not_accept_failed_run(monkeypatch):
    _production_env(monkeypatch)
    attestation = _attestation()

    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: {
            "id": attestation["workflow_run_id"],
            "name": "V3 Runtime",
            "head_branch": "main",
            "head_sha": attestation["source_commit"],
            "conclusion": "failure",
            "run_attempt": 2,
        },
    )

    with pytest.raises(RuntimeError, match="did not complete successfully"):
        guard._verify_immutable_workflow_evidence(attestation)
