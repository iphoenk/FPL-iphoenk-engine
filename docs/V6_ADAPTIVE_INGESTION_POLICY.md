# V6 Adaptive Ingestion Policy

V6 remains a data-only acquisition platform. This policy extends the existing 27-source registry without changing source authority, prediction logic, optimizer logic, or the source denominator.

## Goals

- Keep source behavior config-driven rather than provider-hardcoded.
- Avoid polling every source at the same frequency when upstream data changes more slowly or provider budgets are tighter.
- Preserve fail-isolated concurrent acquisition for every source that is due.
- Reuse existing SHA/content-change evidence instead of introducing a second deduplication engine.
- Make verification, quota, and intentional scheduled skips explicit in runtime health.

## Registry fields

Optional per-source fields:

- `acquisition_kind`: `derived`, `rest_json`, `rest_csv`, `html_scrape`, `rss`, or `generic_http`.
- `poll_interval_minutes`: normal minimum interval between provider polls.
- `poll_interval_minutes_deadline_window`: tighter interval used when an Official FPL deadline is within the configured window.
- `daily_request_budget`: maximum provider request attempts per WIB calendar day.
- `content_hash_dedup`: declares that unchanged SHA content is semantically unchanged and should not create duplicate evidence semantics.
- `verification_required`: source cannot enter scheduled polling until qualification is complete.
- `verification_status`: `PENDING`, `VERIFIED`, or `FAILED`.

Sources without `poll_interval_minutes` retain legacy behavior and remain eligible every V6 workflow cycle.

## Deadline window

The collector derives a deadline window from the latest persisted Official FPL bootstrap data. Default horizon is 48 hours. A source may define `poll_interval_minutes_deadline_window` to increase cadence only inside that window.

## Budget semantics

Daily request counters use `Asia/Jakarta` calendar days. The persisted source snapshot carries the budget counter across ephemeral runners through the existing `runtime-data-v6` hydration path. Actual provider attempts, including retries, are counted from `attempt_count`; missing-credential checks do not consume provider budget.

If the next configured poll would exceed the remaining budget, the source is not called and is reported explicitly as `BUDGET_EXHAUSTED` rather than as a transport failure.

## Verification gate

A source with `verification_required: true` and a status other than `VERIFIED` is intentionally not polled. It is reported as `VERIFICATION_REQUIRED`/AMBER. This is not an authentication bypass and does not fabricate availability.

## Current targeted policies

The initial policy metadata is intentionally narrow and based on known source characteristics instead of guessing a cadence for all 27 providers:

- Official FPL: 60 minutes.
- Understat: 60 minutes, `html_scrape`, SHA/content-hash dedup semantics.
- StatsBomb Open Data catalogue: 1,440 minutes, SHA/content-hash dedup semantics.
- API-Football: 1,440 minutes normally, 360 minutes inside the deadline window, daily request budget 100, qualification gate enabled.
- football-data.org: 60 minutes.

All other sources keep existing every-cycle eligibility until their cadence is explicitly qualified.

## Health semantics

A scheduled `NOT_DUE` skip can preserve the latest healthy source state because no provider call was required by contract. Runtime output exposes `polling.reason`, `polling.last_polled_at`, effective interval, deadline-window state, and budget metadata so a scheduled cache is distinguishable from an acquisition failure.

`VERIFICATION_REQUIRED` and `BUDGET_EXHAUSTED` are AMBER states. Critical sources with no usable current or cached data remain RED.
