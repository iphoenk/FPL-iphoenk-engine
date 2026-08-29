from __future__ import annotations

import hashlib

from src.runtime_v3 import incremental_reuse
from src.utils import ROOT


def _clear() -> None:
    incremental_reuse._digest_source_tree.cache_clear()


def test_github_sha_is_used_as_precomputed_source_identity(monkeypatch):
    sha = "a" * 40
    monkeypatch.delenv("FPL_DEPLOYMENT_CODE_DIGEST", raising=False)
    monkeypatch.setenv("GITHUB_SHA", sha)
    _clear()
    expected = hashlib.sha256(f"git:{sha}".encode("utf-8")).hexdigest()
    assert incremental_reuse._digest_source_tree(str((ROOT / "src").resolve())) == expected
    identity = incremental_reuse.source_tree_identity()
    assert identity["source"] == "GITHUB_SHA"
    assert identity["precomputed"] is True
    assert identity["digest_prefix"] == expected[:12]


def test_explicit_deployment_digest_has_priority(monkeypatch):
    digest = "b" * 64
    monkeypatch.setenv("FPL_DEPLOYMENT_CODE_DIGEST", digest)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    _clear()
    assert incremental_reuse._digest_source_tree(str((ROOT / "src").resolve())) == digest
    assert incremental_reuse.source_tree_identity()["source"] == "FPL_DEPLOYMENT_CODE_DIGEST"


def test_invalid_deployment_identity_falls_back_to_source_tree_hash(monkeypatch, tmp_path):
    monkeypatch.setenv("FPL_DEPLOYMENT_CODE_DIGEST", "not-a-digest")
    monkeypatch.setenv("GITHUB_SHA", "also-invalid")
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text("x = 1\n", encoding="utf-8")
    _clear()
    first = incremental_reuse._digest_source_tree(str(source.resolve()))
    (source / "a.py").write_text("x = 2\n", encoding="utf-8")
    _clear()
    second = incremental_reuse._digest_source_tree(str(source.resolve()))
    assert first != second
    identity = incremental_reuse.source_tree_identity()
    assert identity["source"] == "SOURCE_TREE_HASH"
    assert identity["precomputed"] is False
