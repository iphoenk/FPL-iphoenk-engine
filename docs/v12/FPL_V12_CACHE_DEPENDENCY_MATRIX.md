# FPL V12 Cache Dependency Matrix

> Status: FROZEN BEFORE PERFORMANCE A/B  
> Change timestamp: 2026-09-27T12:12:00+07:00

This matrix fixes expected cache reuse before observing PERF-A through PERF-E.

A required MISS that becomes an actual HIT is a correctness failure. A required HIT that becomes an actual MISS is over-invalidation and therefore a performance defect. Warm output that differs from the canonical cold output is always a correctness failure.

The matrix is deliberately conservative where generic scenario overrides or route-space changes could alter downstream decision legality. Narrower reuse is allowed only after a separately governed typed dependency contract proves equivalence.

Public/private separation is preserved: an owner-only availability change does not invalidate the public Stage-2 universe projection, while it does invalidate owned-lineup, route simulation and downstream decision surfaces.

Challenger-only context does not invalidate canonical caches before a challenger is explicitly calibrated and integrated into canonical policy.
