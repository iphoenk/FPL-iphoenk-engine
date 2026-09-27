# FPL V12 D-P3 Private Cache Crypto

> Status: PREPARED / NOT YET PRODUCTION-ACTIVE  
> Change timestamp: 2026-09-27T11:46:00+07:00  
> Production base at preparation: `a25fd7b22d0aca0c35afa66ccfea935f1d5fcf78`

## Purpose

D-P3 is the cryptographic boundary for manager-specific decision caches. It does not create cache eligibility, invalidation, scheduler, optimizer, or decision authority.

The public repository may contain the reusable crypto implementation and tests. Personal cache payloads and production key material remain private-only.

## Profiles

- `SECURE_NO_PERSONAL_CACHE`: correctness baseline. Manager-specific decision results are not persisted.
- `SECURE_ENCRYPTED_PERSONAL_CACHE`: permits private persistence only when a valid 256-bit key is available.

There is no plaintext fallback from the encrypted profile.

## Envelope contract

- AEAD: AES-256-GCM through the Python `cryptography` package.
- Nonce: fresh random 96-bit nonce per encryption.
- AAD: deterministic canonical encoding of `cache_key`, `schema_version`, and `crypto_version`.
- Envelope stores ciphertext, nonce, schema/crypto versions and algorithm metadata only.
- The plaintext cache key is intentionally not stored in the envelope.
- Wrong key, wrong cache key, wrong schema, malformed envelope, tampering, or authentication-tag failure all become a safe cache MISS.
- Safe MISS requires canonical recomputation by the caller; unauthenticated bytes are never returned.

## Secret handling

The supported environment variable name is `FPL_V12_PRIVATE_CACHE_KEY_B64`. Its value must be base64 for exactly 32 random bytes.

The value itself must never be committed, logged, written to cache metadata, included in public artifacts, or exposed to pull-request/fork workflows.

This branch does not wire a production secret into any workflow. Production secret wiring and cache-layer integration remain a later gated step after preceding delivery/natural gates are accepted.

## Acceptance tests

The test suite requires:

1. round-trip decrypt with the exact key/cache-key/schema tuple;
2. fresh unique 96-bit nonces;
3. wrong key -> MISS;
4. copied ciphertext under another cache key -> MISS through AAD authentication;
5. schema/version mismatch -> MISS;
6. tampered ciphertext -> MISS;
7. malformed envelope -> MISS;
8. exact profile behavior for encrypted versus no-personal-cache modes;
9. key loader rejects missing, malformed, or non-256-bit keys;
10. raw key material is absent from the envelope.

D-P3 must not be called production GREEN merely because these code tests pass. Production activation also requires secret/fork-safety governance, private-only cache integration, canonical warm/cold equality, and natural production acceptance under the architecture gates.
