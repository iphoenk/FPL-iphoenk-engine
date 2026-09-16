# Wave 14 Runtime Module Consolidation — Design

## Objective
Consolidate the flat `src/runtime_v6` module surface into explicit canonical domain packages while preserving production behavior, public imports, CLI/module entrypoints, scheduler authority, publication semantics, report-slot state machines, registry semantics, and V6 isolation.

## Constraints
- No V3/V4/V5 runtime fallback or dependency.
- No new deployed microservices.
- No workflow behavior redesign.
- No registry/source activation semantic changes.
- No publisher flow redesign.
- No scheduler/recovery/report-delivery semantic changes.
- Existing flat imports remain supported through compatibility facades.
- Canonical domain modules must not route back through flat facades when a canonical owner exists.

## Canonical Layout

All canonical implementations live under `src/runtime_v6/domains/`:

```text
src/runtime_v6/
├── domains/
│   ├── acquisition/
│   ├── identity/
│   ├── publication/
│   ├── control_plane/
│   ├── report_plane/
│   ├── observability/
│   └── governance/
├── domain_layout.py
└── <flat legacy modules> -> compatibility facades/re-exports
```

Domain ownership is recorded in `DOMAIN_MODULE_MAP` and guarded structurally. Historical/backfill modules and Wave 2/3 acceptance/proof modules may remain flat when they are evidence/acceptance surfaces rather than core production ownership.

## Dependency Direction

```text
governance ─┐
            ├─> shared config/store contracts
control_plane ─> publication / observability
acquisition ─> identity ─> publication
report_plane ─> publication + observability + control_plane contracts
observability ─> publication/shared temporal contracts
```

Rules:
1. Flat facades may import canonical domain implementations.
2. Canonical domain implementations must not import their own flat facade equivalents.
3. Cross-domain ports must resolve directly to the canonical owner domain rather than detouring through a flat facade.
4. Root/path discovery must use canonical repository-root ownership rather than file-depth assumptions after a move.

## Compatibility Strategy
For each migrated module:
1. Preserve implementation semantics while moving ownership into `src/runtime_v6/domains/<domain>/`.
2. Rewrite only imports/path-root wiring required by the new ownership boundary.
3. Replace the original flat module with a thin compatibility facade; preserve `main()` passthrough for executable modules.
4. Preserve exported names, monkeypatch/module alias behavior where required, and workflow module entrypoints.
5. Maintain structural tests that prove one-way facade direction and unique domain ownership.

## Migration Order
1. Control Plane
2. Report Plane
3. Observability
4. Identity
5. Acquisition
6. Publication
7. Governance
8. Collapse temporary staged bridges to canonical-to-canonical ports
9. Full regression, chaos, PR and post-merge closeout

## Acceptance Gates
Wave 14 is complete only when all are true:
- Seven canonical domain packages exist under `src/runtime_v6/domains/`.
- `DOMAIN_MODULE_MAP` has unique ownership and structural guards pass.
- Flat compatibility imports continue to resolve existing public names.
- Canonical domain modules do not import their own flat facade equivalents.
- Staged cross-domain bridges resolve canonical-to-canonical where canonical owners exist.
- No circular import is introduced in migrated modules.
- Existing workflow module entrypoints still execute through compatibility facades.
- Registry behavior and source activation semantics are unchanged.
- Scheduler/control-plane behavior is unchanged.
- Report delivery/recovery behavior is unchanged.
- Publisher/publication behavior is unchanged.
- Architecture independence PASS.
- Zero-downstream-authority contract PASS.
- Repository policy PASS.
- Naming policy PASS.
- Full V6 regression suite PASS with zero failures.
- Wave 3 chaos tests PASS and canonical chaos acceptance is 16/16.
- PR pre-merge required gates PASS.
- Post-merge `main` repeats full V6 regression, chaos, architecture, authority, publisher configuration and repository governance with zero failures.

## Non-goals
- No source-provider redesign.
- No new application features.
- No unrelated performance tuning.
- No removal of supported flat import paths in Wave 14.
- No migration or fallback to V3/V4/V5.

## Numbering Note
This work was originally implemented under a provisional Wave 13 label. The revised canonical hardening sequence designates Runtime Module Consolidation as Wave 14. Historical branch and merge-commit labels are retained as immutable audit history; current documentation and PR metadata use Wave 14.
