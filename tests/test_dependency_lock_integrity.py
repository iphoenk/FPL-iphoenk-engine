from __future__ import annotations

from pathlib import Path

import pytest

from tools.validate_dependency_locks import validate_lock, validate_lock_set


VALID_HASH = "a" * 64
OTHER_HASH = "b" * 64


def test_repository_dependency_locks_are_exact_and_sha256_hashed():
    result = validate_lock_set([Path("requirements.lock"), Path("requirements-ci.lock")])
    assert result["status"] == "PASS"
    assert result["all_exact_pins"] is True
    assert result["all_sha256_hashed"] is True
    assert result["require_hashes_enabled"] is True
    assert result["direct_url_or_vcs_sources"] == 0
    assert int(result["unique_requirements"]) >= 20


def test_missing_hash_fails_closed(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("--require-hashes\nexample==1.0\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash missing"):
        validate_lock(lock)


def test_missing_require_hashes_directive_fails_closed(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"example==1.0 --hash=sha256:{VALID_HASH}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must enable --require-hashes"):
        validate_lock(lock)


def test_unpinned_or_direct_url_dependency_fails_closed(tmp_path):
    unpinned = tmp_path / "unpinned.lock"
    unpinned.write_text(f"--require-hashes\nexample>=1.0 --hash=sha256:{VALID_HASH}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="exact == pin"):
        validate_lock(unpinned)

    direct = tmp_path / "direct.lock"
    direct.write_text("--require-hashes\nexample @ https://example.invalid/pkg.whl\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="non-deterministic dependency source forbidden"):
        validate_lock(direct)


def test_conflicting_nested_lock_entry_fails_closed(tmp_path):
    runtime = tmp_path / "runtime.lock"
    runtime.write_text(f"--require-hashes\nexample==1.0 --hash=sha256:{VALID_HASH}\n", encoding="utf-8")
    ci = tmp_path / "ci.lock"
    ci.write_text(f"--require-hashes\nexample==1.0 --hash=sha256:{OTHER_HASH}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dependency lock conflict"):
        validate_lock_set([runtime, ci])
