"""No live FPL account or real secrets: local bare Git repository tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from src.runtime_v6.domains.acquisition import git_oidc_store as module
from src.runtime_v6.domains.acquisition.rotating_oidc import (
    Credential, RotatingCredentialManager, RotationBlocked,
)


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    bare = tmp_path / "private.git"
    git("init", "--bare", str(bare))
    repo = tmp_path / "private"
    git("clone", str(bare), str(repo))
    git("config", "user.name", "fixture", cwd=repo)
    git("config", "user.email", "fixture@example.test", cwd=repo)
    git("checkout", "-b", "main", cwd=repo)
    (repo / "README.md").write_text("fixture only\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-m", "fixture", cwd=repo)
    git("push", "-u", "origin", "main", cwd=repo)
    original = module._git

    def safe_git(root, *args, **kwargs):
        if args[:2] == ("remote", "get-url"):
            return b"https://github.com/iphoenk/fpl-reports-private.git\n"
        return original(root, *args, **kwargs)

    monkeypatch.setattr(module, "_git", safe_git)
    key = Fernet.generate_key().decode()
    return bare, repo, key


def test_remote_git_timeout_is_bounded_and_diagnostic(monkeypatch, tmp_path):
    timeouts = []

    def fake_run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    for action, expected in (("fetch", 90), ("push", 90), ("show", 35)):
        with pytest.raises(RotationBlocked, match="CREDENTIAL_STORE_GIT_TIMEOUT"):
            module._git(tmp_path, action, "origin", "main")
        assert timeouts[-1] == expected


def test_encrypted_cas_first_version_and_readback(checkout):
    bare, repo, key = checkout
    store = module.EncryptedGitCredentialStore(str(repo), key)
    assert store.load().version == 0
    first = store.compare_and_swap(0, Credential(1, "READY", "dummy-refresh-secret-1234567890123456"))
    assert first.version == 1
    assert store.load().refresh_token == "dummy-refresh-secret-1234567890123456"
    blob = git("--git-dir", str(bare), "show", "main:.auth-private/fpl-oidc-credential.enc")
    assert b"dummy-refresh" not in blob
    history = git("--git-dir", str(bare), "log", "-p", "--all")
    assert b"dummy-refresh" not in history


def test_cas_push_uses_authenticated_parent_checkout(checkout, monkeypatch):
    _, repo, key = checkout
    actual_pushes = []
    original = module._git

    def record_push(directory, *args, **kwargs):
        if args and args[0] == "push":
            actual_pushes.append((Path(directory).resolve(), args[-1]))
        return original(directory, *args, **kwargs)

    monkeypatch.setattr(module, "_git", record_push)
    store = module.EncryptedGitCredentialStore(str(repo), key)
    store.compare_and_swap(0, Credential(1, "READY", "dummy-refresh-value"))
    assert len(actual_pushes) == 1
    checkout_root, refspec = actual_pushes[0]
    assert checkout_root == repo.resolve()
    assert refspec.endswith(":refs/heads/main")
    assert not refspec.startswith("HEAD:")
    assert store.load().phase == "READY"


def test_cas_conflict_rejects_stale_writer(checkout):
    _, repo, key = checkout
    store = module.EncryptedGitCredentialStore(str(repo), key)
    store.compare_and_swap(0, Credential(1, "READY", "refresh-placeholder"))
    with pytest.raises(RotationBlocked, match="CAS_VERSION_CONFLICT"):
        store.compare_and_swap(0, Credential(1, "READY", "another-placeholder"))


def test_wrong_encryption_key_fails_closed(checkout):
    _, repo, key = checkout
    store = module.EncryptedGitCredentialStore(str(repo), key)
    store.compare_and_swap(0, Credential(1, "READY", "refresh-placeholder"))
    other = module.EncryptedGitCredentialStore(str(repo), Fernet.generate_key().decode())
    with pytest.raises(RotationBlocked, match="DECRYPTION"):
        other.load()


def test_restart_refresh_persistence_and_worker_reuse(checkout):
    _, repo, key = checkout
    initial = module.EncryptedGitCredentialStore(str(repo), key)
    initial.compare_and_swap(0, Credential(1, "READY", "dummy-refresh-start"))
    class Provider:
        calls = 0
        def post(self, url, **kwargs):
            self.calls += 1
            assert kwargs["allow_redirects"] is False
            return type("R", (), {"status_code": 200, "json": lambda self: {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
            }})()
    provider = Provider()
    def manager():
        return RotatingCredentialManager(
            store=module.EncryptedGitCredentialStore(str(repo), key),
            lease=module.CASLease(),
            token_url="https://account.premierleague.com/as/token",
            approved_host="account.premierleague.com",
            client_id="test-client",
            contract_verified=True,
            http=provider,
            clock=lambda: 1000,
        )
    assert manager().get_access_token() == "new-access-token"
    assert manager().get_access_token() == "new-access-token"
    assert provider.calls == 1
    assert initial.load().refresh_token == "new-refresh-token"


def test_crash_after_marker_blocks_future_grants(checkout):
    _, repo, key = checkout
    store = module.EncryptedGitCredentialStore(str(repo), key)
    store.compare_and_swap(0, Credential(1, "READY", "dummy-start"))
    stored = store.load()
    store.compare_and_swap(stored.version, Credential(stored.version + 1, "IN_FLIGHT", "dummy-start"))
    assert store.load().phase == "IN_FLIGHT"


def test_wrong_repo_remote_is_rejected(tmp_path, checkout, monkeypatch):
    _, repo, key = checkout
    monkeypatch.setattr(module, "_git", lambda root, *args, **kwargs: b"https://github.com/iphoenk/FPL-iphoenk-engine.git\n" if args[:2] == ("remote", "get-url") else b"")
    with pytest.raises(RotationBlocked, match="WRONG_REMOTE"):
        module.EncryptedGitCredentialStore(str(repo), key)


def test_two_distinct_runners_cannot_both_claim_grant(checkout, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    bare, repo, key = checkout
    one = module.EncryptedGitCredentialStore(str(repo), key)
    one.compare_and_swap(0, Credential(1, "READY", "dummy-refresh-original"))
    second_dir = tmp_path / "runner-two"
    git("clone", "--branch", "main", str(bare), str(second_dir))
    two = module.EncryptedGitCredentialStore(str(second_dir), key)
    barrier = Barrier(2)

    def claim(store, ident):
        state = store.load()
        assert state.version == 1
        barrier.wait(timeout=5)
        try:
            store.compare_and_swap(
                state.version,
                Credential(state.version + 1, "IN_FLIGHT", state.refresh_token,
                           transaction_id=f"distinct-claim-{ident}"),
            )
            return "CLAIMED"
        except RotationBlocked:
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcome = list(workers.map(lambda pair: claim(*pair), ((one, "one"), (two, "two"))))
    assert sorted(outcome) == ["BLOCKED", "CLAIMED"]
    assert one.load().phase == "IN_FLIGHT"


def test_existing_ciphertext_read_failure_is_not_empty_enrollment(checkout, monkeypatch):
    _, repo, key = checkout
    store = module.EncryptedGitCredentialStore(str(repo), key)
    store.compare_and_swap(0, Credential(1, "READY", "dummy-refresh-existing"))
    real = module._git

    def unreadable(root, *args, **kwargs):
        if args[:1] == ("show",):
            raise RotationBlocked("CREDENTIAL_STORE_GIT_OPERATION_FAILED")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(module, "_git", unreadable)
    with pytest.raises(RotationBlocked, match="GIT_OPERATION_FAILED"):
        store.load()


def test_sparse_cas_worktree_keeps_noncredential_private_tree_untouched(checkout, monkeypatch):
    """An auth update must not materialize the bulky private report tree."""
    bare, repo, key = checkout
    report = repo / "reports" / "large-private-artifact.bin"
    report.parent.mkdir(parents=True)
    report_payload = b"immutable-private-report-fixture" * 32768
    report.write_bytes(report_payload)
    git("add", "--", "reports/large-private-artifact.bin", cwd=repo)
    git("commit", "-m", "fixture large private report", cwd=repo)
    git("push", "origin", "main", cwd=repo)

    original_git = module._git
    observed = {"no_checkout": False, "sparse": False, "credential_only": False}

    def inspect_git(root, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            observed["no_checkout"] = "--no-checkout" in args
        if args[:2] == ("sparse-checkout", "set"):
            observed["sparse"] = args[-1] == ".auth-private/fpl-oidc-credential.enc"
        result = original_git(root, *args, **kwargs)
        if args[:2] == ("checkout", "-f") and Path(root).resolve() != repo.resolve():
            assert (Path(root) / ".auth-private" / "fpl-oidc-credential.enc").exists()
            assert not (Path(root) / "reports" / "large-private-artifact.bin").exists()
            observed["credential_only"] = True
        return result

    monkeypatch.setattr(module, "_git", inspect_git)
    store = module.EncryptedGitCredentialStore(str(repo), key)
    stored = store.compare_and_swap(0, Credential(1, "READY", "dummy-private-fixture-token"))
    assert stored.phase == "READY"
    assert stored.version == 1
    assert all(observed.values()), observed
    assert git("--git-dir", str(bare), "show", "main:reports/large-private-artifact.bin") == report_payload
    assert store.load().refresh_token == "dummy-private-fixture-token"


def test_git_timeout_emits_allowlisted_verb_without_arguments(monkeypatch, tmp_path, capsys):
    """Only an operation category, never a private path, reaches logs."""
    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", timed_out)
    with pytest.raises(RotationBlocked, match="CREDENTIAL_STORE_GIT_TIMEOUT"):
        module._git(tmp_path, "worktree", "add", "--no-checkout", "secret-private-path")
    captured = capsys.readouterr().out
    assert "OIDC_GIT_TIMEOUT_OPERATION=worktree" in captured
    assert "secret-private-path" not in captured
