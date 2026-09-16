# Wave 16 — Library + Task Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Library/task contract drift while preserving fail-operational visible-report delivery.

**Architecture:** Keep Library Runtime Contract as operational authority and Spec V11 as methodology/report authority. Reduce the FPL Master Monitor prompt to a hybrid bootstrap/safety-kernel so mutable contract detail is not duplicated, while due-report delivery remains protected if Library retrieval is temporarily degraded.

**Tech Stack:** ChatGPT Library files, Automations, GitHub documentation/audit trail.

**Spec:** `docs/superpowers/specs/2026-09-16-wave16-library-task-coherence-design.md`

## Global Constraints

- Latest explicit user instruction overrides Library/task text.
- Never use V3/V4/V5.
- Preserve FPL Master Monitor automation id, enabled state, exact hourly :30 Asia/Jakarta schedule, and scheduler authority.
- DATA_SLOT_FULFILLED != REPORT_SLOT_FULFILLED != REPORT_DELIVERED.
- A due report may never end progress/status-only.
- No repository runtime/report-delivery implementation changes in Wave 16.

---

### Task 1: Update Runtime Contract anti-drift rules

**Files:**
- Modify Library: `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt`

**Interfaces:**
- Consumes: current Runtime Contract V1.
- Produces: operational authority with explicit task-coherence and fail-operational Library-read rules.

- [ ] Read the current full Runtime Contract and preserve all existing behavior.
- [ ] Add `0A. AUTHORITY COHERENCE / ANTI-DRIFT` stating that the automation must not duplicate mutable report methodology/presentation detail and that Library is the current source of truth.
- [ ] Add fail-operational behavior: if Library retrieval fails/degrades, continue due-report execution using the task safety kernel, mark `CONTRACT SOURCE: DEGRADED`, never infer V3/V4/V5 fallback, and never suppress a due report solely because Library retrieval failed.
- [ ] Read back the complete updated file and verify all pre-existing report/delivery gates remain present.

### Task 2: Replace FPL Master Monitor prompt with hybrid safety-kernel

**Files:**
- Update Automation: `FPL Master Monitor` id `6a8b9315a70881918adb502120a1d02e`

**Interfaces:**
- Consumes: Runtime Contract and Spec V11.
- Produces: minimal bootstrap prompt that keeps immutable safety invariants but defers mutable detail to Library.

- [ ] Preserve title, enabled state, exact hourly :30 schedule, timezone, and automation id.
- [ ] Require full Runtime Contract read and mode-relevant Spec/Visible Report Catalog read at start of every run.
- [ ] Retain only the safety kernel: V6-only, +/-90-second scheduled occurrence, independent data/report/delivery states, mandatory visible checkpoints, hard content/delivery QA, weather/ICON+/exact-count gates, and same-slot acknowledged delivery proof.
- [ ] Add fail-operational `CONTRACT SOURCE: DEGRADED` behavior for Library read failure.
- [ ] Remove duplicated mutable methodology/presentation prose from the automation prompt.
- [ ] Read back automation state and prompt after update.

### Task 3: Coherence audit

**Files:**
- Read-only audit of Library and Automations.

**Interfaces:**
- Consumes: updated Library/task state.
- Produces: Wave 16 acceptance evidence.

- [ ] Verify `/FPL/FPL_MASTER_ALL_IN_ONE_CANONICAL_V11.txt` remains legacy/non-authoritative.
- [ ] Verify Runtime Contract and Spec V11 remain active authorities.
- [ ] Verify FPL Master Monitor is enabled and exact hourly :30 Asia/Jakarta.
- [ ] Verify no legacy FPL report/helper automation is active as a second recurring FPL authority.
- [ ] Verify task prompt contains explicit due-report fail-operational protection and no V3/V4/V5 fallback.
- [ ] Verify report delivery remains independent from data-slot success.

### Task 4: Repository audit trail closeout

**Files:**
- Create/merge Wave 16 design and plan documentation only.

**Interfaces:**
- Consumes: verified external-state acceptance.
- Produces: permanent Wave 16 design/plan audit trail without runtime behavior changes.

- [ ] Open PR from `wave16/library-task-coherence`.
- [ ] Confirm diff is documentation-only.
- [ ] Merge with expected-head protection after external coherence acceptance is GREEN.
- [ ] Verify `main` contains the Wave 16 docs and no runtime implementation files changed.
