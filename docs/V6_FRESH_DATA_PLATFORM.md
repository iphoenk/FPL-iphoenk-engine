# V6 Fresh Data Platform

> **Documentation sync:** 2026-09-20 23:34 WIB (Asia/Jakarta)  
> **Runtime baseline:** production `main` at `ff89271d45353105e001b2f1f3328229d6323c45` and current V6 scheduler policy.  
> **Maintenance rule:** every runtime/governance change that affects this document MUST update the affected description in the same bounded change and refresh this timestamp. Runtime/config/code remains authoritative if prose ever drifts.

## Mission and authority

V6 is the repository's dedicated fresh-data acquisition, validation, provenance, identity, health, and evidence-publication layer. It is data-only. V6 has no transfer, captaincy, chip, optimizer, xPts, xMins, Monte Carlo, tactical, recommendation, or decision authority.

Official FPL is the factual and canonical authority for player, team, fixture, and current FPL state. External providers remain separate evidence sources. V6 never averages providers into a hidden consensus and never fabricates missing values.

Consumers such as reporting and the Master Monitor may read a published V6 snapshot. **FPL Master Monitor V12 is the only recurring FPL acquisition/report scheduler authority.** Its hourly ChatGPT occurrence uses the governed Issue #431 control path: an `issues:edited` event with the `FPL_MASTER_SLOT` title marker is classified as `chatgpt_scheduler` and may complete one logical hourly core slot. Report-driven personal/mini-league/live refresh remains a separate `report_prefetch` path and does not complete a core operational slot. Other consumers must not trigger V6 core refresh. All consumers must evaluate snapshot freshness and integrity at read time. A stale, missing, invalid, or broken V6 snapshot may permit only the documented minimum-scope direct external-source fallback by the consumer.

V6 never reads V3/V4/V5 runtime branches, data trees, caches, manifests, or engine artifacts. Those engines are downstream consumers only. Any permitted consumer fallback is external-source retrieval owned by that consumer; it is never a fallback from V6 into another engine's runtime data.

## Canonical effective architecture

The architecture below reflects the effective V6 data plane. It intentionally separates sources that participate in scheduled acquisition from sources that are reference-only, disabled, or excluded by policy. Source membership itself remains registry-owned by `config/v6/source_activation.json` and the published resolved registry; this diagram is a human-readable projection, not a second source of truth.

```text
                         OFFICIAL / PRIMARY FACTS

                              Official FPL
                                  │
                     factual + canonical authority
                                  │
                       deterministic identity
                                  │
                  Official FPL canonical IDs
                                  │
        ┌─────────────────────────┼──────────────────────────┐
        │                         │                          │
   PERFORMANCE               AVAILABILITY               ENVIRONMENT
   Understat                 RotoWire                    Open-Meteo
   FotMob                    public team-news           venue geography
   Opta / The Analyst        evidence                   raw provider weather
   StatMuse
   StatsBomb Open Data*
        │                         │                          │
        └─────────────────────────┼──────────────────────────┘
                                  │
                   OTHER ACTIVE FACT / REFERENCE LANES
        PremierLeague.com stats · Ben Crellin · Wikidata
            TheSportsDB V1 pilot · Vaastav / Official-derived data
                                  │
                                  ▼
                         SOURCE-NATIVE OUTPUT
             FACT · NORMALIZED_FACT · IDENTITY_CROSSWALK
                      UPSTREAM_MODEL_SIGNAL
                                  │
                  upstream only, never V6-authored
                                  │
                                  ▼
                   acquire → normalize → reconcile
                   → validate → cache/history → lineage
                            → health → publish
                                  │
                                  ▼
                              FPL MASTER
                    interpretation / intelligence
          Bayesian · xMins/xPts · Monte Carlo · tactical · DSS
```

`StatsBomb Open Data*` means the public historical/open-data surface only. It does not mean StatsBomb LIVE or another licensed current-EPL feed. `Opta / The Analyst` means the currently configured public evidence surface; it does not grant access to a licensed Opta API.

The data boundary is enforced in code: V6 may publish atomic facts, normalized facts, deterministic identity crosswalks, control telemetry, and provider-authored upstream model signals. V6 must not author prediction, optimization, tactical, transfer, captaincy, chip, formation, xPts, xMins, Bayesian, Monte Carlo, mini-league analytics, or rank-probability output.

## Sidelined and excluded sources

Sources that are not part of the active scheduled data plane must stay visibly outside the architecture above rather than being drawn as if they are production dependencies.

### Reference-only

These sources may remain available for targeted/manual evidence or future revalidation, but they are excluded from scheduled mirroring by `source_activation.json`:

- `reep_register` — public no-auth release pointer returned HTTP 404 during production acceptance; re-enable only after a stable public-download contract is revalidated;
- `fffix` — machine endpoints redirect to login;
- `ffhub` — prediction surface is auth-gated;
- `clubelo` — public reference retained but runtime transport was not stable enough for active acquisition;
- `bbc_team_news` — targeted editorial deadline reference;
- `premier_injuries` — public reference, no scheduled dataset mirroring;
- `fpl_form` — personal-use/reference constraints;
- `fpl_review_free` — free model reference without a stable machine-ingestion contract.

### Disabled

These definitions remain out of the active runtime because they are paid, access-restricted, duplicate, unstable, or deliberately dropped. The authoritative list and reasons live in `config/v6/source_activation.json`. Current examples include `sportmonks`, `api_football`, `football_data_org`, `fbref`, `sofascore`, `transfermarkt`, `whoscored`, and temporarily disabled `football_data_uk`.

### Explicitly outside the active architecture

- **Sportradar** is not an active V6 source. Paid/licensed access is outside the current zero-cost/no-login source policy.
- **Met Office Weather DataHub** is not an active V6 source because registration/account/API-key access is outside the current no-account/no-private-key policy.
- **StatsBomb LIVE / licensed feeds** are not represented by `statsbomb`; only StatsBomb Open Data is configured.
- **Licensed Opta APIs** are not represented by `opta_the_analyst`; only the configured public evidence surface is used.
- **FA/licensed official-facts lanes** must not be shown as active unless a concrete, permitted source is actually registered and production-accepted.

New additive sources must default to zero cost, no account creation, no login, and no private API key/token. A documented shared public access segment may be admitted only as a non-critical pilot when it is not a user credential or secret. If a provider later introduces an auth/paywall requirement, the source must leave active acquisition rather than silently bypassing access policy.

## Production cadence and trigger authority

The current production model has **one recurring FPL scheduler authority**: ChatGPT **FPL Master Monitor V12**, scheduled hourly at `:30` Asia/Jakarta. For each natural occurrence, the Canonical V12 core gate binds to the corresponding `HH:00` logical slot. If the slot is not already authoritatively fulfilled and no governed in-progress run can be bound, the scheduler performs at most one Issue #431 title mutation using the `FPL_MASTER_SLOT` control contract.

That Issue #431 `issues:edited` event is the normal core acquisition trigger. The ingestion workflow classifies it as `chatgpt_scheduler`, runs V6 acquisition/validation, and may publish an authoritative `runtime-data-v6` snapshot through the dedicated V6 publisher app. Duplicate full-core attempts for the same logical slot are forbidden.

GitHub natural acquisition cron is **disabled**. Historical `:13/:28/:43/:58` cron expressions are retained only as migration evidence in scheduler policy; they are not runtime triggers. The older `:23/:53` natural-acquisition description is retired and MUST NOT be used as current architecture.

The only scheduled V6 GitHub control workflow is `v6-scheduler-watchdog.yml` at minute `:50`. It is **monitoring-only**: it may classify continuity and open/update/close an incident, but it cannot trigger acquisition, publish `runtime-data-v6`, mutate Issue #431, or advance scheduler proof.

`v6-core-recovery-guard.yml` is explicit `workflow_dispatch` only. There is no recurring recovery automation. A permitted manual recovery is non-authoritative for scheduler continuity and does not complete a normal core slot.

`report_prefetch` is report-driven and separate from core upkeep. It may refresh public/authenticated personal, mini-league, live, or historical-backfill evidence as requested by a due report, but it does not complete the hourly core operational slot and does not substitute for scheduler proof.

`runtime_control` and `operational_slots` are the runtime evidence for logical-slot fulfillment, duplicate detection, continuity, provenance, and current scheduler proof. Historical gaps remain explicit; later successful slots must not silently rewrite them.

## Governed FPL Master orchestration

The normal governed core path is:

```text
FPL Master Monitor V12 (:30 Asia/Jakarta)
        │
        ▼
Canonical V12 NATURAL_CORE_UPKEEP_GATE
        │
        ├─ reuse same-slot authoritative fulfillment, or
        ├─ bind governed in-progress run, or
        └─ exactly one Issue #431 FPL_MASTER_SLOT title mutation
                │
                ▼
        GitHub issues:edited
                │
                ▼
        v6-natural-data-ingestion.yml
                │
                ▼
        acquire → runtime control → publish integrity
                │
                ▼
        dedicated V6 GitHub App publisher
                │
                ▼
        runtime-data-v6 authoritative snapshot
```

The issue-title control event is restricted to the repository owner and Issue #431 by workflow authorization. A successful `chatgpt_scheduler` publication counts as a completed operational slot and scheduler proof. V3/V4/V5 runtime data is never eligible as fallback.

A separate `report_prefetch` invocation may be issued for a due report. It reuses the governed publication plane but remains report-scoped rather than core-slot authority.

## Governed manual recovery

`workflow_dispatch` exists only as an emergency recovery valve. It is not a substitute for the scheduler and is deliberately non-authoritative.

A manual recovery:

- requires an explicit audit reason and the confirmation phrase defined by `config/v6/schedule_policy.json`;
- is restricted by the workflow contract to the repository owner;
- still uses the same isolated dedicated V6 GitHub App publisher and governed `runtime-data-v6` branch;
- is published as `schedule_kind: manual_recovery` with `scheduled_cycle: false`;
- does not advance `last_scheduled_cycle_at` and does not count as a completed scheduled slot;
- is manifested as AMBER/non-authoritative rather than pretending to restore scheduled health;
- remains invalid as primary V6 consumer authority until a real `schedule` cycle succeeds.

This recovery path can refresh V6-owned last-good evidence and caches during an incident without hiding `MISSED_SCHEDULED_CYCLE` evidence or creating false freshness. Consumers continue to use their documented minimum-scope external-source fallback whenever the latest V6 snapshot is stale or invalid. No V3/V4/V5 artifact may be used as a V6 fallback.

## Production workflow boundaries

The production workflow has two jobs with different authority:

1. `collect` is read-only. It hydrates the previous V6-owned last-good snapshot, runs a lightweight registry/runtime preflight, acquires active sources, applies runtime-control health, validates publish integrity, and transfers one verified artifact. Governed manual recovery is authorized before acquisition and remains non-authoritative in runtime control.
2. `publish` is the only writer. It requires the `v6-runtime-publisher` environment and a dedicated V6 GitHub App token. There is no generic `github.token` publisher fallback. It publishes an atomic orphan snapshot to `runtime-data-v6` using a branch lease and then verifies the exact published tree.

Runtime dependencies are installed from `requirements-v6.lock` with hashes. Full unit and regression contracts run in `v6-ci.yml` using `requirements-v6-ci.lock`; the hourly acquisition hot path does not rerun the unit-test suite.

## Registry and configuration

V6 source configuration is layered and schema-versioned:

1. `config/v6/source_registry.json` contains canonical base definitions.
2. `config/v6/source_additions.json` contains additive source definitions.
3. `config/v6/source_overrides.json` is a repair/incubation layer, not a second canonical registry.
4. `config/v6/source_activation.json` owns disabled, reference-only, activation constraints, and source tiers.

Operational scheduler policy is separately owned by `config/v6/schedule_policy.json`; it does not define source membership and therefore is not a second source registry.

The loader fails closed on schema mismatch, unknown source IDs, duplicate IDs, invalid auth/request configuration, missing required sources, invalid activation overlap, dependency gaps, and dependency cycles. The resulting dependency DAG is converted into topological execution layers. The effective source registry is published as `data/v6/evidence/resolved_registry.json` for drift review.

Stable endpoint repairs should be promoted out of `source_overrides.json` into their canonical source definition after they have proven stable. Overrides should remain a small repair/incubation surface.

## Source lifecycle

The configured source universe is intentionally larger than the active runtime set. Activation policy distinguishes:

- active sources collected by the hourly runtime;
- reference-only sources retained for targeted/manual evidence use but excluded from scheduled mirroring;
- disabled sources that are paid, access-restricted, duplicate, unstable, or intentionally dropped.

Do not hard-code the current active-source count in prose or architecture diagrams. `source_activation.json`, the resolved registry, and the published manifest are the authoritative runtime source-set evidence.

## Performance architecture

V6 is intentionally a modular in-process acquisition service rather than dozens of deployment units. Its logical domains are separated into registry, polling, HTTP acquisition, adapters, source-native normalization, identity, validation, health, runtime control, publish integrity, storage, consumer trust, and orchestration.

Independent sources execute concurrently within topological dependency layers. Independent requests within a source use bounded request-level concurrency. Only declared dependencies serialize. Distributed microservices or workflow shards should be introduced only when telemetry proves a provider family needs a distinct failure domain, rate-limit envelope, network policy, or materially different resource profile.

Premature service fragmentation is explicitly avoided because it would increase orchestration, duplication, and operational failure surface without improving the current acquisition workload.

## Weather ownership

`open_meteo` is currently **disabled as a V6 scheduled dependency** by `config/v6/source_activation.json` (`RETIRED_CHATGPT_REPORT_TIME_WEATHER_NOT_V6_DEPENDENCY`). Weather needed by a visible report is therefore a report-time evidence concern, not part of V6 core freshness or publication authority.

Historical V6 weather adapters/configuration may remain in the repository, but documentation must not present Open-Meteo as an active scheduled V6 source while activation policy disables it. Any future reactivation must update activation policy, runtime acceptance, and this document together.

## Persistent last-good state

Before acquisition, the workflow hydrates `data/v6/` only from the latest `runtime-data-v6` snapshot. It never hydrates V6 from V3/V4/V5 runtime branches or data trees. Failed requests do not silently erase a previously usable payload. Current attempts and effective data state remain distinguishable through explicit origin and health metadata.

A conditional HTTP `304 Not Modified` is successful current-cycle revalidation. A last-good cache carried because the provider could not be revalidated is degraded and must not be mislabeled as fresh live evidence.

## Runtime publication tree

The governed snapshot contains at least:

```text
data/v6/
├── manifest.json
├── current/<active source>.json
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
    └── publish_integrity.json
```

`publish_integrity` requires the current-source file set to exactly match the manifest, requires exact resolved-registry source identity and order, checks deterministic identity-map consistency, requires all declared artifacts, and hashes the runtime tree. Consumers recompute the integrity contract rather than trusting a stored GREEN label.

## Player identity

Official FPL element ID is the canonical player key. Deterministic provider bridges may add external IDs only when they can be verified. The Official-derived price predictor shares the Official element namespace. Vaastav mapping uses exact FPL element ID plus player code. Providers without a verified deterministic bridge remain explicitly unresolved.

Fuzzy player-name matching is not allowed in V6 identity publication. Partial deterministic coverage is preferable to fabricated or probabilistic identity matches.

## Freshness and consumer rule

The Master Monitor and other consumers apply a hard V6 freshness threshold of 90 minutes unless a stricter consumer contract is explicitly supplied. A static historical manifest that says GREEN is not sufficient. The consumer must verify current age, runtime-control provenance, exact source set, exact resolved registry, identity consistency, stored tree digest, recomputed tree digest, every zero-authority dimension, and control/critical failures.

A snapshot may become V6 consumer authority only when it comes from a governed authoritative runtime trigger, `authoritative_runtime_snapshot` is true, publish integrity passes, freshness is valid, and no disqualifying control/source failures exist. The normal core authority is `chatgpt_scheduler`; report-driven `report_prefetch` may publish an authoritative report snapshot but does not complete or prove the core operational slot. A governed `manual_recovery` snapshot remains non-authoritative for normal scheduler continuity by design. If the latest V6 snapshot is stale or invalid, only the documented minimum-scope external-source fallback is eligible. Fallback into another engine's runtime artifacts is forbidden.

## Runtime branch governance

`runtime-data-v6` is a publication branch, not a normal development branch. Production acceptance requires a repository ruleset that blocks deletion, non-fast-forward updates, and ordinary writes, with bypass restricted to the governed V6 publisher integration/app. Human or generic workflow-token bypass is not an accepted normal publication path.

The workflow-level publisher isolation does not replace repository-level branch governance. Both controls are required before V6 can be classified FULL GREEN PROD.

## Scale-out triggers

Create separate workflow shards or deployable services only when measured telemetry shows at least one of these conditions:

- a provider family repeatedly dominates cycle wall-clock time;
- provider-specific rate limits require a distinct scheduler;
- authentication or network policy requires a separate failure domain;
- payload/parsing resource needs materially differ from the common runtime;
- a provider family repeatedly causes worker starvation despite bounded timeouts and isolation.

Until one of these conditions is measured, the modular in-process V6 runtime remains the preferred architecture.
