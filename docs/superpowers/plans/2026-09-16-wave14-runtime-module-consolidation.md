# Wave 14 Runtime Module Consolidation Implementation Plan

**Goal:** Consolidate the flat V6 runtime into explicit canonical domain packages while preserving production behavior and legacy import/CLI entrypoints.

**Canonical architecture:** `src/runtime_v6/domains/{acquisition,identity,publication,control_plane,report_plane,observability,governance}/`. Existing flat modules remain compatibility facades only. Cross-domain ports must resolve canonical-to-canonical when an owner has been migrated.

**Spec:** `docs/superpowers/specs/2026-09-16-wave14-runtime-module-consolidation-design.md`

## Global Constraints
- No V3/V4/V5 runtime fallback or dependency.
- No new deployed microservices.
- No registry/source activation semantic changes.
- No scheduler, recovery, report-slot, publisher, or workflow behavior redesign.
- Flat import/CLI compatibility remains intact.
- Canonical domain implementations never import their own flat facade equivalents.

## Execution Status

### Task 1 — Structural Guard and Domain Packages
- [x] Create `src/runtime_v6/domains/` and seven domain namespaces.
- [x] Add `DOMAIN_MODULE_MAP` ownership manifest.
- [x] Add structural acceptance guards for unique ownership and one-way facade direction.

### Task 2 — Control Plane
- [x] Move canonical control-plane implementations under `domains/control_plane/`.
- [x] Preserve flat imports and executable entrypoints.
- [x] Pass focused and full regression gates.

### Task 3 — Report Plane
- [x] Move canonical report-plane implementations under `domains/report_plane/`.
- [x] Preserve report state-machine, QA, delivery, recovery and prefetch semantics.
- [x] Collapse temporary staged ports to canonical-to-canonical owners.
- [x] Pass focused and full regression gates.

### Task 4 — Observability
- [x] Move canonical observability implementations under `domains/observability/`.
- [x] Preserve health, ledger, reliability and report-observability semantics.
- [x] Pass focused and full regression gates.

### Task 5 — Identity
- [x] Move deterministic identity implementations under `domains/identity/`.
- [x] Preserve coverage, crosswalk and deterministic-join behavior.
- [x] Pass focused and full regression gates.

### Task 6 — Acquisition
- [x] Move acquisition, transport, adapter and normalization implementations under `domains/acquisition/`.
- [x] Preserve public imports and runtime composition behavior.
- [x] Pass full 647-test regression at the migration boundary.

### Task 7 — Publication
- [x] Move artifact, store, registry, integrity and production validation implementations under `domains/publication/`.
- [x] Fix canonical registry root ownership without changing registry semantics.
- [x] Retarget stale static guards to the canonical production validator.
- [x] Pass full 647/647 regression, architecture, authority and repository governance gates.

### Task 8 — Governance
- [x] Move architecture independence, authority, season, security, source-contract and source-policy implementations under `domains/governance/`.
- [x] Preserve enforcement semantics and executable flat entrypoints.
- [x] Pass V6 CI, repository governance and naming policy.

### Task 9 — Bridge Cleanup
- [x] Audit staged canonical ports for flat-facade detours.
- [x] Collapse Report Plane staged ports to canonical owner domains.
- [x] Verify bridge-cleanup HEAD passes V6 CI, repository governance and naming policy.

### Task 10 — Final Verification and PR Closeout
- [x] Verify full V6 regression suite with zero failures on final head.
- [x] Verify architecture independence and zero-downstream-authority contract.
- [x] Run Wave 3 chaos matrix and require canonical acceptance 16/16.
- [x] Verify PR #565 required pre-merge gates all PASS on exact final head `bcf06e81dc1252e727100107eb99809f7ddf0864`.
- [x] Merge PR #565 with expected-head protection; merge commit `62998909b1edc66cacfd98ebe0df0c26ccaf52d8`.
- [x] Verify post-merge `main` repeats the full suite, chaos, architecture, authority, publisher configuration, repository governance and naming policy with zero failures.
- [x] Post-merge V6 regression: 647/647 PASS.
- [x] Post-merge controlled-chaos acceptance: 16/16 PASS with zero missing/failed scenarios.

## Definition of GREEN
Wave 14 is GREEN only after Task 10 is complete. All implementation and final production-verification gates above are complete.

## Numbering Note
Runtime Module Consolidation was originally executed under a provisional Wave 13 label. The canonical revised sequence assigns it to Wave 14. Historical branch/merge labels remain untouched as audit history; this plan, the matching spec, and PR #565 metadata use the corrected Wave 14 designation.
