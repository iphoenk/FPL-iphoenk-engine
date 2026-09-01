from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.services import runtime_hydration_guard as guard

ROOT = Path(__file__).resolve().parents[1]


def test_reference_modules_cannot_write_canonical_artifacts():
    for relative in (
        "src/engines/v4_wc_package_audit.py",
        "src/engines/v4_lineup_optimizer.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "atomic_json(" not in text, relative


def test_runtime_policy_declares_fail_closed_hydration_gate_and_external_ruleset():
    policy = json.loads((ROOT / "config/runtime_artifact_policy.json").read_text())
    runtime = policy["runtime_branch"]
    gate = runtime["hydration_integrity_gate"]
    assert gate["mode"] == "FAIL_CLOSED_BEFORE_SERVICE_EXECUTION"
    assert all(value is True for key, value in gate.items() if key.startswith("requires_"))
    platform = runtime["platform_write_protection"]
    assert platform["authority"] == "GITHUB_BRANCH_RULESET"
    assert platform["external_admin_control_required"] is True


def test_orchestrator_verifies_runtime_before_architecture_and_services():
    text = (ROOT / "src/services/orchestrator.py").read_text(encoding="utf-8")
    assert text.index("verify_hydrated_runtime_if_required(root=root)") < text.index("architecture_guard_service.run()")
    assert '"runtime_hydration_assurance": runtime_hydration_assurance' in text


def test_runtime_artifact_policy_is_architecture_attested():
    text = (ROOT / "src/services/architecture_guard_service.py").read_text(encoding="utf-8")
    assert 'CONFIG / "runtime_artifact_policy.json"' in text
    assert 'checks["reference_modules_read_only"]' in text


def test_runtime_guard_accepts_governed_snapshot_and_rejects_tamper(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "runtime").mkdir(parents=True)
    snapshot = b'{"snapshot":"governed"}\n'
    source = "a" * 40
    provenance = {
        "schema_version": 1,
        "contract": "V4_RUNTIME_PROVENANCE_V1",
        "canonical_source_sha": source,
        "runtime_branch": "runtime-data-v4",
        "repository": "iphoenk/FPL-iphoenk-engine",
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
    }
    latest = {"runtime_provenance": provenance}
    (data / "runtime_provenance_v4.json").write_text(json.dumps(provenance))
    (data / "runtime" / "snapshot.v1.json").write_bytes(snapshot)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    monkeypatch.setattr(guard, "DATA", data)
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "_git_ok", lambda _root, *args: True)

    def text(_root, *args):
        joined = " ".join(args)
        if "rev-parse" in joined: return "b" * 40
        if "rev-list" in joined: return "b" * 40
        if "--format=%ae" in joined or "--format=%ce" in joined: return guard.EXPECTED_BOT_EMAIL
        if "--format=%s" in joined: return guard.EXPECTED_SUBJECT
        if "ls-tree" in joined: return "data/latest.json\ndata/runtime_provenance_v4.json\ndata/runtime/snapshot.v1.json"
        raise AssertionError(joined)

    def binary(_root, *args):
        target = args[-1]
        if target.endswith("runtime_provenance_v4.json"): return json.dumps(provenance).encode()
        if target.endswith("latest.json"): return json.dumps(latest).encode()
        if target.endswith("snapshot.v1.json"): return snapshot
        raise AssertionError(target)

    monkeypatch.setattr(guard, "_git_text", text)
    monkeypatch.setattr(guard, "_git_bytes", binary)
    result = guard.verify_hydrated_runtime_if_required(root=tmp_path)
    assert result["status"] == "PASS"
    assert result["automation_commit_metadata_matches"] is True
    assert result["publisher_identity_requires_platform_ruleset"] is True
    assert "automation_identity" not in result
    (data / "runtime" / "snapshot.v1.json").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="workspace snapshot differs"):
        guard.verify_hydrated_runtime_if_required(root=tmp_path)
