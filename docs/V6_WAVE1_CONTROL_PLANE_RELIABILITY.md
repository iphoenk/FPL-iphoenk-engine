# V6 Wave 1 — Control-Plane Reliability

## Purpose

Wave 1 hardens scheduler continuity without adding a second acquisition authority.

The production authority remains:

`ChatGPT FPL Master Monitor -> issue #431 title FPL_MASTER_SLOT -> V6 acquisition -> freeze -> integrity -> atomic publish`

The issue-title transport is frozen for core acquisition. `/v6-master-acquire` remains retired. GitHub native acquisition cron remains disabled. V3/V4/V5 remain forbidden as operational input or fallback.

## Monitoring-only watchdog

`.github/workflows/v6-scheduler-watchdog.yml` is an independent dead-man detector, not an acquisition scheduler.

It runs at minute 50 each hour and reads the latest authoritative `runtime-data-v6` scheduler proof. Thresholds:

- `<= 90 minutes`: `HEALTHY`
- `> 90 minutes`: `WARNING`
- `> 135 minutes`: `CRITICAL`

The watchdog has only `contents: read`, `actions: read`, and `issues: write`. It has no runtime publisher environment/credential, no contents write permission, no ingestion-dispatch path, and no authority to advance scheduler proof.

When stale, it opens or updates one deduplicated incident issue. When proof becomes fresh again, it closes that monitoring incident. It never repairs continuity by publishing data itself.

## Incident diagnosis

The watchdog records one diagnosis code to make the next incident attributable instead of merely visible:

- `EXTERNAL_CONTROL_EVENT_MISSING`: current control title did not advance beyond the last authoritative scheduler proof.
- `GITHUB_EVENT_NOT_STARTED`: the control title advanced but a matching acquisition run did not start.
- `ACQUISITION_OR_PUBLISH_FAILED`: a matching acquisition run completed unsuccessfully.
- `PUBLICATION_PROOF_NOT_ADVANCED`: acquisition evidence exists but authoritative scheduler proof did not advance.
- `CONTROL_PATH_UNRESOLVED`: available evidence is insufficient for a narrower classification.

These codes do not assert that a ChatGPT task was paused. Historical task-side root cause must be proven from task/control evidence; it must not be inferred solely from a missing GitHub acquisition.

## CI blind-spot closure

`.github/workflows/repository-naming-policy.yml` executes `tests/test_test_naming_policy.py` and the direct repository naming validator on every pull request and main push. This makes repository naming policy independent of V3/V6 path filters.

## Acceptance

Wave 1 is accepted only when all of the following are true:

1. watchdog healthy/warning/critical threshold tests pass;
2. report-prefetch/manual recovery cannot count as watchdog core proof;
3. watchdog contract proves zero acquisition/publish authority;
4. GitHub acquisition cron remains disabled and ChatGPT remains the sole hourly acquisition authority;
5. repository naming-policy CI is mandatory independently of V6 path selection;
6. V6 architecture independence and authority-contract checks remain PASS;
7. full V6 regression and repository governance remain GREEN;
8. existing immutable natural Wave-3 evidence is preserved.
