# FPL V12 P6 Warm Execution

Status: preparation branch from production main `c2c821cc67edd2a7435cc4367abff0d967aee807`.

P6 is a bounded orchestration layer over the existing Canonical V12 engine. It is not a scheduler, factual plane, optimizer, scorer, model, or second private compute authority.

The lifecycle is:

`START -> LOAD_CANONICAL_STATE -> VALIDATE_DEPENDENCIES -> WARM_READY -> RECEIVE_CHANGE -> CLASSIFY_CHANGE -> INVALIDATE_MINIMUM_REQUIRED -> RECOMPUTE -> STAGE3 -> RENDER -> QA -> PRIVATE_PUBLISH -> WARM_READY`.

TTL or explicit termination ends in `CLEAN_SHUTDOWN`. The maximum accepted lifetime is strictly less than six hours.

Cache behavior is read from the frozen `config/performance/v12_cache_dependency_matrix.json`. Operational hard invalidations for model/schema/current-15/captain/official-result/bonus-finalization are overlays and do not rewrite the frozen matrix. `SET_PIECE_FACT` deterministically maps to `SET_PIECE_ROLE`, `MATERIAL_PROJECTION` to `XMINS`, and the PERF-F aliases `NO_CHANGE` / `OUR15_AVAILABILITY` to the existing `UNCHANGED` / `OWNED_AVAILABILITY` rows. A dependency-valid `P4_SCENARIO_HIT` maps to `UNCHANGED`; `P4_SCENARIO_MISS` and `UNCERTAIN_SCOPE` force full MISS because the affected bound dependency cannot be safely narrowed. Unknown or ambiguous dependency scope is always fail-closed.

Correctness rules are strict: expected MISS plus actual HIT is a correctness failure; partial invalidation may never reuse affected dependency keys; warm and canonical cold semantic fingerprints must be equal. Expected HIT plus actual MISS is reported as performance over-invalidation, not silently accepted as optimal.

D-P2 remains factual/report precompute only. Its governed P6 handoff preserves exact occurrence identity and supports T-15 prefetch plus T-10 freeze validation. Neither step counts as a natural core scheduler proof.

PERF-F measures T0 at event/command acceptance by an already-running warm worker and T1 only after validated private publication. The warm worker records measured classification, cache lookup, recompute, Stage3, render, QA, and private-publication timings; canonical Stage2/P1.7/MC timings are consumed from engine telemetry and are never inferred. Queue and runner provisioning are excluded. Every required class is judged individually against 15.000 seconds; no average can hide a failing required sample. A PERF-F sample passes only when latency is within target, warm and canonical-cold semantic surfaces are exactly equal, cache correctness passes, owner-context lineage is present, and the private publication is PASS with a verified remote SHA.

Manager-specific CURRENT15, owner context, scenario packages, decision results and decrypted personal caches stay within the private/encrypted boundary. Public CI uses contract fixtures only.

## Operational D-P2 wiring

The existing owner-gated D-P2 issue-comment transport remains non-recurring and non-authoritative. At T-15 it dispatches the existing V6 report-prefetch path, then invokes the reusable P6 workflow with the same report kind, logical slot, exact T-10 freeze target, and deterministic occurrence ID. P6 has no cron, cannot edit issue 431, and cannot advance scheduler proof.

The production P6 workflow uses a standard GitHub-hosted runner for strictly less than six hours. It checks out the exact production V12 tree, runtime-data-v6, and the governed private repository. It waits for the factual/report prefetch bound to the same occurrence before preparing canonical state with the existing integrated V12 runner and encrypted personal-cache profile.

At T-10, occurrence, production SHA, runtime state, owner state, model, projection lineage, MC authority, and cache dependencies are revalidated. Broad or ambiguous drift is classified as UNCERTAIN_SCOPE and forces a MISS/full canonical recompute instead of speculative selective reuse.

At the visible occurrence, T0 begins only after the already-running worker accepts the occurrence or material change. Unchanged state may reuse the frozen canonical output. Changed state currently uses the same canonical V12 engine whenever a safe selective executor is not yet proven. Such conservative reuse loss is reported as PERFORMANCE_OVER_INVALIDATION and must never be mislabeled as a HIT.

Stage3, render QA, and the existing thin private publisher remain mandatory. T1 occurs only after the private repository publication is committed, pushed, and the remote SHA is verified. Manager-specific CURRENT15, owner context, scenario packages, decrypted cache state, and decision results are never uploaded as public artifacts.

PERF-F is therefore allowed to expose slow MISS classes. Latency is optimized only after warm/cold semantic equality is proven and profiling identifies the dominant component. Correctness is not traded for the 15-second target.


Warm identity hashes the canonical V6 `data/v6/current/official_fpl.json` snapshot together with publish-integrity and same-occurrence prefetch proof; legacy/nonexistent `data/v6/official_fpl` and `data/v6/fixtures` paths are not identity authority. This path binding is a correctness contract, not a performance optimization.
