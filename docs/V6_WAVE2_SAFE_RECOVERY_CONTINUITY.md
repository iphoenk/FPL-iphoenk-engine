# V6 Wave 2 — Safe Recovery Continuity

Status: implementation contract.

## Objective

Add a recovery-only continuity path without creating a second normal V6 acquisition scheduler and without manufacturing scheduler-health or Wave-3 natural-slot proof.

## Authority

Normal hourly V6 acquisition remains owned by the ChatGPT `FPL Master Monitor` through Issue #431 title transport `FPL_MASTER_SLOT ...`.

GitHub natural acquisition scheduling remains disabled. The Wave-1 scheduler watchdog remains monitoring-only.

Wave 2 adds `.github/workflows/v6-core-recovery-guard.yml` as a recovery-only control-plane schedule. It is not a normal scheduler authority.

## Recovery eligibility

The recovery guard may dispatch exactly one governed `manual_recovery` only when all of these are true:

1. The independent scheduler watchdog is `CRITICAL`.
2. No V6 ingestion run is queued, pending, waiting, requested, or in progress.
3. No recent governed core event is inside the settle window.
4. No recent workflow-dispatch recovery is inside the recovery cooldown.

Otherwise it MUST NO-OP.

Default controls:

- watchdog CRITICAL threshold: inherited from Wave 1 (>135 minutes scheduler-proof age or missing authoritative scheduler proof),
- recovery guard cron: `:55` UTC minute of every hour,
- recovery cooldown: 60 minutes,
- recent governed-event settle window: 20 minutes.

## Recovery action

When eligible, the guard dispatches the existing `v6-natural-data-ingestion.yml` workflow using:

- `mode=manual_recovery`,
- `reason=WAVE2_SAFE_RECOVERY_CRITICAL`,
- `confirm=RECOVER_V6`.

The guard does not edit Issue #431, does not emit `FPL_MASTER_SLOT`, does not hold V6 publisher credentials, does not write `runtime-data-v6` directly, and has no repository contents-write permission.

## Proof isolation

A Wave-2 recovery is emergency continuity evidence only. It MUST NOT:

- count as `chatgpt_scheduler_proof`,
- count as a completed scheduled slot,
- count as a genuine natural Wave-3 slot,
- repair a missing slot in the 6/6 or rolling 48/48 proof window,
- rewrite historical misses.

Wave-3 countability remains restricted to `event_name=issues`, `schedule_kind=chatgpt_scheduler`, with the full validated/frozen/promoted chain PASS.

## Failure semantics

Recovery failure does not suppress due reports. `V6 FAIL != REPORT FAIL` remains authoritative. Report delivery uses the canonical scope-specific recovery order and never falls back to V3/V4/V5.

## Acceptance

Wave 2 is accepted only after:

- scheduler recovery decision tests PASS,
- scheduler authority regression tests PASS,
- Repository Governance PASS,
- FPL V6 CI contracts PASS,
- recovery workflow is merged to `main`,
- healthy production state proves the recovery guard NO-OPs and does not trigger a false recovery.

A real recovery dispatch is not required to merge; it is production evidence only when a genuine CRITICAL condition occurs or through a bounded non-production decision simulation. The production guard must never create an outage merely to prove recovery.
