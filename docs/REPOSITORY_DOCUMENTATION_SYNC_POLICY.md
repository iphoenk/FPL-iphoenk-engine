# Repository Documentation Synchronization Policy

> **Policy introduced:** `2026-09-20T23:34:18+07:00`

## Purpose

Repository documentation must describe the runtime that actually exists, not a historical design that has already been superseded.

This policy applies to FPL V6/V12 runtime, architecture, scheduler/control plane, source activation, decision/report ownership, recovery paths, production governance, and other user-visible repository descriptions.

## Required PR description metadata

Every pull request must include these lines:

```text
Change timestamp: YYYY-MM-DDTHH:MM:SS+07:00
Documentation sync: UPDATED | NOT_APPLICABLE
Documentation timestamp: YYYY-MM-DDTHH:MM:SS+07:00
```

Rules:

1. `Change timestamp` is mandatory for every PR and must include a timezone.
2. `Documentation sync: UPDATED` is mandatory when runtime, architecture, control plane, methodology authority, scheduler, source activation, production workflow, or governance behavior changes.
3. When `UPDATED` is used, at least one relevant repository documentation file must change in the same PR and `Documentation timestamp` is mandatory.
4. `NOT_APPLICABLE` is allowed only when the change cannot make runtime-facing documentation stale.
5. A stale document must never be preserved merely to avoid broadening a bounded repair. The documentation change may remain concise, but it must describe the resulting runtime truth.

## Runtime-relevant paths

Repository governance treats changes under these surfaces as runtime/documentation relevant:

- `src/runtime_v6/`
- `src/engines/`
- `src/models/`
- `config/v6/`
- `config/intelligence/`
- `control/fpl_master_v12/`
- `.github/workflows/`
- dependency lock files used by V6/V12 CI/runtime
- `README.md`

When those surfaces change, update the relevant architecture/runtime documentation in the same PR.

## Timestamp placement in documents

Runtime-projection documents should carry a visible synchronization timestamp near the top, for example:

```text
Last runtime/documentation sync: 2026-09-20T23:34:18+07:00
```

The timestamp states when that document was reconciled to the implementation. It does not replace live runtime timestamps from `runtime-data-v6`.

## Authority rule

Documentation is descriptive, not a second runtime authority.

For current behavior use the actual code/config/control-plane authorities. In particular:

- V6 factual runtime policy: active code/config plus `runtime-data-v6`;
- V12 operational/methodology/report authority: `control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt`;
- V12 durable state: `control/fpl_master_v12/FPL_MASTER_STATE_V12.json`, non-authoritative;
- scheduler authority: current ChatGPT Automation plus `config/v6/schedule_policy.json`.

If documentation and runtime conflict, treat it as documentation drift and repair the documentation immediately.

## Enforcement

`.github/workflows/repository-governance.yml` enforces:

- PR description change timestamp;
- documentation-sync declaration;
- documentation timestamp when updated;
- same-PR documentation change for runtime/architecture/governance modifications.

The PR template includes the required fields.
