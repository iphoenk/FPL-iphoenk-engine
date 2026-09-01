import json
from pathlib import Path

import pytest

from src.runtime_v3 import precompute_checkpoint
from src.runtime_v3 import runtime_hydration_guard as guard


SOURCE_SHA = "a" * 40
RUNTIME_SHA = "b" * 40


def _manifest(paths=None):
    paths = paths or ["a.json", "nested/b.json"]
    return {
        "schema_version": 2,
        "registry": "RUNTIME_MANIFEST_V1",
        "source_commit": SOURCE_SHA,
        "publication": {
            "registry": "RUNTIME_PUBLISH_REGISTRY_V1",
            "paths": paths,
            "file_count_without_manifest": len(paths),
            "file_count": len(paths) + 1,
        },
    }


def _wire_git(
    monkeypatch,
    *,
    manifest=None,
    tree_paths=None,
    parentful=False,
    ancestry=True,
    author=guard.EXPECTED_BOT_EMAIL,
    committer=guard.EXPECTED_BOT_EMAIL,
    subject=guard.EXPECTED_SUBJECT,
):
    manifest = manifest or _manifest()
    tree_paths = tree_paths or [
        "data/a.json",
        "data/nested/b.json",
        "data/runtime_manifest.json",
    ]

    def fake_ok(root: Path, *args: str) -> bool:
        if args[:3] == ("show-ref", "--verify", "--quiet"):
            return True
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ancestry
        raise AssertionError(f"unexpected git ok args: {args}")

    def fake_text(root: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return RUNTIME_SHA
        if args[0] == "rev-list":
            return f"{RUNTIME_SHA} {'c' * 40}" if parentful else RUNTIME_SHA
        if args[:3] == ("show", "-s", "--format=%ae"):
            return author
        if args[:3] == ("show", "-s", "--format=%ce"):
            return committer
        if args[:3] == ("show", "-s", "--format=%s"):
            return subject
        if args[:3] == ("ls-tree", "-r", "--name-only"):
            return "\n".join(tree_paths)
        raise AssertionError(f"unexpected git text args: {args}")

    def fake_bytes(root: Path, *args: str) -> bytes:
        if args[0] == "show" and args[1].endswith(":data/runtime_manifest.json"):
            return json.dumps(manifest).encode("utf-8")
        raise AssertionError(f"unexpected git bytes args: {args}")

    monkeypatch.setattr(guard, "_git_ok", fake_ok)
    monkeypatch.setattr(guard, "_git_text", fake_text)
    monkeypatch.setattr(guard, "_git_bytes", fake_bytes)


def test_runtime_hydration_guard_accepts_governed_parentless_snapshot(monkeypatch):
    _wire_git(monkeypatch)
    result = guard.verify_runtime_snapshot(Path("."))
    assert result["status"] == "PASS"
    assert result["runtime_commit"] == RUNTIME_SHA
    assert result["canonical_source_sha"] == SOURCE_SHA
    assert result["parentless_snapshot"] is True
    assert result["publication_whitelist_verified"] is True


def test_runtime_hydration_guard_rejects_non_parentless_snapshot(monkeypatch):
    _wire_git(monkeypatch, parentful=True)
    with pytest.raises(RuntimeError, match="parentless"):
        guard.verify_runtime_snapshot(Path("."))


def test_runtime_hydration_guard_rejects_non_data_tree(monkeypatch):
    _wire_git(
        monkeypatch,
        tree_paths=[
            "README.md",
            "data/a.json",
            "data/nested/b.json",
            "data/runtime_manifest.json",
        ],
    )
    with pytest.raises(RuntimeError, match="non-data paths"):
        guard.verify_runtime_snapshot(Path("."))


def test_runtime_hydration_guard_rejects_manifest_tree_drift(monkeypatch):
    _wire_git(monkeypatch, manifest=_manifest(["a.json"]))
    with pytest.raises(RuntimeError, match="whitelist mismatch"):
        guard.verify_runtime_snapshot(Path("."))


def test_runtime_hydration_guard_rejects_noncanonical_source(monkeypatch):
    _wire_git(monkeypatch, ancestry=False)
    with pytest.raises(RuntimeError, match="canonical checkout ancestry"):
        guard.verify_runtime_snapshot(Path("."))


def test_precompute_gates_runtime_before_collector(monkeypatch):
    order = []
    monkeypatch.setattr(
        precompute_checkpoint,
        "verify_runtime_snapshot",
        lambda: order.append("guard") or {"status": "PASS"},
    )
    monkeypatch.setattr(
        precompute_checkpoint.collector_gate,
        "main",
        lambda: order.append("collector") or 0,
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.delenv("FPL_SCHEDULE_EXPR", raising=False)

    assert precompute_checkpoint.main() == 0
    assert order == ["guard", "collector"]
