from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v6 import publish_integrity, store


def _repoint_store(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    health = root / "health"
    freeze = health / "candidate_freeze.lock"
    monkeypatch.setattr(store, "OUT", root)
    monkeypatch.setattr(store, "HEALTH", health)
    monkeypatch.setattr(store, "CANDIDATE_FREEZE", freeze)
    monkeypatch.setattr(
        store,
        "_POST_FREEZE_WRITABLE",
        {freeze, health / "publish_integrity.json"},
    )
    return freeze


def test_current_run_freeze_rejects_post_freeze_data_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    freeze = _repoint_store(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "1001")

    store.write_json(freeze, {"candidate_state": "FROZEN", "run_id": "1001"})

    with pytest.raises(RuntimeError, match="candidate_frozen_write_rejected:manifest.json"):
        store.write_json(tmp_path / "manifest.json", {"should": "fail"})

    store.write_json(tmp_path / "health" / "publish_integrity.json", {"status": "PASS"})
    assert store.read_json(tmp_path / "health" / "publish_integrity.json") == {"status": "PASS"}


def test_previous_run_freeze_does_not_block_new_acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    freeze = _repoint_store(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "1002")
    freeze.parent.mkdir(parents=True, exist_ok=True)
    freeze.write_text(json.dumps({"candidate_state": "FROZEN", "run_id": "1001"}), encoding="utf-8")

    store.write_json(tmp_path / "manifest.json", {"new_run": True})

    assert store.read_json(tmp_path / "manifest.json") == {"new_run": True}


def test_frozen_candidate_validator_is_read_only_and_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1003")
    payload = tmp_path / "current" / "official_fpl.json"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text('{"source_id":"official_fpl","value":1}\n', encoding="utf-8")

    digest, count = publish_integrity._candidate_tree_digest(tmp_path)
    freeze = tmp_path / "health" / "candidate_freeze.lock"
    freeze.parent.mkdir(parents=True, exist_ok=True)
    freeze.write_text(
        json.dumps(
            {
                "candidate_state": "FROZEN",
                "run_id": "1003",
                "run_attempt": "1",
                "candidate_generation_id": "1003:1:test",
                "candidate_tree_sha256": digest,
                "artifact_count": count,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        publish_integrity,
        "validate_publish_tree",
        lambda root: {
            "schema_version": 4,
            "status": "PASS",
            "errors": [],
            "tree_sha256": "validator-tree",
        },
    )

    before, before_count = publish_integrity._candidate_tree_digest(tmp_path)
    report = publish_integrity.validate_frozen_candidate(tmp_path)
    after, after_count = publish_integrity._candidate_tree_digest(tmp_path)

    assert report["status"] == "PASS"
    assert report["freeze_verified"] is True
    assert before == after == digest
    assert before_count == after_count == count

    payload.write_text('{"source_id":"official_fpl","value":2}\n', encoding="utf-8")
    drifted = publish_integrity.validate_frozen_candidate(tmp_path)

    assert drifted["status"] == "FAIL"
    assert "candidate_tree_changed_after_freeze" in drifted["errors"]
    assert drifted["freeze_verified"] is False
