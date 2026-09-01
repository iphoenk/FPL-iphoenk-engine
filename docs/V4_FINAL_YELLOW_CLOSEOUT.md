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
- Reuse the exact prediction object explicitly between prediction, validation, and governance in the non-publishing hot execution strategy while retaining the original file-backed service entrypoints for the process-isolated production DAG.
- Carry same-cycle reconciliation-integrity evidence into maturity evaluation by exact model-version, GW, and semantic digest. Missing proof falls back to the full integrity check; mismatched proof is rejected rather than trusted.

## Explicit non-changes

No prediction mathematics, xPts/xMins mathematics, calibration thresholds, optimizer search width, DSS scoring semantics, tactical semantics, canonical decision arbitration, chip semantics, watchlist semantics, or V3/V5 code is changed.

## Validated closeout evidence

The final performance patch was validated before landing with the complete deterministic suite: 409 tests passed. Architecture assurance and content-addressed attestation passed with all 24 architecture checks.

The repeated FAST population kept the existing 3.0 second p95 threshold unchanged and produced serving times of 2516.91 ms, 2483.56 ms, 2553.74 ms, 2617.12 ms, and 2551.55 ms. Median was 2551.55 ms and p95 was 2617.12 ms. The cold/cache-establishment run remains separately visible and is not counted as FAST evidence.

Warm validation was approximately 617-627 ms and final governance approximately 246-289 ms in the validated population. The optimization service continued to use its governed 5.0 second production SLO; no optimizer search-width or decision-quality reduction was introduced.

## Acceptance

The closeout is accepted only when the existing `core / validate-v4` required check passes, including the complete deterministic test suite, 8-service DAG, centralized quality gate, architecture assurance, before/after diagnostic, advanced ablation, and repeated non-publishing performance benchmark.

The governed architecture attestation was regenerated from the final closeout source bytes with `tools/v4_architecture_guard_attest.py` after the final reusable-workflow and FAST-path hardening. Documentation-only evidence commits intentionally follow the attestation and are outside the architecture fingerprint.
