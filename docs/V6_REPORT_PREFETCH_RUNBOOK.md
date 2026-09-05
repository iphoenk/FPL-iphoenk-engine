# V6 Report Prefetch Architecture and Runbook

## Purpose and authority boundary

V6 remains a data-only platform. The report-prefetch capability acquires, normalizes, validates, caches, reconciles factual identities, calculates mechanical aggregates from submitted picks, preserves lineage/freshness/health, and publishes factual datasets.

V6 report prefetch does not recommend transfers, captaincy, vice-captaincy, formation, chips, or squad changes. It does not produce xPts, xMins, Monte Carlo results, tactical recommendations, or WAIT/PREPARE/ACT classifications. Those remain responsibilities of the downstream FPL Master Monitor / Manual FPL decision layer.

The three logical Official FPL domains are:

- `official_fpl`: canonical public universe authority.
- `official_fpl_personal`: personal entry/team factual state.
- `official_fpl_leagues`: memberships, standings, submitted rival picks, and mechanically derived league factual aggregates.

All three belong to `independence_group=official_fpl`. They are not independent corroborating sources.

## Core hourly acquisition versus report prefetch

The normal V6 source cycle remains the existing 21-source public-universe acquisition. It does not call `/my-team`, personal submitted-picks refresh, league standings, or rival-picks endpoints.

Report prefetch is a separate governed job path inside the existing V6 production workflow. It has no cron and no standalone publisher. FPL Master Monitor invokes it only when an upcoming report contract needs personal and/or mini-league context.

Default consumer timing is:

- target invocation: T-30 minutes before the logical report slot;
- maximum age at report time: 35 minutes;
- freshness authority: `REPORT_PREFETCH_FRESHNESS`, separate from core source freshness.

## Report routing contract

| Report kind | Personal | Mini league | Event live |
|---|---:|---:|---:|
| `full_master` | yes | yes | no |
| `match_mode` | yes | yes | yes |
| `deadline_review` | yes | configurable, default no | no |
| `05:30_price` | no | no | no |
| `ad_hoc` | explicit requested scope only | explicit requested scope only | explicit requested scope only |

The `05:30_price` route is a hard no-op for personal and league acquisition. It may expose the timestamp of an older personal artifact as reference metadata, but it must publish `NOT_REFRESHED_FOR_05_30_PRICE_CHECKPOINT` and `request_count=0` for the prefetch invocation.

## Consumer configuration

Canonical V6 consumer context lives in `config/v6/consumer_context.json`. It owns:

- entry ID;
- priority league identities by name and kind;
- feature switches;
- full submitted-picks policy for priority leagues;
- T-30 lead and freshness maximum age;
- bounded rival-picks concurrency;
- HTTP timeout/retry policy.

Deployment may override `FPL_TEAM_ID` and `FPL_PRIORITY_LEAGUES`. A numeric ICON+ league ID is deliberately not executable configuration. Membership is rediscovered from authoritative Official FPL entry metadata on each relevant prefetch and the configured name/kind is resolved to the current league ID.

The legacy `config/strategy/mini_leagues.json` remains a downstream/legacy configuration and is not an authority for V6. V6 does not read its old max-per-kind or rival-picks limitations and does not hydrate any V3/V4/V5 runtime state.

## Governed invocation

The existing V6 control issue remains the control plane. Report prefetch extends issue `#431` rather than creating a second orchestration framework.

Owner-authorized issue command:

```text
/v6-report-prefetch report_kind=full_master logical_slot=2026-09-05T12:30:00+07:00 reason=master_t30
```

Match Mode:

```text
/v6-report-prefetch report_kind=match_mode logical_slot=2026-09-05T21:30:00+07:00 reason=match_mode_t30
```

Ad-hoc mini-league pull:

```text
/v6-report-prefetch report_kind=ad_hoc logical_slot=2026-09-05T12:30:00+07:00 scope=mini_league reason=user_requested
```

A governed `force=true` is accepted only through this validated control path and is intended for incomplete acquisition, stale acquisition, integrity failure, manager-set change recovery, or operational recovery.

The existing workflow-dispatch path also supports `mode=report_prefetch` with an audit reason, report kind, logical slot, optional ad-hoc scope, and optional force retry.

## Personal-team acquisition

For a personal prefetch V6 acquires:

1. `bootstrap-static` for current Official element price/team/position identity and GW context;
2. entry metadata for authoritative identity and memberships;
3. public submitted picks for the current GW where available;
4. authenticated `/me/` only when authentication is configured, to verify the session belongs to the configured entry;
5. authenticated `/my-team/{entry_id}/` only after the identity check succeeds.

If authentication is unavailable or rejected, public submitted picks may remain usable. V6 does not infer bank, purchase price, selling price, FT state, hit state, or chips from public picks. Unsupported values remain null with explicit availability/auth state.

## Membership and priority-league acquisition

Membership discovery reads all current classic and H2H memberships present in the Official entry payload and excludes system leagues where their Official league type identifies them as system-owned. There is no five-league truncation.

Priority league resolution uses configured `name + kind`. Exactly one match resolves. Zero matches publish `NOT_FOUND`; duplicate names publish `AMBIGUOUS` with candidate IDs and fail closed.

For a resolved priority league, standings pagination continues until Official indicates no next page. Full submitted picks are enabled only for configured priority leagues, not for every discovered league.

## Submitted-picks cache

Priority-league submitted picks are cached at:

`season + gw + league_id + entry_id`

After the GW deadline, a complete digest-valid manager/GW record is considered immutable unless a governed force retry, corruption/integrity failure, a new/missing manager, or other explicit Official evidence requires refresh.

Cache provenance is explicit:

- `LIVE_FETCHED_CURRENT_GW`
- `IMMUTABLE_GW_CACHE_REUSED`

A later same-GW prefetch refreshes standings and, in Match Mode, event-live data while reusing valid manager picks. A manager-set change reuses unchanged cached records and fetches only new/missing entries.

## Mechanical mini-league aggregates

For managers with available submitted picks V6 publishes, per Official element:

- managers owned count and ownership percent;
- starts, captain, vice, and bench counts;
- submitted multiplier sum;
- mini-league effective ownership percent calculated mechanically from submitted multipliers;
- current live Official points when Match Mode event-live data is available.

Ownership denominator is the number of managers with available submitted picks, never silently the full standings count when coverage is partial. Artifacts expose expected count, collected count, submitted-picks available/missing counts, missing entry IDs, coverage percent, and `complete`.

V6 does not publish strategic labels such as HELP, HURT, SHIELD, DANGER, differential recommendation, or rank strategy.

## Match Mode

Match Mode acquires or reuses:

- our submitted picks;
- current priority-league standings;
- immutable same-GW all-manager submitted-picks cache;
- fresh Official event-live data.

It publishes mechanical manager multiplier-by-live-points totals where all required player points are present. Strategic interpretation, live-rank strategy, threats, shields, and captain decisions remain downstream.

## Publication tree

Canonical artifacts are:

```text
data/v6/
  personal/
    current_team.json
    submitted_picks.json
    memberships.json
  mini_leagues/<league_id>/
    standings.json
    gw_<gw>_manager_picks.json
    gw_<gw>_exposure.json
    live_state.json
  report_prefetch/
    latest.json
  health/
    report_prefetch.json
```

The existing V6 `manifest.json`, evidence, resolved registry, normalized/current public source tree, and publish-integrity contract remain owned by the existing core publisher. Report prefetch shares the same `runtime-data-v6` publication branch and dedicated GitHub App publisher. There is no second runtime branch or shadow registry.

## Lineage, freshness, and telemetry

Each prefetch artifact preserves applicable Official endpoint class, checked time, HTTP status, payload digest, live/cache origin, GW, entry ID, league ID, pagination coverage, and normalization version.

`report_prefetch/latest.json` records request identity, logical slot, requested domains, domain statuses, source/control failures, league/picks completeness, cache state, live check time, artifact digests, and telemetry.

Telemetry includes:

- request count and failures;
- manager count;
- cache hits/misses;
- execution duration;
- maximum concurrency used;
- `fresh_for_target_report`.

No giant raw HTTP log or authentication header is published.

## Authentication and secret governance

Supported deployment modes are session-cookie and bearer-token authentication. Secret values are consumed only by the report-prefetch workflow step and client. They are never copied into `runtime-data-v6`.

The V6 safe publisher rejects secret-bearing keys and configured secret values before JSON artifacts are written. Exceptions publish only sanitized class/state identifiers. Authenticated redirects are rejected and session identity is verified before `/my-team` is trusted.

## Failure semantics

Failure isolation is deliberate:

- authenticated personal failure does not invalidate public picks or unrelated league data;
- one rival-picks failure produces partial coverage with the exact missing entry ID, never fabricated 100% ownership;
- event-live failure leaves submitted picks valid and reports live state unavailable;
- standings failure never claims current rank or full coverage;
- duplicate priority league identity fails closed;
- malformed or timezone-naive logical slots are rejected;
- an incomplete prefetch is published as incomplete/partial rather than silently reported as successful.

## Operational acceptance checklist

Before declaring production green, verify from a governed runtime run:

1. entry membership discovery resolves the current configured priority league dynamically;
2. standings paginate completely;
3. all available current-GW manager picks are fetched/cached;
4. exposure artifact uses the correct denominator;
5. authenticated personal state is acquired when the credential is available;
6. no secret-bearing value appears anywhere under `data/v6`;
7. a second same-GW run shows cache hits and avoids re-downloading unchanged rival picks;
8. Match Mode refreshes event live while reusing the submitted-picks cache;
9. a governed `05:30_price` run reports zero Official prefetch requests and does not modify personal/mini-league artifacts;
10. core V6 publish integrity remains PASS after the report-prefetch artifacts are added;
11. CI and V6 architecture-independence validation remain green.

If any live Official endpoint or credential is unavailable, record the exact degraded acceptance item. Do not convert that condition into a false green status.
