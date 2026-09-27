from __future__ import annotations

"""D-P3 private cache AEAD boundary.

This module is deliberately narrow: it encrypts/decrypts already-authorized
manager-specific cache payloads and owns no scheduler, model, invalidation, or
decision semantics.
"""

import base64
import json
import os
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ALGORITHM = "AES-256-GCM"
CRYPTO_VERSION = 1
NONCE_BYTES = 12
TAG_BYTES = 16

SECURE_NO_PERSONAL_CACHE = "SECURE_NO_PERSONAL_CACHE"
SECURE_ENCRYPTED_PERSONAL_CACHE = "SECURE_ENCRYPTED_PERSONAL_CACHE"
SUPPORTED_PROFILES = {
    SECURE_NO_PERSONAL_CACHE,
    SECURE_ENCRYPTED_PERSONAL_CACHE,
}

_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "crypto_version",
        "nonce_b64",
        "ciphertext_b64",
        "tag_b64",
    }
)


class PrivateCacheCryptoError(ValueError):
    """Invalid crypto configuration."""


class PrivateCacheMiss(Exception):
    """Fail-closed cache miss; caller must recompute canonically."""


def _require_text(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PrivateCacheCryptoError(f"{label} must be non-empty")
    return text


def _require_key(key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise PrivateCacheCryptoError("AES-256-GCM key must be exactly 32 bytes")
    return bytes(key)


def load_key_from_env(env_name: str = "FPL_V12_PRIVATE_CACHE_KEY_B64") -> bytes:
    """Load one base64-encoded 256-bit key without logging or persisting it."""
    raw = os.environ.get(_require_text(env_name, label="env_name"), "")
    if not raw:
        raise PrivateCacheCryptoError("private cache encryption key is unavailable")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 - fail closed at secret boundary
        raise PrivateCacheCryptoError(
            "private cache encryption key is invalid base64"
        ) from exc
    return _require_key(key)


def validate_profile(profile: str, *, key_available: bool) -> str:
    profile = _require_text(profile, label="profile")
    if profile not in SUPPORTED_PROFILES:
        raise PrivateCacheCryptoError(f"unsupported private cache profile: {profile}")
    if profile == SECURE_ENCRYPTED_PERSONAL_CACHE and not key_available:
        raise PrivateCacheCryptoError(
            "encrypted personal cache profile requires a key"
        )
    return profile


def personal_persistence_enabled(profile: str, *, key_available: bool) -> bool:
    return (
        validate_profile(profile, key_available=key_available)
        == SECURE_ENCRYPTED_PERSONAL_CACHE
    )


def _aad(*, cache_key: str, schema_version: str | int, crypto_version: int) -> bytes:
    """Canonical AAD reconstructed from the cache request, never envelope metadata."""
    payload = {
        "cache_key": _require_text(cache_key, label="cache_key"),
        "crypto_version": int(crypto_version),
        "schema_version": _require_text(
            str(schema_version), label="schema_version"
        ),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: Any, *, label: str) -> bytes:
    try:
        return base64.b64decode(str(value), validate=True)
    except Exception as exc:  # noqa: BLE001 - malformed envelope is safe MISS
        raise PrivateCacheMiss(f"invalid {label}") from exc


def encrypt_bytes(
    plaintext: bytes,
    *,
    cache_key: str,
    schema_version: str | int,
    key: bytes,
    crypto_version: int = CRYPTO_VERSION,
) -> dict[str, Any]:
    """Encrypt private cache bytes with a fresh random 96-bit nonce."""
    if not isinstance(plaintext, (bytes, bytearray)):
        raise PrivateCacheCryptoError("plaintext must be bytes")
    if int(crypto_version) != CRYPTO_VERSION:
        raise PrivateCacheCryptoError("unsupported crypto_version")

    secret = _require_key(key)
    nonce = os.urandom(NONCE_BYTES)
    aad = _aad(
        cache_key=cache_key,
        schema_version=schema_version,
        crypto_version=int(crypto_version),
    )
    sealed = AESGCM(secret).encrypt(nonce, bytes(plaintext), aad)
    ciphertext, tag = sealed[:-TAG_BYTES], sealed[-TAG_BYTES:]
    return {
        "schema_version": str(schema_version),
        "crypto_version": int(crypto_version),
        "nonce_b64": _b64encode(nonce),
        "ciphertext_b64": _b64encode(ciphertext),
        "tag_b64": _b64encode(tag),
    }


def decrypt_bytes(
    envelope: Mapping[str, Any],
    *,
    cache_key: str,
    schema_version: str | int,
    key: bytes,
) -> bytes:
    """Decrypt or raise PrivateCacheMiss. Never return unauthenticated bytes."""
    try:
        if set(envelope) != _ENVELOPE_FIELDS:
            raise PrivateCacheMiss("private cache envelope field set mismatch")
        if int(envelope.get("crypto_version")) != CRYPTO_VERSION:
            raise PrivateCacheMiss("private cache crypto_version mismatch")
        if str(envelope.get("schema_version")) != str(schema_version):
            raise PrivateCacheMiss("private cache schema_version mismatch")

        nonce = _b64decode(envelope.get("nonce_b64"), label="nonce")
        ciphertext = _b64decode(
            envelope.get("ciphertext_b64"), label="ciphertext"
        )
        tag = _b64decode(envelope.get("tag_b64"), label="tag")
        if len(nonce) != NONCE_BYTES:
            raise PrivateCacheMiss("private cache nonce length mismatch")
        if len(tag) != TAG_BYTES:
            raise PrivateCacheMiss("private cache tag length mismatch")

        aad = _aad(
            cache_key=cache_key,
            schema_version=schema_version,
            crypto_version=CRYPTO_VERSION,
        )
        return AESGCM(_require_key(key)).decrypt(
            nonce,
            ciphertext + tag,
            aad,
        )
    except PrivateCacheMiss:
        raise
    except (
        InvalidTag,
        PrivateCacheCryptoError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PrivateCacheMiss("private cache authentication failed") from exc


def encrypt_json(
    payload: Any,
    *,
    cache_key: str,
    schema_version: str | int,
    key: bytes,
) -> dict[str, Any]:
    plaintext = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return encrypt_bytes(
        plaintext,
        cache_key=cache_key,
        schema_version=schema_version,
        key=key,
    )


def try_decrypt_json(
    envelope: Mapping[str, Any],
    *,
    cache_key: str,
    schema_version: str | int,
    key: bytes,
) -> Any | None:
    """Safe cache read: any auth/config/envelope failure becomes MISS."""
    try:
        plaintext = decrypt_bytes(
            envelope,
            cache_key=cache_key,
            schema_version=schema_version,
            key=key,
        )
        return json.loads(plaintext.decode("utf-8"))
    except (
        PrivateCacheMiss,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None
