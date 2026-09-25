# Cache Partial-Change Matrix Evidence — 2026-09-25

Status: CLOSED
Production main authority under test:
`156df38920896a7aa8cb9e7de759f279a726fe89`

Runtime-key hardening authority:
- PR #694
- merged production SHA: `156df38920896a7aa8cb9e7de759f279a726fe89`
- Stage-2 / P1.7 / MC cache schema: v2
- exact internal key binds Python major.minor + NumPy version.

Measurement-design authority:
`58a22a977e2d2a1be863b223bca0512d1c125564`
(Revision 4 frozen before this matrix)

## 1. Authoritative run

Authoritative workflow run:
`36091021641`

Validation head:
`fa3d49a7a3f25df4d79c6ff60e8f365bba9d218d`

Structure:
- 7 independent prime-A jobs;
- 21 independent verify-B jobs;
- 3 verify attempts per change class;
- exact isolated outer cache namespace keyed by this workflow run id;
- Stage-2, P1.7, and MC outer caches saved by prime A;
- each verify job restores the exact prime-A key, with no prefix ambiguity;
- B warm execution uses restored A directories;
- B cold reference uses isolated empty cache directories;
- material output fingerprints are compared per layer.

All 7 prime jobs: PASS.
All 21 verify jobs: PASS.

No over-invalidation finding was emitted in any of the 21 verify artifacts.

## 2. Non-authoritative earlier runs

Run `36090823084` is not authoritative for the team class because the synthetic team mutation could move a GK into the starting XI.

Run `36090922785` is not authoritative for the team class because the corrected same-position swap could still remove the existing captain or vice from the starting XI.

Both failures occurred before cache-semantic comparison and were fixture-validity failures, not cache failures.

The authoritative run fixes the team fixture by:
- swapping only same-position outfield players;
- excluding captain and vice from the replaced starter;
- preserving a legal starting XI.

## 3. Frozen expectation vs observed result

| Change class | Stage-2 expected | Stage-2 observed | P1.7 expected | P1.7 observed | MC expected | MC observed | Attempts |
|---|---|---|---|---|---|---|---|
| Injury / availability | MISS | **MISS** | MISS | **MISS** | MISS | **MISS** | 3/3 |
| xMins driver | MISS | **MISS** | MISS | **MISS** | MISS | **MISS** | 3/3 |
| Tactical role/system | MISS | **MISS** | MISS | **MISS** | MISS | **MISS** | 3/3 |
| Official price | MISS | **MISS** | HIT | **HIT** | MISS | **MISS** | 3/3 |
| Current-team identity | HIT | **HIT** | MISS | **MISS** | MISS | **MISS** | 3/3 |
| Finance-only | HIT | **HIT** | HIT | **HIT** | MISS | **MISS** | 3/3 |
| Unchanged control | HIT | **HIT** | HIT | **HIT** | HIT | **HIT** | 3/3 |

Observed internal-key relations matched the frozen expectation in every attempt:

- expected MISS -> A/B internal key **DIFFERENT**;
- expected HIT -> A/B internal key **SAME**.

## 4. Output correctness

For all 21 verify jobs and all three cache layers:

`warm-B material output fingerprint == cold-B material output fingerprint`

Therefore no restored A cache produced stale B material output.

This includes:
- all expected invalidations;
- all expected exact hits;
- the unchanged-input control.

## 5. Asymmetric scoring result

Frozen scoring rule:

- HIT where MISS expected -> correctness FAIL;
- MISS where HIT expected -> performance finding / over-invalidation;
- B-warm output != B-cold -> correctness FAIL.

Observed:
- stale HIT failures: **0**
- output mismatches: **0**
- over-invalidation findings: **0**

Thus the current cache dependency map is both correctness-complete for the tested mutation classes and no more conservative than the frozen matrix expected.

## 6. Outer-cache provenance result

Every verify job required:

`cache-matched-key == exact prime-A key from the same workflow run`

The workflow would fail before the semantic harness if any Stage-2, P1.7, or MC restore came from another key.

All 21 verify jobs passed that provenance check.

Therefore scheduled/hourly production caches could not contaminate this matrix.

## 7. Runtime-version invalidation

Separately, focused validation run `36089477721` proved for all three layers:

- unchanged runtime identity -> same exact internal key;
- Python-minor change -> different key;
- NumPy-version change -> different key.

This was merged before the partial-change matrix, as required by Revision 4.

## 8. Closure

The following are now CLOSED for the tested cache model:

- exact prime-A outer restore provenance;
- Stage-2 key completeness for injury, xMins, role/system, price;
- deliberate Stage-2 exclusion of current-team identity and finance;
- P1.7 key completeness for player-surface/current-team changes;
- deliberate P1.7 exclusion of price and finance;
- MC key completeness for projection, route, and economics changes;
- unchanged-input exact reuse;
- Python-minor invalidation;
- NumPy-version invalidation;
- B-warm vs B-cold material correctness.

This matrix is a cache-correctness closure. It is not an end-to-end latency result and does not satisfy the separate 30 s / 15 s compute gates.
