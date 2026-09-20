# V6 Fresh Data Platform

> **Last runtime/documentation sync:** `2026-09-20T23:34:18+07:00`  
> **Runtime contract basis:** `config/v6/schedule_policy.json` schema v6, `config/v6/source_activation.json` schema v4, `.github/workflows/v6-natural-data-ingestion.yml`, and the active `runtime-data-v6` publication model.

## Mission and authority

V6 is the repository's factual fresh-data plane. It acquires, normalizes, validates, joins, health-checks, preserves provenance, and publishes factual/evidence artifacts. It has no transfer, captaincy, chip, optimizer, xPts, xMins, Bayesian, Monte Carlo, tactical, mini-league strategy, or recommendation authority.

Official FPL is the canonical authority for Official-FPL-native player, team, fixture, price, scoring, rule, and submitted-picks facts. External providers remain separate evidence sources. V6 never averages them into hidden consensus and never fabricates missing values.

V6 must never import, execute, hydrate, or fall back to V3/V4/V5 runtime data, caches, manifests, or engines.

## Current production control plane

The active hourly authority is **FPL Master Monitor V12** in ChatGPT Automation:

- timezone: `Asia/Jakarta`;
- physical cadence: every hour at `:30`;
- logical V6 core slot: current `HH:00`;
- current scheduler epoch: `CHATGPT_MASTER_V1`;
- control issue: GitHub issue `#431`;
- preferred transport: **issue title edit**;
- title marker: `FPL_MASTER_SLOT`;
- required reason: `chatgpt_hourly_master`;
- required audit marker: `FPL_MASTER_HOURLY`.

The normal full-core path is:

```text
FPL Master Monitor V12 (:30 Asia/Jakarta)
        |
        | edit issue #431 title for current HH:00 logical slot
        v
GitHub issues:edited event
        |
        v
.github/workflows/v6-natural-data-ingestion.yml
        |
        +--> hydrate last-good runtime-data-v6
        +--> classify governed chatgpt_scheduler occurrence
        +--> guard duplicate logical slot
        +--> acquire active V6 sources
        +--> runtime-control / identity / integrity validation
        +--> isolated V6 publisher GitHub App
        v
runtime-data-v6 atomic factual snapshot
        |
        v
Canonical V12 downstream analytics / report
```

Issue #431 is transport and execution trigger evidence, not methodology authority.

## GitHub schedules

There is **no recurring GitHub acquisition cron** for V6.

`config/v6/schedule_policy.json` explicitly sets:

- `github_natural_schedule.enabled = false`;
- `workflow_schedule_triggers_removed = true`;
- `scheduled_crons_utc = []`;
- `natural_schedule_redundancy_attempts_per_hour = 0`.

Former GitHub acquisition cron expressions are historical evidence only and must not be described as active production cadence.

The only scheduled GitHub V6 control workflow is:

- `.github/workflows/v6-scheduler-watchdog.yml`
- cron: minute `:50` UTC
- role: **monitoring only**
- it cannot acquire V6 data, publish `runtime-data-v6`, mutate issue #431 for a core slot, or advance scheduler proof.

`.github/workflows/v6-core-recovery-guard.yml` is `workflow_dispatch` only. It is non-recurring and may dispatch governed `manual_recovery` only when explicitly invoked and eligible.

## Invocation classes

### chatgpt_scheduler

The normal hourly full-core occurrence is triggered through issue #431 title edit and publishes `schedule_kind=chatgpt_scheduler`.

A valid scheduler proof requires the governed logical slot plus authoritative publication evidence. It is the current scheduler-health authority.

### report_prefetch

Report-prefetch is report-driven, not independently scheduled. It uses the existing V6 workflow and publisher but:

- does not complete a core operational slot;
- does not count as scheduler proof;
- does not substitute for hourly acquisition;
- may refresh exact report scopes such as authenticated personal, mini-league, live, price, or historical scope;
- remains fail-operational with respect to visible report delivery.

The current preferred report-prefetch transport is the issue #431 comment command `/v6-report-prefetch`.

### manual_recovery

Manual recovery is an explicit emergency path only:

- `workflow_dispatch`;
- confirmation phrase `RECOVER_V6`;
- repository-owner restricted;
- reuses the dedicated V6 publisher;
- `authoritative_runtime_snapshot=false`;
- does not complete a scheduled/core operational slot;
- cannot become scheduler-health proof.

## Production workflow boundary

`.github/workflows/v6-natural-data-ingestion.yml` owns the production execution path.

The `collect` job is read-only against the repository and:

1. authorizes the governed invocation;
2. hydrates the latest `runtime-data-v6` last-good snapshot;
3. classifies the invocation;
4. guards already-fulfilled logical slots;
5. runs V6 acquisition or exact-scope report-prefetch;
6. updates runtime-control evidence;
7. validates publish integrity;
8. packages one verified runtime tree.

The `publish` job is the only runtime writer. It uses the protected `v6-runtime-publisher` environment and a dedicated V6 GitHub App token, publishes atomically to `runtime-data-v6`, and verifies the exact published tree.

There is no generic workflow-token publication fallback.

## Effective source membership

Effective production membership is owned by:

1. `config/v6/source_registry.json` — source definitions;
2. `config/v6/source_additions.json` — additive definitions;
3. `config/v6/source_overrides.json` — repair/incubation overrides;
4. `config/v6/source_activation.json` — active/reference-only/disabled policy.

A source being defined in `source_registry.json` does not mean it is currently active.

Examples currently outside active acquisition include paid/access-restricted/unstable sources listed in `source_activation.json`.

### Weather

`open_meteo` is currently **disabled/retired from V6 production acquisition** with policy reason:

`RETIRED_CHATGPT_REPORT_TIME_WEATHER_NOT_V6_DEPENDENCY`

Therefore Open-Meteo must not be shown as an active V6 runtime dependency. Report-time weather may be obtained downstream when the Canonical report contract requires it; it is not a V6 data-plane authority.

## Identity semantics

Official FPL element ID is the canonical player key.

External records may participate in canonical joins only when the identity map provides a deterministic `EXACT` or `VERIFIED_MANUAL` link. Silent fuzzy matching is forbidden.

Transport/data health and join completeness are distinct dimensions. Secondary provider identity gaps may remain truthfully RED/partial without corrupting Official FPL canonical identity or blocking factual publication, provided no hard identity conflict/corruption exists.

The current runtime truth for identity must be read from:

- `data/v6/evidence/player_identity_map.json`;
- `data/v6/evidence/player_identity_coverage.json` when present;
- `data/v6/health/source_health.json`;
- `data/v6/health/publish_integrity.json`.

Do not hard-code mutable player-universe or provider-coverage counts in this document.

## Runtime publication tree

The governed runtime branch is `runtime-data-v6`.

Representative artifacts include:

```text
data/v6/
├── manifest.json
├── current/
│   ├── official_fpl.json
│   └── official_price_predictor.json
├── personal/
│   ├── current_team.json
│   ├── memberships.json
│   └── submitted_picks.json
├── mini_leagues/
├── normalized/
│   ├── canonical_players.json
│   ├── canonical_teams.json
│   └── canonical_fixtures.json
├── evidence/
│   ├── lineage.json
│   ├── latest_index.json
│   ├── resolved_registry.json
│   └── player_identity_map.json
└── health/
    ├── source_health.json
    ├── runtime_control.json
    ├── operational_slots.json
    ├── report_prefetch.json
    └── publish_integrity.json
```

The publication tree is factual/evidence output only. V6 must not publish transfer recommendations, xPts/xMins decisions, tactical scores, optimizer decisions, or mini-league strategic conclusions.

## Freshness and consumer trust

A stored GREEN label is not sufficient by itself. Consumers must evaluate current runtime evidence, including:

- current age/freshness;
- governed trigger provenance;
- `authoritative_runtime_snapshot`;
- publish-integrity status;
- exact source/registry consistency;
- canonical identity health;
- relevant source failures;
- logical-slot/scheduler evidence.

Mode-specific report freshness may be stricter than the generic V6 freshness target.

A degraded secondary source must degrade only the affected claims. It must not erase healthy Official FPL facts or force a due report to disappear.

## Runtime branch governance

`runtime-data-v6` is a publication branch, not a development branch.

Normal publication is performed only by the governed dedicated V6 publisher integration/app. Manual human writes or generic workflow-token writes are not part of the accepted production path.

## V6 and V12 boundary

```text
Official / factual providers
        |
        v
V6 factual acquisition + validation + publication
        |
        v
runtime-data-v6
        |
        v
Canonical V12
  - Gate0
  - Bayesian / event models
  - P(start) / xMins
  - tactical / role
  - fixture adjustment
  - price interpretation
  - full-universe search
  - package / XI / bench / CVC
  - Monte Carlo when supportable
  - mini-league overlay
  - WAIT / PREPARE / ACT
        |
        v
Visible report
```

V6 tells V12 what is factually supportable. V12 owns interpretation and decision logic.

## Documentation synchronization

This file is a runtime projection, not a runtime authority.

Whenever scheduler ownership, trigger transport, V6 workflow behavior, source activation, runtime publication, recovery semantics, authority boundaries, or production governance changes, this document and any affected README/architecture document must be updated in the **same pull request**.

Every PR must carry the timestamp and documentation-sync metadata defined in `docs/REPOSITORY_DOCUMENTATION_SYNC_POLICY.md`. Repository governance enforces the contract.
