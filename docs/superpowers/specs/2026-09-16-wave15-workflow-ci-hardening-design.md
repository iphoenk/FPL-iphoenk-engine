# Wave 15 Workflow & CI Hardening — Design

## Objective
Harden V6 workflows and CI after Wave 14 domain consolidation without changing runtime decision semantics, scheduler authority, report delivery semantics, publication semantics, source activation, or recovery authority.

The primary goals are:
- production workflows invoke canonical `src.runtime_v6.domains.*` owners instead of flat compatibility facades whenever a canonical owner exists;
- V6 change-surface detection has one canonical implementation and evaluates cumulative PR diff rather than only a last commit;
- PR verification ownership remains in `repository-governance.yml` and post-merge verification ownership remains in `v6-ci.yml`;
- workflow CI contracts are structurally guarded against drift;
- due visible reports remain independently governed from V6/data-slot completion.

## Protected Behavior
Wave 15 MUST NOT change:
- ChatGPT FPL Master Monitor as the only normal hourly acquisition authority;
- Issue #431 `FPL_MASTER_SLOT` transport;
- report-slot state machine, `VISIBLE_EMITTED`, `REPORT_CONTRACT_PASS`, or same-slot delivery proof requirements;
- `DATA_SLOT FULFILLED != REPORT SLOT FULFILLED != VISIBLE REPORT DELIVERED`;
- watchdog role `MONITORING_ONLY` or its incident thresholds;
- recovery role `SAFE_RECOVERY_ONLY` or non-proof semantics;
- `runtime-data-v6` publication branch;
- registry/source activation behavior;
- dedicated V6 publisher credentials, isolated publisher, atomic publication, or force-with-lease behavior;
- V3/V4/V5 isolation and zero fallback.

## Architecture

### Canonical workflow entrypoints
Operational workflows call canonical owners directly:

```text
.github/workflows/*
  -> src.runtime_v6.domains.control_plane.*
  -> src.runtime_v6.domains.acquisition.*
  -> src.runtime_v6.domains.publication.*
  -> src.runtime_v6.domains.report_plane.*
  -> src.runtime_v6.domains.governance.*
```

Flat modules under `src/runtime_v6/*.py` remain compatibility facades for external/backward compatibility, but production workflows must not depend on those facades when the module has a canonical domain owner.

Historical/backfill or Wave-3 proof modules without a domain owner remain unchanged in Wave 15.

### Canonical V6 CI surface
One Python contract owns the V6-relevant path rules. Repository governance invokes this contract against cumulative PR changed paths. CI structural tests assert that workflow trigger path filters remain a superset of the same canonical surface.

The contract must include at least:
- `config/v6/**`
- `docs/V6_*.md`
- `src/runtime_v6/**`
- V6 lock files
- V6 data-platform tests
- V6 CI / ingestion / governance workflow files
- the Wave 15 contract implementation and its tests.

### Verification ownership
- Pull request: `repository-governance.yml` owns required full V6 verification and publisher-config validation when canonical V6 surface changed.
- Push to `main`: `v6-ci.yml` owns full regression, controlled chaos acceptance, publisher-config validation, and post-merge governance gate.
- `v6-ci.yml` may still trigger for PR path changes as informational coverage, but it must not become a second required pre-merge owner or create contradictory change detection.

### Report safety invariant
Wave 15 adds/retains regression coverage proving that a successful V6/data slot or `ALREADY_PUBLISHED` condition does not close a due visible report without report-slot delivery proof. Workflow/CI hardening must not alter this behavior.

## Implementation Strategy
Use staged, behavior-preserving hardening:
1. Add RED structural tests for canonical workflow entrypoints, canonical change-surface detection, cumulative PR semantics, and report-delivery independence.
2. Add one `src/platform/v6_ci_contract.py` owner for changed-path classification.
3. Retarget production workflow module invocations to canonical domain owners.
4. Retarget repository-governance detection to the canonical Python contract using base/head cumulative diff.
5. Keep `v6-ci.yml` push/main full verification behavior unchanged and add guards that PR/push ownership cannot drift.
6. Update production-path governance/static tests to canonical entrypoints.
7. Run full regression + chaos + governance before merge and repeat on `main`.

## Non-goals
- No reusable-workflow redesign in Wave 15.
- No GitHub Actions permission broadening.
- No new cron/scheduler.
- No report generation logic changes.
- No publisher implementation redesign.
- No source/provider changes.
- No removal of flat compatibility facades.

## Acceptance Gates
Wave 15 is GREEN only when all are true:
- production V6 workflows use canonical domain entrypoints wherever a domain owner exists;
- structural tests prove no operational workflow regresses to flat facades for migrated modules;
- one canonical V6 change-surface classifier is used for PR cumulative-diff detection;
- cumulative PR diff cannot false-skip because the latest commit is unrelated;
- PR verification remains owned by Repository Governance and post-merge verification remains owned by FPL V6 CI;
- report-delivery independence regression passes;
- scheduler/watchdog/recovery authority tests remain unchanged and PASS;
- publisher isolation/lease/governance tests remain unchanged and PASS;
- full V6 regression suite passes with zero failures;
- Wave 3 canonical controlled-chaos acceptance is 16/16;
- architecture independence PASS;
- zero-downstream-authority contract PASS;
- publisher configuration PASS;
- repository governance PASS;
- naming policy PASS;
- PR merged with expected-head protection;
- post-merge `main` repeats required gates with zero failures.
