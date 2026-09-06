# V6 Report Prefetch Architecture and Runbook

## Purpose and authority boundary

V6 report prefetch is a governed **data-acquisition, normalization, identity, cache, lineage, health, and publication** path. V6 remains data-only.

V6 does not own or publish transfer, captain, vice-captain, formation, chip, squad-change, optimizer, xPts, xMins, tactical, Bayesian, Monte Carlo, ownership/EO, rival-model, rank-strategy, or WAIT/PREPARE/ACT analytical authority. Those responsibilities remain downstream in Manual FPL / FPL Master Monitor.

The Official FPL logical domains are:

- `official_fpl`: canonical public universe facts;
- `official_fpl_personal`: personal entry/team facts;
- `official_fpl_leagues`: memberships, standings, and submitted manager picks.

All belong to `independence_group=official_fpl`. They are not independent corroborating sources.

## Core hourly acquisition versus report prefetch

The normal V6 source cycle remains the public-universe acquisition path. It does not continuously poll `/my-team`, personal submitted picks, mini-league standings, or rival picks.

Report prefetch is a separate governed job path inside the existing V6 production workflow. It has no independent cron and no standalone publisher. FPL Master Monitor invokes it only when an upcoming report needs personal or mini-league factual context.

Default consumer timing is:

- target invocation: T-30 minutes before the logical report slot;
- maximum age at report time: 35 minutes;
- freshness authority: `REPORT_PREFETCH_FRESHNESS`, separate from core-source freshness.

## Report routing contract

| Report kind | Personal | Mini league | Event live |
|---|---:|---:|---:|
| `full_master` | yes | yes | no |
| `match_mode` | yes | yes | yes |
| `deadline_review` | yes | configurable, default no | no |
| `05:30_price` | no | no | no |
| `ad_hoc` | explicit requested scope only | explicit requested scope only | explicit requested scope only |

The `05:30_price` route is a hard no-op for personal and league acquisition. It may expose an older artifact timestamp as reference metadata, but it must publish `NOT_REFRESHED_FOR_05_30_PRICE_CHECKPOINT` and `request_count=0` for the prefetch invocation.

## Consumer configuration

Canonical V6 consumer context lives in `config/v6/consumer_context.json`. It owns:

- entry ID;
- priority league identity by name and kind;
- feature switches;
- full submitted-picks policy for configured priority leagues;
- T-30 lead and maximum freshness age;
- bounded manager-picks concurrency;
- HTTP timeout/retry policy.

Deployment may override `FPL_TEAM_ID` and `FPL_PRIORITY_LEAGUES`. Numeric league IDs are not executable authority. Membership is rediscovered from Official FPL entry metadata and configured name/kind is resolved dynamically.

The legacy `config/strategy/mini_leagues.json` is not V6 authority. V6 does not hydrate V3/V4/V5 runtime state.

## Governed invocation

Report prefetch reuses control issue `#431` rather than creating a second orchestration framework.

Owner-authorized examples:

```text
/v6-report-prefetch report_kind=full_master logical_slot=2026-09-05T12:30:00+07:00 reason=master_t30
```

```text
/v6-report-prefetch report_kind=match_mode logical_slot=2026-09-05T21:30:00+07:00 reason=match_mode_t30
```

```text
/v6-report-prefetch report_kind=ad_hoc logical_slot=2026-09-05T12:30:00+07:00 scope=mini_league reason=user_requested
```

A governed `force=true` is accepted only through the validated control path for incomplete acquisition, stale acquisition, integrity failure, manager-set changes, or operational recovery.

## Personal-team acquisition

For a personal prefetch V6 may acquire:

1. `bootstrap-static` for current Official element/team/position/GW facts;
2. entry metadata for identity and memberships;
3. public submitted picks where available;
4. authenticated `/me/` only when authentication is configured, to verify session identity;
5. authenticated `/my-team/{entry_id}/` only after identity verification succeeds.

If authentication is unavailable or rejected, public submitted picks may remain usable. V6 does not infer bank, purchase price, selling price, FT state, hit state, or chip state from public picks. Unsupported values remain null with explicit availability/auth state.

## Membership and priority-league acquisition

Membership discovery reads all current classic and H2H memberships exposed by Official FPL and excludes system leagues where the Official league type identifies them as system-owned. There is no five-league truncation.

Priority league resolution uses configured `name + kind`. Exactly one match resolves. Zero matches publish `NOT_FOUND`; duplicate matches publish `AMBIGUOUS` and fail closed.

For a resolved priority league, standings paginate until Official indicates no next page. Full submitted picks are enabled only for configured priority leagues.

## Submitted-picks cache

Priority-league submitted picks are keyed by:

```text
season + gw + league_id + entry_id
```

After the GW deadline, a complete digest-valid manager/GW record is reusable unless a governed force retry, corruption/integrity failure, new/missing manager, or other explicit Official evidence requires refresh.

Cache provenance is explicit, including live fetch versus immutable same-GW reuse. A manager-set change reuses unchanged valid records and fetches only new/missing entries.

## Mini-league factual boundary

V6 publishes the **inputs** required for downstream mini-league analysis, not the analysis itself.

Allowed canonical facts include:

- current Official standings rows and ranks exactly as exposed by Official FPL;
- current manager set and coverage metadata;
- each manager's submitted 15-player picks;
- squad position and bench order;
- submitted multiplier;
- designated captain and vice-captain flags;
- active chip when Official FPL exposes it;
- raw Official event-live element stats in Match Mode;
- lineage, cache provenance, completeness, and health.

V6 does **not** calculate or publish canonical:

- ownership percentages or ownership aggregates;
- effective ownership (EO);
- captain/vice/start/bench population aggregates;
- player exposure tables;
- manager multiplier-by-live-points totals;
- shield/danger/differential labels;
- rank impact, reconstructed rank, or rank probability;
- transitions, overlap, concentration, HHI, or rival-behavior analytics.

All such derivation is downstream-only.

## Match Mode

Match Mode acquires or reuses factual inputs:

- our submitted picks;
- current priority-league standings;
- same-GW all-manager submitted-picks cache;
- fresh Official event-live element data.

V6 does not combine submitted multipliers with live points into manager analytical totals. Strategic interpretation and all rank-impact logic remain downstream.

## Publication tree

Canonical report-prefetch artifacts are:

```text
data/v6/
  personal/
    current_team.json
    submitted_picks.json
    memberships.json
  mini_leagues/<league_id>/
    standings.json
    gw_<gw>_manager_picks.json
    live_state.json
  report_prefetch/
    latest.json
  health/
    report_prefetch.json
```

A legacy `gw_<gw>_exposure.json` path may temporarily exist only as a backward-compatibility tombstone. When present it must be explicitly `canonical=false`, `deprecated=true`, contain no player analytics, and carry `authority=NONE`. Consumers must not treat it as V6 analytical data.

The existing V6 `manifest.json`, evidence, resolved registry, normalized/current public-source tree, and publish-integrity contract remain owned by the same core publisher. Report prefetch shares `runtime-data-v6`; there is no second runtime branch, second publisher, or shadow registry.

## Historical backfill

Historical mini-league backfill reuses this control plane with `report_kind=historical_backfill`. Its factual-only contract is documented in `docs/V6_HISTORICAL_MINI_LEAGUE_BACKFILL.md`.

Canonical historical inputs are submitted manager picks, Official event points, Official entry-history facts, current-cohort membership facts, reconciliation checks, and factual per-manager history. Historical ownership/EO, overlap, transitions, concentration, reconstructed mini-league rank, and behavioral analytics are not V6 outputs.

## Lineage, freshness, and telemetry

Each prefetch artifact preserves applicable Official endpoint class, checked time, HTTP status, payload digest, live/cache origin, GW, entry ID, league ID, pagination coverage, and normalization version.

`report_prefetch/latest.json` records request identity, logical slot, requested domains, domain statuses, source/control failures, completeness, cache state, live check time, artifact digests, and telemetry.

Telemetry includes request count/failures, manager count, cache hits/misses, duration, bounded concurrency, and target-report freshness. Telemetry describes acquisition behavior, not FPL decision quality.

## Authentication and secret governance

Supported deployment modes are session-cookie and bearer-token authentication. Secret values are consumed only by the report-prefetch workflow/client and are never copied into `runtime-data-v6`.

The V6 safe publisher rejects secret-bearing keys and configured secret values before artifacts are written. Authenticated redirects are rejected and session identity is verified before `/my-team` is trusted.

## Failure semantics

Failure isolation is explicit:

- authenticated personal failure does not invalidate unrelated public or league facts;
- one manager-picks failure produces partial coverage with the exact missing entry ID;
- event-live failure leaves submitted picks valid and marks live data unavailable;
- standings failure never claims current rank or full coverage;
- duplicate priority-league identity fails closed;
- malformed or timezone-naive logical slots are rejected;
- incomplete prefetch remains incomplete/partial rather than being converted to false GREEN.

## Operational acceptance checklist

Before declaring the report-prefetch path production-green, verify:

1. priority-league membership resolves dynamically from Official FPL;
2. standings paginate completely;
3. all available manager submitted picks are fetched or validly reused;
4. canonical mini-league artifacts contain atomic facts only and no ownership/EO or rival analytics;
5. any legacy exposure file is noncanonical, deprecated, empty of analytical player rows, and has `authority=NONE`;
6. authenticated personal state is acquired when credentials are available;
7. no secret-bearing value appears under `data/v6`;
8. a second same-GW run shows valid cache reuse without unnecessary manager-picks downloads;
9. Match Mode refreshes raw event-live facts while reusing immutable submitted picks where eligible;
10. a governed `05:30_price` run makes zero Official prefetch requests and does not modify personal/mini-league artifacts;
11. V6 publish integrity, zero-authority validation, and architecture-independence validation pass;
12. CI remains green.

If an Official endpoint or credential is unavailable, record the exact degraded acceptance item. Do not convert the condition into false GREEN.
