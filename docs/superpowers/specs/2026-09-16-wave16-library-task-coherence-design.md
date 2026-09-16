# Wave 16 — Library + Task Coherence Design

## Goal
Keep the FPL Master Library authorities, the single recurring FPL Master Monitor automation, and repository runtime invariants coherent without making report delivery depend on a single successful Library read.

## Authority model
1. Latest explicit user instruction overrides all.
2. `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt` is the operational authority.
3. `/FPL/FPL_MASTER_SPEC_V11.txt` is the methodology/report-detail authority.
4. The legacy all-in-one V11 file is non-authoritative.
5. FPL Master Monitor is the only active recurring FPL decision/report automation.

## Hybrid safety-kernel
The automation must read the current Library authority at every run, but it also retains a minimal immutable safety kernel so a transient Library retrieval problem cannot suppress a due report. The kernel contains only:
- V6 only; never V3/V4/V5.
- hourly Asia/Jakarta :30 schedule and +/-90s scheduled occurrence identity.
- DATA_SLOT_FULFILLED != REPORT_SLOT_FULFILLED != REPORT_DELIVERED.
- mandatory visible checkpoints 04:30 Deep, 05:30 Price, 12:30 Deep, 21:30 Deep plus canonical Deadline/Final/Post-All-Match/live Match checkpoints.
- due report must never finish progress/status-only.
- mode-required exact-count gates, ICON+, weather handling, and actual-body QA.
- same-report-slot acknowledged delivery proof required before DELIVERED.
- if Library retrieval is degraded, continue using the safety kernel, label `CONTRACT SOURCE: DEGRADED`, and deliver the best truthful report rather than suppressing it.

Mutable presentation order, analytical methodology, and detailed report-mode semantics live only in Library and are not duplicated into the automation prompt.

## Scope
- Update Runtime Contract with Authority Coherence / Anti-Drift and fail-operational Library-read behavior.
- Replace the FPL Master Monitor prompt with the hybrid safety-kernel bootstrap.
- Preserve exact hourly :30 schedule, Asia/Jakarta timezone, enabled state, and automation identity.
- Keep all legacy FPL recurring/report helper automations disabled.
- No runtime/report-delivery code, scheduler authority, Issue #431 transport, registry, publication, or V3/V4/V5 behavior changes.

## Acceptance
- Runtime Contract readback contains anti-drift/fail-operational rules.
- Automation prompt reads Runtime Contract + Spec and contains only the safety kernel for duplicated invariants.
- Automation schedule remains exact hourly :30 Asia/Jakarta and enabled.
- Only FPL Master Monitor is active as recurring FPL decision/report authority.
- No active legacy FPL helper becomes enabled.
- Due-report safety semantics remain explicit: V6/data success never substitutes for report delivery proof.
