# FPL V12 D-P3 Private Cache Crypto

> Status: PREPARED / NOT YET PRODUCTION-ACTIVE  
> Change timestamp: 2026-09-27T15:20:00+07:00
> Production base at preparation: `508f1ed919b9b37540cc604d92bdfe5075e96366`

## Purpose

D-P3 defines the cryptographic boundary for manager-specific P1.7 and Monte Carlo cache payloads. It does not create scheduler, model, optimizer, cache-eligibility, invalidation, or decision authority.

The public repository may contain reusable crypto code and public-safe tests. Production key material, private cache payloads, and manager-specific decision state remain private-only.

## Profiles

- `SECURE_NO_PERSONAL_CACHE`: correctness baseline. Manager-specific decision results are not persisted.
- `SECURE_ENCRYPTED_PERSONAL_CACHE`: permits private persistence only when a valid 256-bit production key is available.

There is no plaintext fallback.

## Envelope contract

- AEAD: AES-256-GCM.
- Key: exactly 32 bytes.
- Nonce: fresh random 96-bit CSPRNG bytes for every encryption.
- Tag: 128-bit GCM authentication tag.
- AAD is reconstructed from the cache request using canonical `cache_key`, `schema_version`, and `crypto_version`.
- Blob metadata is never trusted as AAD input.
- The envelope exposes only `schema_version`, `crypto_version`, `nonce_b64`, `ciphertext_b64`, and `tag_b64`.
- Extra envelope fields are rejected fail-closed.
- The cache key itself must be an opaque digest and is not stored in the envelope.
- Wrong key, copied ciphertext, schema mismatch, malformed base64, nonce mismatch, ciphertext modification, tag modification, or AAD mismatch all become a safe MISS.
- Safe MISS requires canonical recomputation. Unauthenticated bytes are never returned.

## Secret handling

The supported environment variable is `FPL_V12_PRIVATE_CACHE_KEY_B64`, containing base64 for exactly 32 random bytes.

The key must never be committed, logged, written into artifact metadata, or exposed to pull-request/fork execution. Production workflow wiring remains a later gated step and must avoid secret-bearing `pull_request_target`.

## Acceptance coverage prepared here

1. encrypt/decrypt round trip;
2. wrong key fail-closed;
3. modified ciphertext fail-closed;
4. modified tag fail-closed;
5. changed AAD fail-closed;
6. cache-A ciphertext copied to cache-B fails authentication;
7. 2,048-encryption nonce uniqueness stress test with exact 12-byte nonces;
8. malformed/extra metadata fail-closed;
9. profile semantics;
10. key loader rejects missing/malformed/non-256-bit keys;
11. personal payload markers and raw key material absent from serialized envelope.

## Production wiring prepared

The integrated V12 workflow now selects the cache profile explicitly:

- owner-triggered production main / issue transport uses `SECURE_ENCRYPTED_PERSONAL_CACHE`;
- non-main branch acceptance uses `SECURE_NO_PERSONAL_CACHE`;
- branch acceptance must not receive `FPL_V12_PRIVATE_CACHE_KEY_B64`;
- production encrypted mode fails before canonical compute when the key is absent or does not decode to exactly 32 bytes;
- P1.7 and MC persistence uses only `*.aead.json` files;
- restored production cache directories are rejected if any non-AEAD file is present;
- encrypted cache save occurs only after successful execution;
- no `pull_request_target` secret-bearing path exists.

P1.7 and MC retain their existing deterministic cache keys, model ownership, 500k Monte Carlo requirement and canonical semantics. Only persistence encoding/profile behavior changes. Authentication failure becomes an exact recomputation path and never a plaintext fallback.

This preparation is not CRYPTO GREEN by itself. Production closure still requires exact-head CI/governance, proof that the production secret is provisioned, cold/warm semantic equality, successful encrypted cache reuse on a governed production run, and the mandated natural post-merge acceptance.
