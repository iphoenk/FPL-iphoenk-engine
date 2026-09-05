from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE_KEY_FRAGMENTS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "access_token",
    "refresh_token",
    "session",
    "private_key",
    "client_secret",
    "secret",
}


class SecretLeakError(RuntimeError):
    """Raised when secret-bearing material is about to enter the V6 publish tree."""


def _normalise_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def find_sensitive_paths(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_norm = _normalise_key(key)
            child_path = f"{path}.{key}"
            if any(fragment in key_norm for fragment in SENSITIVE_KEY_FRAGMENTS):
                findings.append(child_path)
                continue
            findings.extend(find_sensitive_paths(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            findings.extend(find_sensitive_paths(child, f"{path}[{index}]"))
    return findings


def assert_publish_safe(value: Any, *, secret_values: Sequence[str] = ()) -> None:
    findings = find_sensitive_paths(value)
    if findings:
        raise SecretLeakError(f"sensitive key material blocked at {findings[0]}")
    rendered = repr(value)
    for secret in secret_values:
        if secret and secret in rendered:
            raise SecretLeakError("secret value material blocked from V6 publish tree")


def safe_error(exc: BaseException) -> str:
    return type(exc).__name__
