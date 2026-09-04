# V6 Standalone Data Platform Contract

## Role

V6 is the upstream FPL data warehouse/data platform. It acquires, normalizes, validates, versions, and publishes governed canonical data. It has no decision, prediction, optimizer, tactical, transfer, captain, chip, or formation authority.

## Dependency direction

Allowed:

`external providers -> V6 -> V3/V4/future consumers`

Forbidden:

- `V6 -> runtime_v3 implementation`
- `V6 -> runtime_v4 implementation`
- `V6 -> V3/V4 runtime-data authority`
- `V6 PR/merge -> V3/V4 production runtime`
- V3/V4 mutating V6 canonical snapshots

Downstream engines may consume V6 and may own an explicit governed direct-source fallback. A consumer fallback never becomes V6 authority and never mutates V6.

## V6-owned runtime boundaries

- code: `src/runtime_v6/**`
- config: `config/v6/**`
- runtime dependencies: `requirements-v6.lock`
- CI dependencies: `requirements-v6-ci.lock`
- CI: `.github/workflows/v6-ci.yml`
- acquisition/publisher: `.github/workflows/v6-hourly-data-ingestion.yml`
- runtime branch: `runtime-data-v6`
- publisher environment: `v6-runtime-publisher`
- publisher credentials: dedicated V6 GitHub App only

## Canonical data rules

- Official FPL element ID is the canonical player identity authority.
- Fuzzy identity is not canonical authority.
- Source failures are isolated.
- Last-good cache must be explicit and truthfully stale when not revalidated.
- Provenance and integrity are mandatory.
- Manual recovery is non-authoritative and cannot satisfy a missed scheduled production slot.

## CI isolation

Version-specific checks have explicit identities (`v3-verify`, `v6-verify`). The repository-wide required check named `verify` is owned only by neutral repository governance. V3 CI ignores V6-owned changes on PR and on `main` push, so a V6-only change cannot chain into V3 runtime or V3 package precompute.

## Delete-test acceptance

V6 architecture is accepted only when V6 can build, validate, acquire, normalize, and publish without importing or reading V3/V4 implementation/runtime state. The automated V6 independence validator and neutral repository version-isolation validator enforce this boundary.
