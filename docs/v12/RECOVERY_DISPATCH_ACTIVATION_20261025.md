# Recovery dispatch: activation, rollback and expected evidence (NOT ACTIVE)

Status: prepared. `FPL_RECOVERY_DISPATCH` must stay unset until the owner authorizes activation in writing.

## Preconditions (all must hold before the owner sets the variable)
1. The audit job shows `::notice title=FPL_RECOVERY_DISPATCH` with the effective value (unset or not ENABLED today).
2. Latest main CI is green and the missed-slot audit artifact is non-UNKNOWN for the newest due slot.
3. The owner accepts: at most one future-only occurrence per clock run, ≤180 minutes overdue, never retried when any orchestrator run for that exact occurrence exists, announced on #431 as RECOVERY (natural_proof=false).

## Safety properties (tested in tests/test_recovery_dispatch.py)
- Exact-match gate: only the value `ENABLED` activates; any other value is disabled and makes no call.
- Evidence comment on #431 precedes the dispatch; comment failure or timeout prevents dispatch.
- The run list is re-read immediately before the dispatch; a run that appeared meanwhile blocks it.
- A dispatch timeout reports DISPATCH_STATE_UNKNOWN and is never retried in the same run; the next run sees the run by title.
- Job permissions: contents read, actions write, issues write; concurrency group `fpl-recovery-dispatch`; tick job untouched.
- Recovery output carries `origin=RECOVERY` in the verified pointer and can never count as natural acceptance.

## Activation (owner only)
Set repository variable `FPL_RECOVERY_DISPATCH` to `ENABLED` (Settings, Secrets and variables, Actions, Variables).

## Rollback (owner, immediate)
Delete the variable or set any other value. The next clock run skips the job. An already dispatched orchestrator run is left to finish; cancel it only by explicit owner decision.

## Expected evidence after activation
- Job summary of `recovery-dispatch` with action DISPATCHED_RECOVERY or a SKIPPED_* reason.
- One `FPL_RECOVERY_DISPATCH | label=RECOVERY` comment on #431 before one orchestrator run titled `FPL EXTERNAL_CLOCK_FALLBACK occurrence <MODE> <slot>`.
- On success the `FPL_MASTER_RECEIPT`, then pointer event ADVANCED with `origin=RECOVERY`.
