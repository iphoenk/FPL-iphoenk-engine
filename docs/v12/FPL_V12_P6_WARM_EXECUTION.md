# FPL V12 P6 Warm Execution

Status: preparation branch from production main `c2c821cc67edd2a7435cc4367abff0d967aee807`.

P6 is a bounded orchestration layer over the existing Canonical V12 engine. It is not a scheduler, factual plane, optimizer, scorer, model, or second private compute authority.

The lifecycle is:

`START -> LOAD_CANONICAL_STATE -> VALIDATE_DEPENDENCIES -> WARM_READY -> RECEIVE_CHANGE -> CLASSIFY_CHANGE -> INVALIDATE_MINIMUM_REQUIRED -> RECOMPUTE -> STAGE3 -> RENDER -> QA -> PRIVATE_PUBLISH -> WARM_READY`.

TTL or explicit termination ends in `CLEAN_SHUTDOWN`. The maximum accepted lifetime is strictly less than six hours.

Cache behavior is read from the frozen `config/performance/v12_cache_dependency_matrix.json`. Operational hard invalidations for model/schema/current-15/captain/official-result/bonus-finalization are overlays and do not rewrite the frozen matrix. `SET_PIECE_FACT` deterministically maps to the existing `SET_PIECE_ROLE` class. Unknown or ambiguous dependency scope is a MISS.

Correctness rules are strict: expected MISS plus actual HIT is a correctness failure; partial invalidation may never reuse affected dependency keys; warm and canonical cold semantic fingerprints must be equal. Expected HIT plus actual MISS is reported as performance over-invalidation, not silently accepted as optimal.

D-P2 remains factual/report precompute only. Its governed P6 handoff preserves exact occurrence identity and supports T-15 prefetch plus T-10 freeze validation. Neither step counts as a natural core scheduler proof.

PERF-F measures T0 at event/command acceptance by an already-running warm worker and T1 only after validated private publication. Queue and runner provisioning are excluded. Every required class is judged individually against 15.000 seconds; no average can hide a failing required sample.

Manager-specific CURRENT15, owner context, scenario packages, decision results and decrypted personal caches stay within the private/encrypted boundary. Public CI uses contract fixtures only.
