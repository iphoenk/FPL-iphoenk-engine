from __future__ import annotations

import base64
import json

import pytest

from src.engines.private_cache_crypto import (
    NONCE_BYTES,
    SECURE_ENCRYPTED_PERSONAL_CACHE,
    SECURE_NO_PERSONAL_CACHE,
    TAG_BYTES,
    PrivateCacheCryptoError,
    encrypt_json,
    load_key_from_env,
    personal_persistence_enabled,
    try_decrypt_json,
    validate_profile,
)


def _key(byte: int) -> bytes:
    return bytes([byte]) * 32


def test_round_trip_and_envelope_exposes_only_allowed_metadata():
    payload = {
        "route": "HOLD",
        "player_ids": [1, 2, 3],
        "captain": "PRIVATE_PLAYER",
        "bank": 0.2,
    }
    envelope = encrypt_json(
        payload,
        cache_key="opaque:digest:abcdef",
        schema_version=3,
        key=_key(1),
    )

    assert set(envelope) == {
        "schema_version",
        "crypto_version",
        "nonce_b64",
        "ciphertext_b64",
        "tag_b64",
    }
    serialized = json.dumps(envelope)
    for forbidden in (
        "cache_key",
        "route",
        "player_ids",
        "PRIVATE_PLAYER",
        "captain",
        "bank",
        "FT",
        "chips",
        "OUT",
        "IN",
    ):
        assert forbidden not in serialized

    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:abcdef",
        schema_version=3,
        key=_key(1),
    ) == payload


def test_nonce_uniqueness_stress_and_exact_96_bits():
    nonces = set()
    for i in range(2048):
        envelope = encrypt_json(
            {"i": i},
            cache_key="opaque:digest:stress",
            schema_version=1,
            key=_key(2),
        )
        nonce = base64.b64decode(envelope["nonce_b64"])
        assert len(nonce) == NONCE_BYTES == 12
        nonces.add(nonce)
    assert len(nonces) == 2048


def test_wrong_key_fails_closed_to_safe_miss():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(3),
    )
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(4),
    ) is None


def test_modified_ciphertext_fails_closed():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(5),
    )
    raw = bytearray(base64.b64decode(envelope["ciphertext_b64"]))
    raw[0] ^= 0x01
    envelope["ciphertext_b64"] = base64.b64encode(bytes(raw)).decode("ascii")
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(5),
    ) is None


def test_modified_tag_fails_closed():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(6),
    )
    tag = bytearray(base64.b64decode(envelope["tag_b64"]))
    assert len(tag) == TAG_BYTES == 16
    tag[-1] ^= 0x01
    envelope["tag_b64"] = base64.b64encode(bytes(tag)).decode("ascii")
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(6),
    ) is None


def test_changed_aad_cache_key_fails_closed():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:original",
        schema_version=1,
        key=_key(7),
    )
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:copied",
        schema_version=1,
        key=_key(7),
    ) is None


def test_changed_aad_schema_fails_closed():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=7,
        key=_key(8),
    )
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=8,
        key=_key(8),
    ) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("crypto_version", 999),
        ("nonce_b64", "not-base64"),
        ("ciphertext_b64", "not-base64"),
        ("tag_b64", "not-base64"),
    ],
)
def test_malformed_envelope_fails_closed(field, value):
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(9),
    )
    envelope[field] = value
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(9),
    ) is None


def test_extra_metadata_is_rejected_not_trusted():
    envelope = encrypt_json(
        {"route": "A"},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(10),
    )
    envelope["aad"] = {
        "cache_key": "attacker-controlled",
        "schema_version": "1",
        "crypto_version": 1,
    }
    assert try_decrypt_json(
        envelope,
        cache_key="opaque:digest:a",
        schema_version=1,
        key=_key(10),
    ) is None


def test_profiles_separate_no_cache_and_encrypted_cache():
    assert (
        validate_profile(
            SECURE_NO_PERSONAL_CACHE,
            key_available=False,
        )
        == SECURE_NO_PERSONAL_CACHE
    )
    assert (
        personal_persistence_enabled(
            SECURE_NO_PERSONAL_CACHE,
            key_available=False,
        )
        is False
    )

    with pytest.raises(PrivateCacheCryptoError):
        validate_profile(
            SECURE_ENCRYPTED_PERSONAL_CACHE,
            key_available=False,
        )

    assert (
        personal_persistence_enabled(
            SECURE_ENCRYPTED_PERSONAL_CACHE,
            key_available=True,
        )
        is True
    )


def test_key_loader_accepts_only_base64_encoded_256_bit_key(monkeypatch):
    name = "FPL_V12_PRIVATE_CACHE_KEY_B64"
    monkeypatch.setenv(name, base64.b64encode(_key(11)).decode("ascii"))
    assert load_key_from_env(name) == _key(11)

    monkeypatch.setenv(
        name,
        base64.b64encode(b"too-short").decode("ascii"),
    )
    with pytest.raises(PrivateCacheCryptoError):
        load_key_from_env(name)

    monkeypatch.setenv(name, "%%%")
    with pytest.raises(PrivateCacheCryptoError):
        load_key_from_env(name)

    monkeypatch.delenv(name, raising=False)
    with pytest.raises(PrivateCacheCryptoError):
        load_key_from_env(name)


def test_envelope_never_contains_raw_key_material():
    key = _key(12)
    envelope = encrypt_json(
        {"x": 1},
        cache_key="opaque:digest:a",
        schema_version=1,
        key=key,
    )
    serialized = json.dumps(envelope).encode("utf-8")
    assert key not in serialized
    assert base64.b64encode(key) not in serialized
