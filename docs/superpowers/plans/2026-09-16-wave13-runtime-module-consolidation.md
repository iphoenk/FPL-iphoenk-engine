# Wave 13 Runtime Module Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the flat V6 runtime into explicit domain packages while preserving every production behavior and legacy import/CLI entrypoint.

**Architecture:** Canonical implementations move into seven domain packages. Existing flat modules become thin compatibility facades that re-export domain implementations, so current workflows/tests/imports remain valid while new code has clear ownership boundaries.

**Tech Stack:** Python 3.12, pytest, GitHub Actions, existing V6 hash-locked dependencies.

**Spec:** `docs/superpowers/specs/2026-09-16-wave13-runtime-module-consolidation-design.md`

## Global Constraints
- No V3/V4/V5 runtime fallback or dependency.
- No new deployed microservices.
- No registry/source activation semantic changes.
- No scheduler, recovery, report-slot, publisher, or workflow behavior redesign.
- Flat import/CLI compatibility must remain intact.
- Domain canonical implementations must never import their flat facade equivalents.

---

### Task 1: Structural Guard and Domain Packages

**Files:**
- Create: `tests/test_data_platform_runtime_domain_packages.py`
- Create: `src/runtime_v6/{acquisition,identity,publication,control_plane,report_plane,observability,governance}/__init__.py`

**Interfaces:**
- Produces seven importable domain namespaces and structural acceptance guards.

- [ ] Write failing tests asserting all seven packages exist/import, the migration map has unique ownership, and facade direction is one-way.
- [ ] Run the focused test and confirm RED before package creation.
- [ ] Create package `__init__.py` files and a single `DOMAIN_MODULE_MAP` ownership manifest in `src/runtime_v6/domain_layout.py`.
- [ ] Re-run focused tests to PASS.

### Task 2: Control Plane Migration

**Files:**
- Canonical move into `src/runtime_v6/control_plane/`: `control_plane.py`, `temporal.py`, `schedule_policy.py`, `scheduled_report_slot.py`, `runtime_control.py`, `workflow_control.py`, `scheduler_watchdog.py`, `scheduler_recovery.py`, `legacy_scheduler_compat.py`.
- Replace corresponding flat modules with compatibility facades.

**Interfaces:**
- Legacy imports such as `src.runtime_v6.temporal.parse_timestamp` remain valid.
- Canonical imports become `src.runtime_v6.control_plane.temporal.parse_timestamp`.

- [ ] Copy implementations to domain package and adjust relative imports.
- [ ] Replace flat files with re-export facades and `main()` passthrough where applicable.
- [ ] Run temporal, schedule, runtime-control, workflow-control, watchdog/recovery tests.
- [ ] Run import-cycle/ownership structural test.

### Task 3: Report Plane Migration

**Files:**
- Canonical move into `src/runtime_v6/report_plane/`: `consumer.py`, `delivery_integrity.py`, `report_contract.py`, `report_compute.py`, `report_delivery.py`, `report_prefetch.py`, `report_qa.py`, `report_recovery.py`, `report_recovery_closeout.py`, `report_trigger.py`, `prefetch_contract.py`, `personal_prefetch.py`, `league_prefetch.py`.
- Replace flat modules with compatibility facades.

- [ ] Move canonical implementations and rewrite internal imports toward canonical packages.
- [ ] Preserve old import and CLI/module entrypoints.
- [ ] Run all `test_data_platform_report_*`, AD_HOC E2E, public-prefetch, and exact-scope recovery tests.
- [ ] Run structural no-back-import test.

### Task 4: Observability Migration

**Files:**
- Canonical move into `src/runtime_v6/observability/`: `current_health.py`, `health.py`, `operational_ledger.py`, `operational_reliability.py`, `player_observation.py`, `report_observability.py`.

- [ ] Move implementations and replace flat modules with facades.
- [ ] Run current-health, operational reliability, player observation, report observability, scheduler age tests.
- [ ] Run structural guard.

### Task 5: Identity Migration

**Files:**
- Canonical move into `src/runtime_v6/identity/`: `entity_scope.py`, `identity.py`, `identity_scope.py`, `identity_coverage.py`, `verified_bridges.py`, `verified_crosswalks.py`.

- [ ] Move deterministic identity implementations and preserve public imports.
- [ ] Run identity, coverage, FFScout identity, crosswalk and provider-limitation tests.
- [ ] Run structural guard.

### Task 6: Acquisition Migration

**Files:**
- Canonical move into `src/runtime_v6/acquisition/`: `adapters.py`, `collector.py`, `http_client.py`, `official_fpl_client.py`, `polling.py`, `source_native.py`, `noauth_source_native.py`, `ffscout_public.py`, `normalizer.py`, `rotowire_normalizer.py`.

- [ ] Move transport/acquisition implementations and preserve public imports.
- [ ] Run ingestion, adaptive polling, source-native, Rotowire and noauth-source tests.
- [ ] Run structural guard.

### Task 7: Publication Migration

**Files:**
- Canonical move into `src/runtime_v6/publication/`: `artifact_catalog.py`, `artifact_migration.py`, `artifact_provenance.py`, `production_validate.py`, `publish_integrity.py`, `store.py`, `registry.py`.

- [ ] Move publication/storage/registry implementations and preserve public imports.
- [ ] Run artifact migration/provenance, publish integrity, publisher governance, registry alignment and production acceptance tests.
- [ ] Verify registry behavior and source activation fingerprints are unchanged.
- [ ] Run structural guard.

### Task 8: Governance Migration

**Files:**
- Canonical move into `src/runtime_v6/governance/`: `architecture_independence_validate.py`, `authority_contract.py`, `season_contract.py`, `security.py`, `source_contract_doc.py`, `source_policy.py`.

- [ ] Move governance implementations and preserve executable flat entrypoints.
- [ ] Update validators so domain package structure is accepted and facade direction is enforced.
- [ ] Run architecture independence, authority, source policy and repository policy checks.

### Task 9: Full Verification and PR Closeout

- [ ] Run `python -m pytest -q tests/test_data_ingestion_engine.py tests/test_adaptive_polling.py tests/test_data_platform_*.py tests/test_data_platform_production_acceptance.py` and require zero failures.
- [ ] Run architecture independence validator and authority contract.
- [ ] Run Wave 3 chaos matrix and require canonical acceptance 16/16.
- [ ] Open PR against `main` and require naming, repository governance and V6 gates green.
- [ ] Merge with expected-head protection only after all pre-merge gates PASS.
- [ ] Verify post-merge `main` repeats full suite, chaos, architecture, authority, publisher config and governance with zero failures.
