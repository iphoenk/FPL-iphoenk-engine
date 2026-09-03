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


def _legacy_attestation() -> dict:
    return {
        "registry": guard.ATTESTATION_REGISTRY_V1,
        "digest_contract": "MANIFEST_CORE_PLUS_DECLARED_PAYLOAD_V1",
        "workflow_name": "V3 Runtime",
        "workflow_run_id": 123456,
        "source_commit": "a" * 40,
        "snapshot_sha256": "b" * 64,
    }


def _attempt_attestation(attempt: int = 1) -> dict:
    return {
        "registry": guard.ATTESTATION_REGISTRY,
        "digest_contract": "MANIFEST_CORE_PLUS_DECLARED_PAYLOAD_V1",
        "workflow_name": "V3 Runtime",
        "workflow_run_id": 123456,
        "workflow_run_attempt": attempt,
        "source_commit": "a" * 40,
        "snapshot_sha256": "b" * 64,
    }


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Runtime")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.test")


def _metadata(attestation: dict, attempt: int, conclusion: str) -> dict:
    return {
        "id": attestation["workflow_run_id"],
        "name": "V3 Runtime",
        "head_branch": "main",
        "head_sha": attestation["source_commit"],
        "conclusion": conclusion,
        "run_attempt": attempt,
    }


def test_legacy_attestation_survives_later_failed_rerun(monkeypatch):
    _production_env(monkeypatch)
    attestation = _legacy_attestation()
    expected_marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )

    def fake_fetch_json(url: str) -> dict:
        if url.endswith("/actions/runs/123456"):
            return _metadata(attestation, 2, "failure")
        if url.endswith("/attempts/1"):
            return _metadata(attestation, 1, "success")
        if url.endswith("/attempts/2"):
            return _metadata(attestation, 2, "failure")
        raise AssertionError(f"unexpected metadata URL: {url}")

    monkeypatch.setattr(guard, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(
        guard,
        "_fetch_bytes",
        lambda url: _zip_log(expected_marker) if "/attempts/1/logs" in url else _zip_log("no marker"),
    )

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result == {
        "workflow_run_success_verified": True,
        "immutable_log_attestation_verified": True,
        "workflow_run_attempt": 1,
        "legacy_attempt_migration": True,
    }


def test_legacy_attestation_rejects_missing_marker(monkeypatch):
    _production_env(monkeypatch)
    attestation = _legacy_attestation()

    def fake_fetch_json(url: str) -> dict:
        if url.endswith("/actions/runs/123456"):
            return _metadata(attestation, 2, "failure")
        attempt = 1 if url.endswith("/attempts/1") else 2
        return _metadata(attestation, attempt, "success" if attempt == 1 else "failure")

    monkeypatch.setattr(guard, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(guard, "_fetch_bytes", lambda url: _zip_log("no marker here"))

    with pytest.raises(RuntimeError, match="immutable workflow attestation marker missing"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_legacy_attestation_rejects_ambiguous_matching_attempts(monkeypatch):
    _production_env(monkeypatch)
    attestation = _legacy_attestation()
    expected_marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )

    def fake_fetch_json(url: str) -> dict:
        if url.endswith("/actions/runs/123456"):
            return _metadata(attestation, 2, "failure")
        attempt = 1 if url.endswith("/attempts/1") else 2
        return _metadata(attestation, attempt, "success")

    monkeypatch.setattr(guard, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(guard, "_fetch_bytes", lambda url: _zip_log(expected_marker))

    with pytest.raises(RuntimeError, match="attempt is ambiguous"):
        guard._verify_immutable_workflow_evidence(attestation)


def test_attempt_aware_attestation_verifies_only_exact_attempt(monkeypatch):
    _production_env(monkeypatch)
    attestation = _attempt_attestation(1)
    expected_marker = guard.ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )
    requested = []

    def fake_fetch_json(url: str) -> dict:
        requested.append(url)
        assert url.endswith("/actions/runs/123456/attempts/1")
        return _metadata(attestation, 1, "success")

    def fake_fetch_bytes(url: str) -> bytes:
        requested.append(url)
        assert url.endswith("/actions/runs/123456/attempts/1/logs")
        return _zip_log(expected_marker)

    monkeypatch.setattr(guard, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(guard, "_fetch_bytes", fake_fetch_bytes)

    result = guard._verify_immutable_workflow_evidence(attestation)

    assert result == {
        "workflow_run_success_verified": True,
        "immutable_log_attestation_verified": True,
        "workflow_run_attempt": 1,
        "legacy_attempt_migration": False,
    }
    assert all("/attempts/1" in url for url in requested)


def test_attempt_aware_attestation_rejects_failed_exact_attempt(monkeypatch):
    _production_env(monkeypatch)
    attestation = _attempt_attestation(2)
    monkeypatch.setattr(
        guard,
        "_fetch_json",
        lambda url: _metadata(attestation, 2, "failure"),
    )

    with pytest.raises(RuntimeError, match="attempt did not complete successfully"):
        guard._verify_immutable_workflow_evidence(attestation)
