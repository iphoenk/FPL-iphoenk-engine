# V6 + FPL Master Operational Recovery — Final 3-Wave Contract

Date: 2026-09-14
Timezone: Asia/Jakarta
Repository: `iphoenk/FPL-iphoenk-engine`
Canonical runtime branch: `runtime-data-v6`
Canonical control issue: `#431`

This runbook defines the final production-recovery sequence for the current V6 + FPL Master incident stream.

It supersedes earlier ad-hoc operational references to a 2-wave or overlapping 3-wave repair plan. It does **not** supersede V6 source-expansion Wave A / Wave B / Wave C; those remain a separate architecture/source program.

Use these names consistently:

- **Operational Recovery Wave 1** = V6 data plane / publication integrity
- **Operational Recovery Wave 2** = control plane / freshness / report contract
- **Operational Recovery Wave 3** = production reliability / natural proof

Current adoption state:

- Wave 1: **IN PROGRESS** — current blocker is publish-tree integrity after successful acquisition.
- Wave 2: **NOT ACCEPTED** — some foundations are already merged, especially core-title vs prefetch-comment separation and `V6 FAIL != REPORT FAIL`, but the wave is not complete.
- Wave 3: **NOT STARTED**.

Do not declare a wave complete from a partial sub-feature. The exit criteria below are authoritative.

---

## Operational Recovery Wave 1 — Recover V6 Publication & Atomic Generation Integrity

### Objective

Restore the complete V6 path without bypassing or weakening safety gates:

`ACQUIRE -> NORMALIZE -> BUILD CANDIDATE -> FREEZE -> INTEGRITY -> PRODUCTION VALIDATE -> ATOMIC PROMOTE`

### Required work

1. Capture exact publish-integrity failure diagnostics from failing natural runs. Preserve, where available:
   - `candidate_generation_id`
   - `check_name`
   - `failed_path`
   - `first_error`
   - `errors[]`
   - registry epoch/fingerprint used by acquisition
   - manifest/catalog/checksum lineage
2. Compare failed candidate against LAST_GOOD for:
   - missing artifacts
   - malformed or empty JSON
   - mixed generations
   - artifact-catalog mismatch
   - checksum/manifest mismatch
   - registry-lineage mismatch
   - identity inconsistency, duplicate, or broken stable-ID bridge
   - semantic-authority violation
3. Fix the upstream producer or lineage that is proven wrong. Never disable the validator to make the run green.
4. Use generation-isolated staging: `staging/<generation_id>/`.
5. Use one `generation_id` end-to-end across acquisition, normalization, catalog, manifest, validation, and promotion.
6. Freeze the candidate before integrity validation. After FREEZE, normal producers must not mutate candidate contents.
7. Build the manifest from the frozen candidate only.
8. Carry explicit registry lineage with the candidate, including registry epoch/fingerprint and active source count at acquisition. Validation must compare to the registry actually used by that acquisition.
9. A legitimate one-way activation transition may pass only when explicitly proven. Corruption, conflict, duplicate identity, broken stable-ID bridge, or structural integrity failure remains fail-closed.
10. Promote atomically only after integrity and production validation both pass.
11. Any failure leaves active runtime on LAST_GOOD and must not mutate LAST_GOOD.
12. Emit machine-readable failure diagnostics, conceptually: `status`, `generation_id`, `failed_at`, `check_name`, `failed_path`, `first_error`, `errors[]`.
13. Controlled validation is allowed after patching, but manual replay/recovery does not count as natural reliability evidence.

### Wave 1 acceptance

Positive path must prove:

```text
CORE TRANSPORT:          PASS | <timestamp>
ACQUISITION:             PASS | <timestamp>
PUBLISH_INTEGRITY:       PASS | <timestamp>
PUBLISH VALIDATION:      PASS | <timestamp>
NEW PUBLICATION:         PROMOTED | <timestamp>
LAST-GOOD:               AVAILABLE | generated <timestamp> | age <duration>
```

Runtime control must point to the exact promoted generation.

Identity/coverage counts must be taken from the current verified source contract. Do not hard-code example counts as healthy if the live contract differs.

Mandatory negative test:

```text
BROKEN CANDIDATE
-> PUBLISH_INTEGRITY or PUBLISH VALIDATION FAIL
-> NEW PUBLICATION NOT PROMOTED
-> LAST-GOOD remains AVAILABLE and unchanged
```

### Exit gate

Do not start new Wave 2 implementation that depends on a healthy current publication until both positive and negative Wave 1 acceptance paths pass. Already-merged Wave 2 foundations may remain in place.

---

## Operational Recovery Wave 2 — Control Plane, Freshness, Prefetch & Report Contract

### Objective

Make scheduler proof, freshness, report-prefetch, status mapping, price reporting, mini-league retrieval, and report continuity truthful, granular, and idempotent.

### Required work

1. Separate time concepts:
   - `observed_at` / `now_wib` = actual execution time
   - `logical_slot` = governed logical hour/checkpoint
2. Core scheduler proof may only be advanced by authoritative core transport, never by report-prefetch.
3. Preserve fields such as:
   - `last_chatgpt_scheduler_cycle_at`
   - `last_authoritative_cycle_at`
   - `last_operational_cycle_at`
   - `scheduler_proof_age_seconds`
   - logical slot and run/publication provenance
4. Preserve transport separation:
   - issue `#431` title transport is reserved for `FPL_MASTER_SLOT`
   - report-prefetch is comment-only via `/v6-report-prefetch`
5. Core idempotency key includes at minimum `schedule_kind + logical_slot`.
6. Safety Net checks ownership, prefetch state, delivery state, and logical report slot before recovery. If the primary already owns/prefetched/delivered the slot, Safety Net is NO-OP.
7. Separate health by layer:
   - CORE TRANSPORT
   - ACQUISITION
   - PUBLISH_INTEGRITY
   - PUBLISH VALIDATION
   - NEW PUBLICATION
   - LAST-GOOD
   - SCHEDULER PROOF
   - REPORT PREFETCH
   - TARGET REPORT FRESHNESS
   - AUTH
   - REPORT DELIVERY
8. Every applicable status carries timestamp. Any state derived from older data also carries age.
9. Artifact-level freshness is authoritative over a coarse whole-publication stale flag.
10. 05:30 Price must verify the inputs required for the decision:
    - Official FPL current price facts
    - freshest valid predictor/model source(s), provenance-labelled
    - relevant ICON+ mini-league exposure
    - target players / transfer frontier
    - personal auth only when a required field genuinely needs it
11. Price authority wording:
    - Official FPL is authority for current price **facts**.
    - Do not call a predictor an "Official FPL predictor" unless independent provenance proves that it is an official FPL product.
    - A legacy identifier such as `official_price_predictor` is not proof of official provenance by itself.
12. Predictor/model fallback:

```text
Official current price FACT
-> freshest verified predictor/model source with explicit provenance
-> fresh supporting predictor/model
-> V6 cached predictor only if still within freshness contract
-> stale predictor disclosed / UNAVAILABLE
```

13. AUTH mapping is explicit: `OK`, `NOT REQUESTED`, `EXPIRED`, `FAILED`. `NOT REQUESTED` must never become `AUTH_EXPIRED`.
14. Report delivery is independent from V6 health: **V6 FAIL != REPORT FAIL**.
15. Due-report fallback ladder:

```text
fresh current V6
-> direct fresh Official/public source allowed by policy
-> valid LAST_GOOD only for nonvolatile facts with age disclosed
-> explicit UNAVAILABLE
```

16. Mini-league connector truncation must not be interpreted as proof that the underlying cohort is incomplete. Retrieve granularly until the cohort denominator is known or explicitly mark it incomplete.
17. Regression-test at minimum:
    - normal hourly
    - 04:30 Deep
    - 05:30 Price
    - 12:30 Deep
    - 21:30 Deep
    - Match Mode
    - Deadline Mode
    - ad-hoc Deep
    - provider AMBER
    - auth unavailable/expired
    - stale predictor
    - duplicate prefetch
    - delayed execution
    - corrupt candidate / blocked publication

### Wave 2 acceptance

Healthy non-report slot should be internally consistent, e.g.:

```text
LOGICAL SLOT:            <slot>
OBSERVED_AT:             <actual time>
CORE TRANSPORT:          PASS | <timestamp>
ACQUISITION:             PASS | <timestamp>
PUBLISH_INTEGRITY:       PASS | <timestamp>
PUBLISH VALIDATION:      PASS | <timestamp>
NEW PUBLICATION:         PROMOTED | <timestamp>
LAST-GOOD:               AVAILABLE | generated <timestamp> | age <duration>
SCHEDULER PROOF:         CURRENT | <timestamp> | age <duration>
REPORT PREFETCH:         N/A
TARGET REPORT FRESHNESS: N/A
AUTH:                    NOT REQUESTED
REPORT DELIVERY:         N/A
```

A local failure must remain granular, for example:

```text
CORE TRANSPORT:          PASS
ACQUISITION:             PASS
PUBLISH_INTEGRITY:       FAIL
PUBLISH VALIDATION:      SKIPPED/FAIL as applicable
NEW PUBLICATION:         NOT PROMOTED
LAST-GOOD:               AVAILABLE
REPORT DELIVERY:         PASS | DIRECT FRESH FALLBACK
```

### Exit gate

All report modes and status mappings pass regression tests. 05:30 Price and Safety Net dedupe pass. One stale/local component no longer produces a false whole-system FAILED/STALE state.

---

## Operational Recovery Wave 3 — Production Reliability, Chaos & Natural Proof

### Objective

Prove the repaired system remains stable in natural hourly operation and under controlled failure scenarios. Wave 3 is proof and hardening, not another redesign wave.

### Required work

1. Freeze the functional contracts from Waves 1-2. Only defect fixes are allowed unless new evidence requires a contract change.
2. Persist per-slot lifecycle/provenance as applicable:

`TRIGGERED -> ACQUIRED -> STAGED -> FROZEN -> INTEGRITY_PASS -> VALIDATED -> PROMOTED -> PREFETCHED -> DELIVERED`

Include logical slot, observed timestamps, run ID, generation/publication ID, registry fingerprint, ownership, and reason/provenance.
3. Exercise controlled chaos/recovery scenarios:
   - provider timeout
   - provider incomplete / AMBER
   - auth expired / auth not requested
   - stale optional cache
   - registry activation transition
   - identity conflict / duplicate
   - broken stable-ID bridge
   - malformed/corrupt candidate
   - publisher rejection
   - duplicate core trigger
   - duplicate report-prefetch
   - delayed scheduler execution
   - LAST_GOOD recovery
4. Provider incompleteness after reasonable retries remains non-blocking when Official core/identity is valid. Corruption, identity conflict, broken bridge, and structural integrity failures remain fail-closed.
5. Due reports continue through degraded scenarios; only affected fields/layers degrade.
6. Reliability proof counts only genuine governed natural slots, never manual replay/recovery.

### Production proof sequence

1. Obtain **>= 6 consecutive genuine natural core slots** with the expected full core chain passing.
2. After 6/6, continue to a **rolling 48/48 genuine natural-slot** proof window.
3. During both windows verify:
   - no duplicate ownership/publication for the same logical slot
   - candidate failures never mutate LAST_GOOD
   - scheduler proof timestamps/age are truthful
   - due report delivery remains correct
   - degraded states identify only affected layers/artifacts

Declare **PRODUCTION GREEN** only after the 48/48 window passes, unless the acceptance contract is explicitly changed.

---

## Single recovery status view

Every recovery update should include all three operational waves to prevent cross-chat drift:

```text
OPERATIONAL RECOVERY WAVE 1: <IN PROGRESS | ACCEPTED>
OPERATIONAL RECOVERY WAVE 2: <NOT STARTED | IN PROGRESS | ACCEPTED>
OPERATIONAL RECOVERY WAVE 3: <NOT STARTED | 6/6 IN PROGRESS | 48/48 IN PROGRESS | PRODUCTION GREEN>
CURRENT BLOCKER: <stage / exact failure>
LATEST NATURAL SLOT: <logical slot / run / result>
```

This runbook is the operational recovery sequence. Source-expansion Wave A/B/C remains separate and must not be conflated with it.
