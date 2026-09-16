# Wave 13 Runtime Module Consolidation — Design

## Objective
Consolidate the flat `src/runtime_v6` module surface into explicit domain packages while preserving production behavior, public imports, CLI/module entrypoints, scheduler authority, publication semantics, report-slot state machines, registry semantics, and V6 isolation.

## Constraints
- No V3/V4/V5 runtime fallback or dependency.
- No new deployed microservices.
- No workflow behavior redesign.
- No registry/source activation semantic changes.
- No publisher flow redesign.
- No scheduler/recovery/report delivery semantic changes.
- Existing flat imports must continue to work through compatibility facades.
- Migration is staged and reversible at module granularity.

## Target Architecture

```text
src/runtime_v6/
├── acquisition/
│   ├── adapters.py
│   ├── collector.py
│   ├── http_client.py
│   ├── official_fpl_client.py
│   ├── polling.py
│   ├── source_native.py
│   ├── noauth_source_native.py
│   ├── ffscout_public.py
│   └── normalizer.py
├── identity/
│   ├── entity_scope.py
│   ├── identity.py
│   ├── identity_scope.py
│   ├── identity_coverage.py
│   ├── verified_bridges.py
│   └── verified_crosswalks.py
├── publication/
│   ├── artifact_catalog.py
│   ├── artifact_migration.py
│   ├── artifact_provenance.py
│   ├── production_validate.py
│   ├── publish_integrity.py
│   └── store.py
├── control_plane/
│   ├── control_plane.py
│   ├── temporal.py
│   ├── schedule_policy.py
│   ├── scheduled_report_slot.py
│   ├── runtime_control.py
│   ├── workflow_control.py
│   ├── scheduler_watchdog.py
│   ├── scheduler_recovery.py
│   └── legacy_scheduler_compat.py
├── report_plane/
│   ├── consumer.py
│   ├── delivery_integrity.py
│   ├── report_contract.py
│   ├── report_compute.py
│   ├── report_delivery.py
│   ├── report_prefetch.py
│   ├── report_qa.py
│   ├── report_recovery.py
│   ├── report_recovery_closeout.py
│   ├── report_trigger.py
│   ├── prefetch_contract.py
│   ├── personal_prefetch.py
│   └── league_prefetch.py
├── observability/
│   ├── current_health.py
│   ├── health.py
│   ├── operational_ledger.py
│   ├── operational_reliability.py
│   ├── player_observation.py
│   └── report_observability.py
├── governance/
│   ├── architecture_independence_validate.py
│   ├── authority_contract.py
│   ├── season_contract.py
│   ├── security.py
│   ├── source_contract_doc.py
│   └── source_policy.py
└── <flat legacy modules> -> compatibility facades/re-exports
```

Historical/backfill modules and Wave 2/3 acceptance/proof modules remain flat in Wave 13 unless required by a migrated dependency. They are explicitly not part of the first structural move because they are evidence/acceptance surfaces rather than core production domains.

## Dependency Direction
The intended dependency direction is:

```text
governance ─┐
            ├─> shared config/store contracts
control_plane ─> publication / observability
acquisition ─> identity ─> publication
report_plane ─> publication + observability + control_plane contracts
observability ─> publication/shared temporal contracts
```

Domain packages must not import legacy flat facade modules when the canonical implementation already exists inside a domain package. Flat facades may import domain implementations, never the reverse.

## Compatibility Strategy
For each migrated module:
1. Copy the implementation into the destination domain package.
2. Rewrite relative imports to domain-qualified canonical imports where needed.
3. Replace the original flat module with a thin compatibility facade using explicit re-export or wildcard re-export plus `main()` passthrough when the old module is executable.
4. Preserve exported names and CLI behavior.
5. Add structural tests proving the canonical implementation lives in the domain package and the flat module is facade-only.

## Migration Order
1. Control plane — already cohesive after Wave 12 and has the clearest boundaries.
2. Report plane — strong contract/test coverage and clear state-machine ownership.
3. Observability — depends on control/report contracts but is read-mostly.
4. Identity — deterministic mapping/crosswalk surface.
5. Acquisition — transports/adapters/normalization.
6. Publication — artifact/publish/store boundary.
7. Governance — validators/contracts; migrated last because they inspect repository structure.

Each stage must pass focused tests before the next stage begins.

## Acceptance Gates
Wave 13 is complete only when all are true:
- Domain package structure exists with `__init__.py` for every target package.
- Flat compatibility imports continue to resolve existing public names.
- Canonical domain modules do not import their own flat facade equivalents.
- No circular import is introduced in migrated modules.
- Existing workflow module entrypoints still execute through compatibility facades.
- Registry behavior unchanged.
- Scheduler/control-plane behavior unchanged.
- Report delivery/recovery behavior unchanged.
- Publisher/publication behavior unchanged.
- Architecture independence PASS.
- Zero-downstream-authority contract PASS.
- Repository policy PASS.
- Naming policy PASS.
- Full V6 regression suite PASS with zero failures.
- Wave 3 chaos tests PASS and canonical chaos acceptance 16/16 PASS.
- Post-merge `main` verification repeats the same gates.

## Non-goals
- No source provider redesign.
- No new application features.
- No performance tuning unrelated to import/module structure.
- No removal of old import paths during this wave.
- No migration of V3/V4/V5 code.
