# Report Hardening R7 — Fail-Safe Delivery Recovery

## Goal

Close the report-plane gap between R6 post-render QA and acknowledged same-slot delivery without weakening V6-only authority, report-slot identity, or delivery-proof truth.

## Authority

- `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt` sections 1A, 3, 8, 8A, 8B, 9.
- `/FPL/FPL_MASTER_SPEC_V11.txt` Y9, Y11, Y12.
- R6 post-render QA remains the visible-body authority.
- `report_delivery.py` remains the single acknowledged receipt/proof authority.
- `report_recovery.py` remains the report-plane recovery planner; R7 must not create a second recovery engine.

## Invariants

1. DATA_SLOT_FULFILLED != REPORT_SLOT_FULFILLED != REPORT_DELIVERED.
2. A report slot becomes DELIVERED only with a valid acknowledged same-slot receipt/proof.
3. Failed delivery remains in the original report slot; no replacement identity.
4. No V3/V4/V5 fallback.
5. A transport/receipt-only failure may retry the exact R6-approved rendered artifact.
6. A visible-body/post-render QA failure must rerender and re-QA before another delivery attempt.
7. A healthy-source assertion failure must recover the exact V6 scope, retrieve, recompute, rerender, and re-QA in the same run before delivery.
8. A truthfully degraded/non-blocking scope does not weaken receipt requirements and does not create a synthetic `PASS_DEGRADED` delivery status.
9. Retry budgets are explicit caller/runtime policy inputs; R7 does not invent a global attempt count.
10. Retry exhaustion schedules catch-up while preserving truthful undelivered state and the original report-slot identity.

## TDD tasks

### Task 1 — Prove current delivery/recovery disconnect

Files:
- `tests/test_report_hardening_r7_fail_safe_delivery.py`
- `src/runtime_v6/domains/report_plane/report_delivery.py`
- `src/runtime_v6/domains/report_plane/delivery_integrity.py`

RED tests:
- failed/unacknowledged delivery produces an explicit recoverable delivery-failed state;
- slot resolver keeps the exact report slot recoverable;
- recovery planner accepts that state instead of treating it as an active build.

### Task 2 — Add deterministic recovery classification

File:
- `src/runtime_v6/domains/report_plane/report_recovery.py`

Add one canonical fail-safe recovery planner that derives, rather than trusts, the recovery path from evidence:
- valid R6 artifact + receipt/transport failure -> delivery-proof retry on the same artifact;
- invalid/missing R6 artifact -> rerender -> post-render QA -> delivery proof;
- failed healthy-source scopes -> exact-scope V6 recovery -> retrieve -> recompute -> rerender -> post-render QA -> delivery proof.

The planner must expose:
- exact `report_slot_id`;
- retry budget state;
- immutable artifact identifiers when same-artifact retry is allowed;
- failed exact scopes when source recovery is required;
- ordered recovery steps;
- `legacy_fallback_allowed=false`;
- `v6_data_plane_mutation_allowed=false` except that exact-scope governed recovery is explicitly requested through the existing V6 scope contract, never by report-plane direct mutation.

### Task 3 — Preserve delivery truth under degraded scope and exhaustion

Tests:
- non-blocking degraded report quality can still receive normal acknowledged delivery proof;
- invalid proof never becomes delivered;
- retry exhaustion schedules catch-up without changing delivery truth;
- same-slot already-delivered receipt becomes a no-op/duplicate, not a second delivery.

### Task 4 — Integration and regression

Update existing recovery/delivery tests only where the new explicit `DELIVERY_FAILED` state is the truthful replacement for ambiguous `BUILDING`.

Run/verify:
- targeted R7 tests;
- full unit/regression suite;
- V3 CI repository harness;
- FPL V6 CI contracts;
- Repository governance;
- Repository naming policy;
- exact-head PR verification;
- guarded merge;
- post-merge `main` verification.

## Non-goals

- No R8 chaos/soak expansion beyond existing CI gates.
- No scheduler redesign.
- No new data source or fallback.
- No duplicate R4/R5/R6 validator.
- No synthetic `PASS_DEGRADED` delivery status unless a future canonical Runtime Contract explicitly defines one.
