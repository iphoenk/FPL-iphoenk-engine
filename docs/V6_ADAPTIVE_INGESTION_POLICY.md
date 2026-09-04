# V6 Adaptive Ingestion Policy

V6 remains a data-only acquisition platform. The base source catalogue is retained for provenance and reversibility, while the active acquisition set is explicitly pruned by `config/v6/source_activation.json`.

## Current active-source contract

The base catalogue contains 27 source definitions. The active scheduled acquisition set contains 20 sources.

Seven sources are disabled from active V6 polling:

- `fbref` — duplicate advanced-stat path plus access restriction.
- `sofascore` — duplicate path using an unofficial endpoint currently returning 403.
- `sportmonks` — paid provider; dropped by owner decision.
- `api_football` — paid access required for the current season; dropped by owner decision.
- `transfermarkt` — automated-access restriction; dropped from scheduled acquisition.
- `whoscored` — duplicate Opta-family path plus access restriction.
- `football_data_org` — dropped by owner decision after pricing/access review.

The source definitions remain in the base catalogue only as historical/audit metadata. They do not enter the active registry, do not consume workers, do not appear in active health denominators, and do not receive provider calls.

FFHub remains active only on a free/public-partial basis. V6 must not depend on a Pro upgrade. FFFix remains free/public only. ClubElo remains active and is designated for repair rather than removal.

## Goals

- Keep source behavior config-driven rather than provider-hardcoded.
- Avoid polling every active source at the same frequency when upstream data changes more slowly.
- Remove paid, restricted, or redundant providers from the active denominator instead of reporting permanent AMBER noise.
- Preserve fail-isolated concurrent acquisition for every active source that is due.
- Reuse existing SHA/content-change evidence instead of introducing a second deduplication engine.
- Make intentional scheduled skips explicit in runtime health.

## Registry fields

Optional per-source fields:

- `acquisition_kind`: `derived`, `rest_json`, `rest_csv`, `html_scrape`, `rss`, or `generic_http`.
- `poll_interval_minutes`: normal minimum interval between provider polls.
- `poll_interval_minutes_deadline_window`: tighter interval used when an Official FPL deadline is within the configured window.
- `daily_request_budget`: maximum provider request attempts per WIB calendar day.
- `content_hash_dedup`: declares that unchanged SHA content is semantically unchanged and should not create duplicate evidence semantics.
- `verification_required`: source cannot enter scheduled polling until qualification is complete.
- `verification_status`: `PENDING`, `VERIFIED`, or `FAILED`.

Sources without `poll_interval_minutes` retain every-cycle eligibility. A configured interval equal to or shorter than the scheduler interval is also treated as every-cycle eligibility; this prevents runner timing jitter from accidentally turning a nominal hourly source into an approximately two-hour source.

## Activation policy

`config/v6/source_activation.json` is the single activation layer. `source_registry.json` remains the source-definition catalogue, while the activation layer determines which definitions are allowed into the runtime registry.

The loader validates both contracts:

- base definitions must still match the 27-source catalogue;
- active definitions must match the 20-source acquisition contract;
- disabled IDs must match the approved drop set;
- unknown activation IDs fail validation.

Dropped-source files from a previously hydrated `runtime-data-v6` snapshot are pruned before publication so stale provider artifacts cannot masquerade as active sources.

## Deadline window

The collector derives a deadline window from the latest persisted Official FPL bootstrap data. Default horizon is 48 hours. A source may define `poll_interval_minutes_deadline_window` to increase cadence only inside that window.

## Budget semantics

Daily request counters use `Asia/Jakarta` calendar days. The persisted source snapshot carries the budget counter across ephemeral runners through the existing `runtime-data-v6` hydration path. Actual provider attempts, including retries, are counted from `attempt_count`; missing-credential checks do not consume provider budget.

Before starting a budgeted poll, V6 reserves enough remaining budget for the worst-case configured retry count across all requests in that source. This prevents a request that starts within budget from crossing a provider's daily limit because of retries. After the poll, only actual provider attempts are charged to the persisted counter.

If the next configured poll would exceed the remaining budget, the source is not called and is reported explicitly as `BUDGET_EXHAUSTED` rather than as a transport failure.

## Current targeted polling policies

- Official FPL: 60 minutes.
- Understat: 60 minutes, `html_scrape`, SHA/content-hash dedup semantics.
- StatsBomb Open Data catalogue: 1,440 minutes, SHA/content-hash dedup semantics.

All other active sources keep existing every-cycle eligibility until their cadence is explicitly qualified.

## Health semantics

A scheduled `NOT_DUE` skip can preserve the latest healthy source state because no provider call was required by contract. Runtime output exposes `polling.reason`, `polling.last_polled_at`, effective interval, deadline-window state, and budget metadata so a scheduled cache is distinguishable from an acquisition failure.

`BUDGET_EXHAUSTED` is AMBER. Critical active sources with no usable current or cached data remain RED. Disabled sources are not health failures because they are not part of the active V6 runtime contract.
