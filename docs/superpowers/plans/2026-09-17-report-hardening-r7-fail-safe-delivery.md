# Report Hardening R7 — Fail-Safe Delivery Recovery

## Goal

Close the report-plane gap between R6 post-render QA and acknowledged same-slot delivery without weakening V6-only authority, report-slot identity, or delivery-proof truth.

## Authority

- `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt` sections 1A, 3, 8, 8A, 8B, 9.
- `/FPL/FPL_MASTER_SPEC_V11.txt` Y9, Y11, Y12.
- R6 post-render QA remains the visible-body authority.
- `report_delivery.py` remains the single acknowledged receipt/proof authority.
- `report_recovery.py` remains the single report-plane recovery planner; R7 does not create a second recovery engine.

## Final invariants

1. DATA_SLOT_FULFILLED != REPORT_SLOT_FULFILLED != REPORT_DELIVERED.
2. `report_state` remains report-plane truth: `BUILDING`, `QA_FAILED`, or `DELIVERED` as defined by the existing slot resolver.
3. `delivery_state` is separate delivery-plane truth: `BLOCKED`, `FAILED`, or `ACKNOWLEDGED`.
4. A receipt/transport failure does not rewrite a valid R6 report artifact into a synthetic report state; the report remains `BUILDING` until acknowledged delivery succeeds.
5. A report slot becomes `DELIVERED` only with a valid acknowledged same-slot receipt/proof.
6. Failed delivery remains in the original report slot; no replacement identity.
7. No V3/V4/V5 runtime/data fallback.
8. A transport/receipt-only failure may retry the exact R6-approved rendered artifact, bound by its compute fingerprint and render-contract token.
9. A visible-body/post-render QA failure must rerender and re-QA before another delivery attempt.
10. A healthy-source assertion failure must recover the exact V6 scope, retrieve, recompute, rerender, and re-QA in the same run before delivery.
11. A truthfully degraded/non-blocking scope does not weaken receipt requirements and does not create a synthetic `PASS_DEGRADED` delivery status.
12. Retry budgets are explicit caller/runtime policy inputs; R7 does not invent a global attempt count.
13. Retry exhaustion schedules catch-up while preserving truthful undelivered state and the original report-slot identity.

## TDD evidence

### RED

Commit `56901ec9c2aa0f5ed71dcf4dbee35a1cdf76e04f` added the R7 contract tests before the orchestration/finalization APIs existed. The full test suite failed during collection on the missing R7 API while compile and architecture/governance pre-checks remained green. This proved the delivery/recovery disconnect without changing production behavior first.

### GREEN

Production changes are intentionally limited to the existing authorities:

- `report_delivery.py`
  - exposes the canonical R6->R7 readiness predicate;
  - adds explicit `delivery_state` evidence to blocked, failed, and acknowledged delivery outcomes;
  - adds `finalize_delivery_outcome()` to project acknowledged delivery truth separately from report quality;
  - successful delivery remains `status=PASS`, `delivery_status=DELIVERED`; report quality is separately `COMPLETE` or `DEGRADED`.

- `report_recovery.py`
  - adds `plan_fail_safe_recovery()` as a thin evidence-driven orchestration layer over the existing recovery planner;
  - valid R6 artifact + receipt-only failure -> same-artifact delivery-proof retry;
  - invalid/missing R6 artifact -> rerender -> post-render QA -> delivery proof;
  - failed healthy-source scopes -> exact-scope V6 recovery -> retrieve -> recompute -> rerender -> post-render QA -> delivery proof;
  - retry exhaustion -> `SCHEDULE_CATCH_UP` without claiming delivery;
  - no direct V6 data-plane mutation and no legacy fallback.

## Verification

- R7 targeted tests cover delivery failure evidence, report/delivery state separation, same-artifact retry, rerender/re-QA recovery, exact-scope V6 recovery, retry exhaustion, degraded-quality delivery, blocked-scope rejection, and same-slot receipt enforcement.
- Existing report-slot/E2E tests continue to cover same-slot already-delivered deduplication/no-op behavior.
- Candidate head `7ed9ad38be373aca71d4876b8940fbd263ab2099` passed all four repository workflows before this documentation-only alignment: FPL V6 CI contracts, repository governance, naming policy, and the full repository regression/release harness.
- Exact-head CI is rerun after this documentation alignment before guarded merge.

## Non-goals

- No R8 chaos/soak expansion beyond existing CI gates.
- No scheduler redesign.
- No new data source or fallback.
- No duplicate R4/R5/R6 validator.
- No synthetic `PASS_DEGRADED` delivery status unless a future canonical Runtime Contract explicitly defines one.
