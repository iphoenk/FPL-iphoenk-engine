# FPL V12 Cache Dependency Matrix

> Status: FROZEN DEFINITION / PRE-PERF-A PREPARATION  
> Change timestamp: 2026-09-27T15:01:00+07:00  
> Production base at preparation: `508f1ed919b9b37540cc604d92bdfe5075e96366`

This matrix fixes expected cache reuse before PERF-A through PERF-E. It is intentionally frozen before performance results are used to choose a strategy.

## Four states

- `HIT`: the prior entry is correctness-equivalent and should be reusable.
- `MISS`: the prior entry must not be reused.
- `PARTIAL_INVALIDATION`: only unaffected dependency-bound subentries may be reused; affected subentries must be recomputed.
- `NOT_APPLICABLE`: the change class does not participate in that layer under the current governed architecture.

A required MISS observed as HIT is a correctness failure. A required HIT observed as MISS is an over-invalidation performance defect. Reusing an affected subentry during partial invalidation is a correctness failure. Any warm result that differs from the canonical cold semantic fingerprint is a correctness failure.

## Partial invalidation discipline

Selective reuse is allowed only when affected dependency keys are explicit. The implementation must preserve fingerprints for unaffected subentries, recompute affected subentries, and compare the final warm result against canonical cold output. If the affected scope is uncertain, the required fallback is a full MISS for that layer.

## Boundary examples

- Owner-only availability does not invalidate public Stage-2 universe projections, but it invalidates P1.7 and downstream manager-specific compute.
- Price or team-finance changes do not rewrite football projections. They selectively invalidate finance/route-dependent MC or scenario subentries.
- Mini-league-only changes preserve football-return MC but invalidate downstream decision stability.
- Runtime-class, xMins, role, set-piece-role and fixture changes fail closed to MISS across canonical layers unless a later equivalence proof explicitly narrows that rule.
- Challenger-only evidence remains context-only. Canonical Stage-2/P1.7/MC caches remain reusable, while scenario/stability challenger integration is `NOT_APPLICABLE` until formally admitted.

The matrix must not be edited after an experiment merely to make the observed cache behavior look correct.
