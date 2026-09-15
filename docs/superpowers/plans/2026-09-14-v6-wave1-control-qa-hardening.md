# V6 Wave 1 Control Plane + QA/QC Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close V6 control-plane, QA/QC, recovery classification, readiness semantics, control-endpoint, and architecture-boundary gaps without changing V6 data-plane authority or publication behavior.

**Architecture:** Keep V6 as a data-only modular pipeline with an independent GitHub control plane and isolated runtime publisher. Harden change detection and policy invariants first, then make recovery/readiness semantics explicit and add boundary/preflight guards. Do not introduce workflow chaining, network microservices, V3/V4/V5 fallback, or new decision authority.

**Tech Stack:** Python 3, pytest/unittest-style repository tests, GitHub Actions YAML, JSON policy/config, GitHub repository governance validators.

**Spec:** REKOMENDASI V6 POST WAVE2.md plus the consolidated two-wave audit approved by the user on 2026-09-14.

## Global Constraints

- Wave 1 only; do not mix Wave 2 structural refactors.
- V6 remains data-only and must not import or call V3/V4/V5 as fallback.
- ChatGPT FPL Master Monitor remains scheduler authority.
- Manual recovery remains non-authoritative scheduler proof.
- Optional provider identity/join incompleteness must remain non-blocking for source-native factual readiness.
- Publisher authority and runtime-data-v6 publication isolation must remain unchanged.
- Use test-first changes and preserve existing successful runtime behavior.

---

### Task 1: Make every `v6-*.yml` part of the V6 QA surface

**Files:**
- Modify: `.github/workflows/v6-ci.yml`
- Modify: `.github/workflows/repository-governance.yml`
- Create: `tests/test_data_platform_v6_workflow_qa_surface.py`

**Interfaces:**
- Consumes: repository workflow filenames under `.github/workflows/v6-*.yml`.
- Produces: generic V6 workflow path detection and a regression test that fails when the QA surface becomes enumerated/incomplete.

- [ ] Write failing tests asserting V6 CI uses a generic `v6-*.yml` path and repository-governance detects all V6 workflow filenames.
- [ ] Run the focused test and verify the current configuration fails.
- [ ] Replace enumerated V6 workflow path detection with generic V6 workflow matching.
- [ ] Re-run focused tests and existing governance tests.

### Task 2: Add cross-config control-plane invariants and clarify threshold semantics

**Files:**
- Modify: `config/v6/scheduler_watchdog.json`
- Modify: `config/v6/schedule_policy.json` only if additive naming/metadata is required.
- Modify/Create: focused scheduler policy/watchdog tests.

**Interfaces:**
- Consumes: canonical scheduler policy and watchdog policy.
- Produces: explicit proof-fresh/late/watchdog-warning/critical semantics and invariant checks preventing drift.

- [ ] Write failing invariant tests for authority, cadence/critical boundary, issue number, and documented threshold ordering.
- [ ] Verify RED.
- [ ] Add only the minimum metadata/validation needed to make semantics explicit; do not make cron dynamic.
- [ ] Verify focused and governance tests GREEN.

### Task 3: Classify recovery cooldown from actual recovery evidence

**Files:**
- Modify: `src/runtime_v6/scheduler_recovery.py`
- Modify: `.github/workflows/v6-core-recovery-guard.yml` only if explicit evidence must be passed.
- Modify: `config/v6/scheduler_recovery.json` only for additive identification metadata if needed.
- Modify: `tests/test_data_platform_scheduler_recovery_guard.py`

**Interfaces:**
- Consumes: recent ingestion workflow-run metadata plus recovery policy.
- Produces: cooldown applies to prior recovery dispatches, not unrelated `report_prefetch` workflow-dispatch activity.

- [ ] Write regression test demonstrating unrelated workflow-dispatch/report-prefetch must not consume recovery cooldown.
- [ ] Verify RED.
- [ ] Implement the smallest reliable recovery-identification rule supported by available run metadata/workflow naming.
- [ ] Verify focused tests and scheduler guard tests GREEN.

### Task 4: Make readiness dimensions explicit without changing blocking policy

**Files:**
- Modify: `src/runtime_v6/health.py`
- Modify: health/semantic tests.

**Interfaces:**
- Consumes: existing operational, data and join readiness dimensions.
- Produces: explicit `source_native_readiness_overall` and `join_readiness_overall` while retaining any compatibility alias required by consumers.

- [ ] Write failing tests for the new explicit readiness keys and non-blocking identity behavior.
- [ ] Verify RED.
- [ ] Add additive readiness fields; preserve existing fallback/blocking semantics.
- [ ] Verify focused tests GREEN.

### Task 5: Add control-endpoint preflight/invariant coverage

**Files:**
- Modify: production/control-plane governance validator or create a focused V6 control preflight module if no suitable home exists.
- Modify: corresponding tests.

**Interfaces:**
- Consumes: schedule policy control issue, marker, scheduler authority and transport contract.
- Produces: deterministic validation distinguishing control-plane contract failures from acquisition failures.

- [ ] Write failing contract tests for issue/marker/authority/transport policy consistency.
- [ ] Verify RED.
- [ ] Add fail-closed static/config preflight validation without adding a second acquisition path.
- [ ] Verify governance tests GREEN.

### Task 6: Harden architecture boundary against relative-import escape

**Files:**
- Modify: `src/runtime_v6/architecture_independence_validate.py`
- Modify: corresponding architecture tests.

**Interfaces:**
- Consumes: Python AST imports under `src/runtime_v6`.
- Produces: rejection of unapproved relative imports escaping the runtime_v6 package boundary, while preserving explicit allowlisted platform dependencies.

- [ ] Write failing tests with representative `from ..sibling import x` escape cases.
- [ ] Verify RED.
- [ ] Extend AST boundary validation minimally.
- [ ] Verify architecture and full V6 tests GREEN.

### Task 7: Wave 1 verification and PR evidence

**Files:**
- No production files unless verification exposes a regression.

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: fresh test/governance evidence and a reviewable Wave 1 PR.

- [ ] Run focused tests for each task.
- [ ] Run full V6 test suite / governance verification used by repository CI.
- [ ] Inspect branch diff for accidental Wave 2 changes.
- [ ] Open PR to `main` with explicit non-goals and verification evidence.
