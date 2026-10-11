"""Encrypted, durable OIDC credentials in the existing private Git repository.

Git fast-forward push is the global compare-and-swap lock. Each refresh first
pushes an encrypted IN_FLIGHT marker. Another runner cannot claim the same
version; a crashed worker fails closed until explicitly re-enrolled.
Only ciphertext is committed. The Fernet encryption key is supplied exclusively
by a protected Actions environment secret, never by the repository.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

from .rotating_oidc import Credential, RotationBlocked

_CREDENTIAL_PATH = ".auth-private/fpl-oidc-credential.enc"
_APPROVED_REPO = "iphoenk/fpl-reports-private"


def _git(repo: Path, *args: str, allow_missing: bool = False) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=35, stdin=subprocess.DEVNULL,
        )
    except Exception:
        raise RotationBlocked("CREDENTIAL_STORE_GIT_UNAVAILABLE") from None
    if completed.returncode != 0:
        if allow_missing and completed.returncode == 128:
            return b""
        # No stderr/stdout: remote URL or error strings might contain secrets.
        raise RotationBlocked("CREDENTIAL_STORE_GIT_OPERATION_FAILED")
    return completed.stdout


class EncryptedGitCredentialStore:
    def __init__(self, directory: str, key: str) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir() or not (self.directory / ".git").exists():
            raise RotationBlocked("CREDENTIAL_STORE_CHECKOUT_UNAVAILABLE")
        try:
            self.fernet = Fernet(key.encode("ascii"))
        except Exception:
            raise RotationBlocked("CREDENTIAL_STORE_ENCRYPTION_KEY_INVALID") from None
        remote = _git(self.directory, "remote", "get-url", "origin").decode("utf-8", errors="replace")
        # Fail closed to the *known private* repository; avoid misleading
        # credential state from a public or unrelated repository.
        sanitized = remote.strip().removesuffix(".git")
        if not (
            sanitized == "https://github.com/" + _APPROVED_REPO
            or sanitized == "git@github.com:" + _APPROVED_REPO
            or sanitized.endswith("@github.com/" + _APPROVED_REPO)
        ):
            raise RotationBlocked("CREDENTIAL_STORE_WRONG_REMOTE")

    def _latest_revision(self) -> str:
        _git(self.directory, "fetch", "--quiet", "--no-tags", "origin", "main")
        return _git(self.directory, "rev-parse", "refs/remotes/origin/main").decode("ascii").strip()

    def _read(self, revision: str) -> Credential:
        raw = _git(
            self.directory, "show", f"{revision}:{_CREDENTIAL_PATH}",
            allow_missing=True,
        )
        if not raw:
            return Credential(version=0, phase="EMPTY", refresh_token="")
        try:
            payload = json.loads(self.fernet.decrypt(raw.strip()).decode("utf-8"))
            result = Credential(
                version=payload["version"], phase=payload["phase"],
                refresh_token=payload["refresh_token"],
                access_token=payload.get("access_token", ""),
                expires_at=payload.get("expires_at", 0),
                transaction_id=payload.get("transaction_id", ""),
            )
            if type(result.version) is not int or result.version < 1:
                raise ValueError("invalid_version")
            if result.phase not in {"READY", "IN_FLIGHT"}:
                raise ValueError("invalid_phase")
            return result
        except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError):
            raise RotationBlocked("CREDENTIAL_STORE_DECRYPTION_OR_SCHEMA_INVALID") from None

    def load(self) -> Credential:
        return self._read(self._latest_revision())

    def compare_and_swap(self, expected_version: int, proposed: Credential) -> Credential:
        revision = self._latest_revision()
        current = self._read(revision)
        if current.version != expected_version:
            raise RotationBlocked("CREDENTIAL_STORE_CAS_VERSION_CONFLICT")
        value = Credential(
            version=expected_version + 1, phase=proposed.phase,
            refresh_token=proposed.refresh_token,
            access_token=proposed.access_token,
            expires_at=proposed.expires_at,
            transaction_id=proposed.transaction_id,
        )
        if value.phase not in {"READY", "IN_FLIGHT"} or not value.refresh_token:
            raise RotationBlocked("CREDENTIAL_STORE_INVALID_TRANSITION")
        encrypted = self.fernet.encrypt(
            json.dumps(
                {
                    "version": value.version, "phase": value.phase,
                    "refresh_token": value.refresh_token,
                    "access_token": value.access_token,
                    "expires_at": value.expires_at,
                    "transaction_id": value.transaction_id,
                }, separators=(",", ":"), sort_keys=True,
            ).encode("utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="fpl-oidc-encrypted-") as tmp:
            work = Path(tmp)
            _git(self.directory, "worktree", "add", "--quiet", "--detach", str(work), revision)
            try:
                destination = work / _CREDENTIAL_PATH
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(encrypted + b"\n")
                destination.chmod(0o600)
                _git(work, "add", "--", _CREDENTIAL_PATH)
                _git(work, "-c", "user.name=fpl-oidc-auth-bot",
                     "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                     "commit", "--quiet", "-m", "security(private): advance encrypted OIDC credential state")
                # Critical: no --force/rebase/merge. Pushing a non-FF claim fails,
                # preventing a second refresh from using the same token version.
                _git(work, "push", "--quiet", "origin", "HEAD:refs/heads/main")
            finally:
                _git(self.directory, "worktree", "remove", "--force", str(work))
        return value


class CASLease:
    """The durable exclusive refresh lock is the pushed IN_FLIGHT CAS state.

    Local process mutexes cannot ensure global safety; rotation manager claims
    the global marker inside this context and any competing writer fails CAS.
    This wrapper intentionally does not misrepresent a local lock as global.
    """

    @contextmanager
    def acquire(self) -> Iterator[None]:
        yield


def store_from_env() -> EncryptedGitCredentialStore:
    key = (os.getenv("FPL_OIDC_STORE_KEY") or "").strip()
    if not key:
        raise RotationBlocked("CREDENTIAL_STORE_KEY_NOT_CONFIGURED")
    directory = os.getenv("FPL_OIDC_STORE_DIR") or "private-reports"
    return EncryptedGitCredentialStore(directory, key)


def enroll_once(token: str, *, reenroll: bool = False) -> int:
    """Run ONLY in owner-only bootstrap workflow; prints metadata, never token."""
    if not isinstance(token, str) or len(token.strip()) < 32:
        raise RotationBlocked("CREDENTIAL_ENROLLMENT_TOKEN_MISSING")
    store = store_from_env()
    current = store.load()
    if current.version > 0 and not reenroll:
        raise RotationBlocked("CREDENTIAL_ALREADY_ENROLLED")
    if reenroll and not os.getenv("FPL_OWNER_CONFIRMED_REENROLL") == "REPLACE":
        raise RotationBlocked("CREDENTIAL_REENROLL_CONFIRMATION_MISSING")
    updated = store.compare_and_swap(
        current.version,
        Credential(version=current.version + 1, phase="READY", refresh_token=token.strip()),
    )
    verified = store.load()
    if verified.version != updated.version or verified.phase != "READY":
        raise RotationBlocked("CREDENTIAL_ENROLLMENT_READBACK_FAILED")
    # No plaintext is included in the return value or workflow summary.
    return verified.version
