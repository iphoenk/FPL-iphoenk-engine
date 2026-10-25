# Repository Documentation Synchronization Policy

> **Policy introduced:** `2026-09-20T23:34:18+07:00`  
> **Last revised:** `2026-09-21T05:24:14+07:00`

## Purpose

Repository documentation must describe the runtime that actually exists, not a historical design that has already been superseded.

This policy applies to FPL V6/V12 runtime, architecture, scheduler/control plane, source activation, decision/report ownership, recovery paths, production governance, and other user-visible repository descriptions.

## Required PR description metadata

Every pull request must include these lines:

```text
Change timestamp: YYYY-MM-DDTHH:MM:SS+07:00
Documentation sync: UPDATED
Documentation timestamp: YYYY-MM-DDTHH:MM:SS+07:00
```

Rules:

1. `Change timestamp` is mandatory for every PR and must include a timezone.
2. `Documentation sync: UPDATED` is mandatory for every PR. `NOT_APPLICABLE` is not accepted.
3. Every PR must change `README.md` in the same PR, regardless of whether the implementation change is runtime-facing, test-only, documentation-only, or governance-only.
4. `Documentation timestamp` is mandatory for every PR and must exactly match the visible `Last runtime/documentation sync` timestamp in `README.md`.
5. Runtime, architecture, control-plane, methodology authority, scheduler, source activation, production workflow, or governance changes must additionally update every deeper documentation surface made stale by the change.
6. The mandatory README edit should be concise and update the relevant current-truth section rather than accumulate a noisy chronological changelog.
7. A stale document must never be preserved merely to keep a bounded repair artificially narrow.

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

Every PR updates `README.md`. When the runtime-relevant surfaces above change, also update every deeper architecture/runtime document affected by the resulting behavior.

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
- `Documentation sync: UPDATED` on every PR;
- documentation timestamp on every PR;
- mandatory same-PR `README.md` change;
- exact equality between the README visible synchronization timestamp and the PR `Documentation timestamp`;
- additional same-PR documentation changes whenever runtime/architecture/governance truth would otherwise become stale.

The PR template includes the required fields.

## Single integration owner for the README sync line (25 Oct 2026)

Governance requires every PR's `Documentation timestamp` to equal the README `Last runtime/documentation sync` line, so every PR touches that one line and concurrent PRs conflict on it. To keep this safe without weakening the check:

1. One integration owner (the session or person designated by the repository owner in the PR conversation) is the only one who rewrites that line when integrating. Author sessions put their own `Change timestamp` in the PR metadata and add their README bullet, but do not resolve a sync-line conflict themselves.
2. The owner merges one PR at a time: bring the branch up to date with `main`, set the sync line and the PR `Documentation timestamp` to one new timestamp later than both, wait for green CI on that exact head, then merge. Any movement of `main` repeats the revalidation.
3. Overlapping PRs (same README region, same governance baseline `BASELINE_TOTAL` or `REQUIRED_FILES`) are never merged concurrently.
4. `BASELINE_TOTAL` is recomputed by the owner at integration (collect-only over `REQUIRED_FILES`), never by guess.
5. This is process only. The equality check itself is unchanged; relaxing it would be a gate change requiring explicit owner authorization.
