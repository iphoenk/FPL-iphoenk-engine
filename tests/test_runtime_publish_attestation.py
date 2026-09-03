from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3 import publication_verify
from src.runtime_v3 import publish_snapshot


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "runtime_publish_registry.json"
    path.write_text(
        json.dumps(
            {
                "registry": "RUNTIME_PUBLISH_REGISTRY_V1",
                "publish_paths": ["a.json", "runtime_manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    return path


def _wire_registry(monkeypatch: pytest.MonkeyPatch, registry: Path) -> None:
    monkeypatch.setattr(publish_snapshot, "REGISTRY_PATH", registry)
    monkeypatch.setattr(publication_verify, "REGISTRY_PATH", registry)


def test_runtime_materialization_embeds_verified_workflow_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _wire_registry(monkeypatch, registry)
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "a.json").write_text('{"x":1}\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Runtime")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    manifest = publish_snapshot.materialize(
        source, output, "fast_decision", "a" * 40
    )
    result = publication_verify.verify_publication(
        output / "data", source_commit="a" * 40, profile="fast_decision"
    )

    assert manifest["schema_version"] == 4
    assert manifest["attestation"]["registry"] == publish_snapshot.ATTESTATION_REGISTRY
    assert manifest["attestation"]["workflow_name"] == "V3 Runtime"
    assert manifest["attestation"]["workflow_run_id"] == 123456
    assert manifest["attestation"]["workflow_run_attempt"] == 2
    assert result["status"] == "PASS"
    assert result["embedded_attestation_verified"] is True
    assert result["workflow_run_id"] == 123456
    assert result["workflow_run_attempt"] == 2
    assert result["snapshot_sha256"] == manifest["attestation"]["snapshot_sha256"]


def test_package_precompute_materialization_embeds_its_workflow_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _wire_registry(monkeypatch, registry)
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "a.json").write_text('{"x":1}\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Package Precompute")
    monkeypatch.setenv("GITHUB_RUN_ID", "654321")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")

    manifest = publish_snapshot.materialize(
        source, output, "exhaustive_precompute", "d" * 40
    )
    result = publication_verify.verify_publication(
        output / "data", source_commit="d" * 40, profile="exhaustive_precompute"
    )

    assert manifest["schema_version"] == 4
    assert manifest["attestation"]["registry"] == publish_snapshot.ATTESTATION_REGISTRY
    assert manifest["attestation"]["workflow_name"] == "V3 Package Precompute"
    assert manifest["attestation"]["workflow_run_id"] == 654321
    assert manifest["attestation"]["workflow_run_attempt"] == 3
    assert result["status"] == "PASS"
    assert result["embedded_attestation_verified"] is True


def test_runtime_materialization_fails_closed_without_attempt_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _wire_registry(monkeypatch, registry)
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "a.json").write_text('{"x":1}\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Runtime")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)

    with pytest.raises(RuntimeError, match="GITHUB_RUN_ATTEMPT"):
        publish_snapshot.materialize(source, output, "fast_decision", "a" * 40)


def test_attestation_rejects_same_size_payload_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _wire_registry(monkeypatch, registry)
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "a.json").write_text('{"x":1}\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW", "V3 Runtime")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    publish_snapshot.materialize(source, output, "fast_decision", "b" * 40)
    published = output / "data" / "a.json"
    before_size = published.stat().st_size
    published.write_text('{"x":2}\n', encoding="utf-8")
    assert published.stat().st_size == before_size

    with pytest.raises(RuntimeError, match="content digest mismatch"):
        publication_verify.verify_publication(
            output / "data", source_commit="b" * 40, profile="fast_decision"
        )


def test_non_runtime_materialization_remains_legacy_bootstrap_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _wire_registry(monkeypatch, registry)
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "a.json").write_text('{"x":1}\n', encoding="utf-8")
    monkeypatch.delenv("GITHUB_WORKFLOW", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)

    manifest = publish_snapshot.materialize(
        source, output, "fast_decision", "c" * 40
    )
    result = publication_verify.verify_publication(
        output / "data", source_commit="c" * 40, profile="fast_decision"
    )

    assert manifest["schema_version"] == 2
    assert "attestation" not in manifest
    assert result["status"] == "PASS"
    assert result["embedded_attestation_verified"] is False
    assert result["workflow_run_attempt"] is None
