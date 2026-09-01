# V4 Final Yellow Closeout

This closeout removes structural and operational hardening debt without changing V4 football or decision semantics.

## Scope

- Bind the non-publishing hot benchmark to the authoritative service registry and the same production wrapper modules used by the process-isolated DAG.
- Remove quality-gate module-global mutation; strict assertions are passed explicitly to the shared runner.
- Re-attest publication integrity after Match Mode composition so the final checkpoint and serving payload bytes are the bytes covered by the final integrity record.
- Source the decision-compute SLO from governed runtime policy and fail closed if registry mirrors drift.
- Reduce canonical and recovery caller `GITHUB_TOKEN` contents permission to read-only; the dedicated publisher GitHub App remains the sole runtime write authority.
- Ensure both canonical production and recovery reusable callers inherit the governed publisher secret contract.
- Pin every `actions/*` dependency in the reusable V4 core to an immutable commit SHA.
- Report runtime commit metadata truthfully without treating spoofable commit metadata as proof of publisher identity. Platform ruleset enforcement remains the separate identity authority.
- Remove repeated Python interpreter/bootstrap overhead from the non-publishing validation hot lane by running the exact registry-owned validation service in a forked child.
- Make FAST performance evidence explicit: retain the cold/cache-establishment run separately, then measure fresh-Official exact-semantic-cache-hit runs against the unchanged 3.0s p95 target.
- Deduplicate legacy reconciliation source-integrity verification inside one validation cycle: an existing reconciliation may defer the expensive source check only to the same cycle's eligibility rebuild, and the cycle fails closed unless that rebuild records the GW as integrity-verified.

## Explicit non-changes

No prediction mathematics, xPts/xMins mathematics, calibration thresholds, optimizer search width, DSS scoring semantics, tactical semantics, canonical decision arbitration, chip semantics, watchlist semantics, or V3/V5 code is changed.

## Acceptance

The closeout is accepted only when the existing `core / validate-v4` required check passes, including the complete deterministic test suite, 8-service DAG, centralized quality gate, architecture assurance, before/after diagnostic, advanced ablation, and repeated non-publishing performance benchmark.

The governed architecture attestation was regenerated from the final closeout source bytes with `tools/v4_architecture_guard_attest.py` after the final reusable-workflow and FAST-path hardening. This documentation-only commit intentionally follows the attestation and is outside the architecture fingerprint.
