# Wave 15 Workflow & CI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden V6 workflow entrypoints and CI change-detection/ownership while preserving report delivery, scheduler, recovery, registry, and publication semantics.

**Architecture:** Production workflows call canonical `src.runtime_v6.domains.*` owners directly. A single Python CI contract classifies V6-owned changed paths from cumulative PR diffs; Repository Governance remains the pre-merge owner and FPL V6 CI remains the post-merge owner.

**Tech Stack:** Python 3.12, pytest, GitHub Actions YAML, existing V6 runtime/domain modules.

**Spec:** `docs/superpowers/specs/2026-09-16-wave15-workflow-ci-hardening-design.md`

## Global Constraints
- No change to ChatGPT FPL Master Monitor scheduler authority.
- No change to Issue #431 `FPL_MASTER_SLOT` transport.
- No change to report-slot/delivery state machine or delivery-proof requirements.
- No change to watchdog `MONITORING_ONLY` authority.
- No change to recovery `SAFE_RECOVERY_ONLY` authority.
- No change to registry/source activation semantics.
- No change to atomic publisher/lease semantics.
- No V3/V4/V5 fallback.
- Flat compatibility facades remain available; production workflows simply stop depending on them where canonical owners exist.

---

### Task 1: RED structural acceptance tests

**Files:**
- Create: `tests/test_data_platform_wave15_workflow_ci_hardening.py`
- Read: `.github/workflows/v6-natural-data-ingestion.yml`
- Read: `.github/workflows/v6-scheduler-watchdog.yml`
- Read: `.github/workflows/v6-core-recovery-guard.yml`
- Read: `.github/workflows/repository-governance.yml`
- Read: `.github/workflows/v6-ci.yml`

**Interfaces:**
- Consumes: `src.runtime_v6.domain_layout.DOMAIN_MODULE_MAP`
- Produces: failing structural assertions that define Wave 15 acceptance.

- [ ] Add a test that scans operational V6 workflows and rejects `python -m src.runtime_v6.<module>` when `<module>` has a canonical domain owner.
- [ ] Add a test that requires a single `src/platform/v6_ci_contract.py` classifier with cumulative changed-path evaluation.
- [ ] Add tests that Repository Governance is the PR full-verify owner and V6 CI is the push/main full-verify + chaos owner.
- [ ] Add a regression using `resolve_report_slot_decision(...)` proving `v6_already_published=True` cannot mark a due report delivered without same-slot valid delivery proof.
- [ ] Run the focused test and confirm it fails only on missing Wave 15 implementation.

### Task 2: Canonical V6 CI change-surface owner

**Files:**
- Create: `src/platform/v6_ci_contract.py`
- Modify: `.github/workflows/repository-governance.yml`
- Test: `tests/test_data_platform_wave15_workflow_ci_hardening.py`

**Interfaces:**
- Produces: `is_v6_owned_path(path: str) -> bool`, `requires_v6_verification(paths: Iterable[str]) -> bool`, CLI command `changed-paths` reading newline-delimited paths from stdin and printing `true`/`false`.

- [ ] Implement explicit canonical path matchers for V6 config, docs, runtime, lockfiles, tests, and V6 workflow/governance files.
- [ ] Make the classifier deterministic and side-effect free.
- [ ] Update Repository Governance detection to compute `git diff --name-only "$BASE_SHA" "$HEAD_SHA"` and pipe the complete list to `python src/platform/v6_ci_contract.py changed-paths`.
- [ ] Preserve push/main delegation behavior unchanged.
- [ ] Run focused Wave 15 tests until GREEN.

### Task 3: Canonical production workflow entrypoints

**Files:**
- Modify: `.github/workflows/v6-natural-data-ingestion.yml`
- Modify: `.github/workflows/v6-scheduler-watchdog.yml`
- Modify: `.github/workflows/v6-core-recovery-guard.yml`
- Modify where applicable: `.github/workflows/v6-wave3-natural-proof.yml`
- Modify: `src/platform/production_path_governance_validate.py`
- Modify affected static tests.

**Interfaces:**
- Consumes: `DOMAIN_MODULE_MAP` canonical domain ownership.
- Produces: direct canonical module invocations in production/control workflows.

- [ ] Replace `workflow_control` invocation with `src.runtime_v6.domains.control_plane.workflow_control`.
- [ ] Replace `collector` with `src.runtime_v6.domains.acquisition.collector`.
- [ ] Replace `runtime_control`, `scheduler_watchdog`, and `scheduler_recovery` with canonical control-plane module paths.
- [ ] Replace `production_validate`, `publish_integrity`, and other migrated publication modules with canonical publication paths.
- [ ] Replace migrated report-plane workflow entrypoints with canonical report-plane paths.
- [ ] Leave non-domain historical/backfill/Wave-3 proof modules unchanged.
- [ ] Update governance/static tests from old flat markers to canonical markers without loosening behavioral assertions.
- [ ] Run focused workflow/governance tests.

### Task 4: CI ownership and anti-drift guards

**Files:**
- Modify: `.github/workflows/v6-ci.yml`
- Modify: `.github/workflows/repository-governance.yml`
- Test: `tests/test_data_platform_wave15_workflow_ci_hardening.py`

**Interfaces:**
- PR: Repository Governance owns full V6 verify/publisher gate when V6 surface changed.
- Push/main: FPL V6 CI owns full regression, chaos, publisher config, post-merge gate.

- [ ] Add structural assertions that Repository Governance PR detection uses the canonical classifier.
- [ ] Add structural assertions that V6 CI push/main always resolves `v6_changed=true` and still runs chaos acceptance.
- [ ] Ensure no workflow tries to infer due-report delivery from V6 CI/acquisition success.
- [ ] Avoid introducing a second required pre-merge owner.

### Task 5: Full regression and protected report behavior

**Files:** existing tests only unless a stale static assertion must be retargeted.

- [ ] Run full V6 regression suite.
- [ ] Confirm scheduler-authority tests PASS.
- [ ] Confirm publisher-governance tests PASS.
- [ ] Confirm delivery-integrity/report recovery tests PASS, including due-report independence.
- [ ] Confirm architecture independence and authority contract PASS.

### Task 6: PR closeout and post-merge verification

**Files:**
- Update: this plan execution status after proof is complete.

- [ ] Open Wave 15 PR.
- [ ] Require exact-head Repository Governance, Naming, and V6-required verification PASS.
- [ ] Merge with expected-head protection.
- [ ] On merge SHA, require FPL V6 CI full regression PASS.
- [ ] Require controlled chaos canonical acceptance 16/16 with zero missing/failed scenarios.
- [ ] Require post-merge V6 governance gate, repository governance, publisher config, and naming PASS.
- [ ] Verify `main` still points to the tested merge SHA before declaring GREEN.

## Definition of GREEN
Wave 15 is GREEN only when production workflows use canonical domain entrypoints, cumulative PR change detection is canonical and false-skip resistant, report-delivery independence remains protected, all pre-merge gates are green, and the same guarantees are re-proven on post-merge `main` with full regression and 16/16 chaos acceptance.
