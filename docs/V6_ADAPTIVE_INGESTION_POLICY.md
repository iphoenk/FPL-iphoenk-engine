# V6 Adaptive Ingestion Policy

V6 remains a data-only acquisition platform. The configured source catalogue is retained for provenance and reversibility, while the active acquisition set is explicitly pruned by `config/v6/source_activation.json`.

## Current active-source contract

Current source counts and source membership are generated from the resolved V6 registry and published in `docs/V6_SOURCE_CONTRACT_GENERATED.md`. That generated contract is CI-checked and is the documentation authority for configured, active, disabled, reference-only, required, and temporary-override counts.

Do not hand-maintain source totals in this policy document. Stable provider contracts belong in the canonical registry/additions layer, temporary repairs belong in `source_overrides.json`, and activation state belongs only in `source_activation.json`.

Reference-only sources remain available as provenance or targeted retrieval references but do not enter scheduled acquisition, consume scheduled workers, or enter active health denominators. Disabled sources likewise remain configuration/audit facts without being treated as runtime failures.

## Goals

- Keep source behavior config-driven rather than provider-hardcoded.
- Avoid polling every active source at the same frequency when upstream data changes more slowly.
- Remove paid, restricted, or redundant providers from the active denominator instead of reporting permanent AMBER noise.
- Preserve fail-isolated concurrent acquisition for every active source that is due.
- Reuse existing SHA/content-change evidence instead of introducing a second deduplication engine.
- Make intentional scheduled skips explicit in runtime health.
- Keep source-count documentation generated from the same resolved registry used by production.

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

`config/v6/source_activation.json` is the single activation layer. `source_registry.json` plus governed additive source definitions form the configured source catalogue, while the activation layer determines which definitions are allowed into the runtime registry.

The loader validates the contracts:

- configured source IDs must remain unique and deterministic;
- disabled and reference-only IDs must resolve to configured sources;
- required platform sources cannot be pruned;
- active definitions must exactly match the resolved activation contract;
- unknown activation IDs fail validation;
- temporary source overrides must remain lifecycle-governed and must not target inactive sources.

Dropped-source files from a previously hydrated `runtime-data-v6` snapshot are pruned before publication so stale provider artifacts cannot masquerade as active sources.

## Season contract

The football season is owned by `config/v6/season_contract.json`. Provider-specific season representations are derived from that contract rather than being independently interpreted at runtime. This keeps canonical season identity and provider formatting under one V6-owned contract.

## Deadline window

The collector derives a deadline window from the latest persisted Official FPL bootstrap data. Default horizon is 48 hours. A source may define `poll_interval_minutes_deadline_window` to increase cadence only inside that window.

## Budget semantics

Daily request counters use `Asia/Jakarta` calendar days. The persisted source snapshot carries the budget counter across ephemeral runners through the existing `runtime-data-v6` hydration path. Actual provider attempts, including retries, are counted from `attempt_count`; missing-credential checks do not consume provider budget.

Before starting a budgeted poll, V6 reserves enough remaining budget for the worst-case configured retry count across all requests in that source. This prevents a request that starts within budget from crossing a provider's daily limit because of retries. After the poll, only actual provider attempts are charged to the persisted counter.

If the next configured poll would exceed the remaining budget, the source is not called and is reported explicitly as `BUDGET_EXHAUSTED` rather than as a transport failure.

## Current targeted polling policies

Provider-specific polling intervals remain registry-owned and are visible in the generated resolved registry/runtime evidence. This policy document intentionally does not duplicate the current per-provider values.

## Health semantics

A scheduled `NOT_DUE` skip can preserve the latest healthy source state because no provider call was required by contract. Runtime output exposes `polling.reason`, `polling.last_polled_at`, effective interval, deadline-window state, and budget metadata so a scheduled cache is distinguishable from an acquisition failure.

`BUDGET_EXHAUSTED` is AMBER. Critical active sources with no usable current or cached data remain RED. Disabled or reference-only sources are not health failures because they are not part of the active scheduled V6 runtime contract.
