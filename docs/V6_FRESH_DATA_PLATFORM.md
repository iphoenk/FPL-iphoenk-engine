# V6 Fresh Data Platform

## Mission and authority

V6 is the repository's dedicated fresh-data acquisition, validation, provenance, identity, health, and evidence-publication layer. It is data-only. V6 has no transfer, captaincy, chip, optimizer, xPts, xMins, Monte Carlo, tactical, recommendation, or decision authority.

Official FPL is the factual and canonical authority for player, team, fixture, and current FPL state. External providers remain separate evidence sources. V6 never averages providers into a hidden consensus and never fabricates missing values.

Consumers such as reporting and the Master Monitor may read a published V6 snapshot. The FPL Master Monitor is also a governed V6 acquisition orchestrator: its hourly task may invoke V6 through the explicit `master_orchestrated` workflow-dispatch mode. Other consumers must not trigger V6 refresh. All consumers must evaluate snapshot freshness and integrity at read time. A stale, missing, invalid, or broken V6 snapshot may permit a minimum-scope direct fallback by the consumer.

V6 never reads V3/V4/V5 runtime branches, data trees, caches, manifests, or engine artifacts. Those engines are downstream consumers only. Any permitted consumer fallback is external-source retrieval owned by that consumer; it is never a fallback from V6 into another engine's runtime data.

## Production cadence and trigger authority

V6 supports two independent authoritative operational triggers. The preferred operational path is the hourly FPL Master Monitor invoking `workflow_dispatch: master_orchestrated`; the repository natural scheduler remains a separate recovery/observability path and its health is tracked independently.

The natural scheduler cadence remains intentionally offset from other repository cron traffic and from GitHub's high-load start-of-hour window:

- primary acquisition: minute `23` of every UTC hour;
- idempotent recovery acquisition: minute `53` of every UTC hour.

The Master-orchestrated invocation and both natural scheduled invocations belong to the same logical hourly operational slot. If an authoritative V6 cycle already published that slot, a later natural primary/recovery invocation exits without a second acquisition. Normal pushes and pull requests never trigger production acquisition. CI is a separate read-only workflow.

The schedule expressions and emergency-recovery policy are declared in `config/v6/schedule_policy.json`. GitHub's `on.schedule` expressions must remain literal in the workflow, so contract tests verify that those trigger expressions exactly match the policy file. The classifier reads the policy file instead of duplicating cron literals in executable logic. The contract also requires both schedule minutes to stay away from the top of the hour and keeps recovery 30 minutes behind primary without hard-coding a second schedule registry.

`runtime_control` records the logical slot, GitHub run ID, trigger kind, schedule lag, duplicate detection, authoritative operational-cycle state, and natural missed-cycle state. `master_orchestrated` is authoritative for V6 runtime freshness but does not count as a natural scheduled cycle. Missed natural scheduler cycles therefore remain explicit evidence and are never hidden by Master orchestration or emergency manual recovery.

## Governed FPL Master orchestration

`workflow_dispatch` with `mode: master_orchestrated` is the governed hourly acquisition path used by the FPL Master Monitor. It requires a non-empty audit reason, is restricted to the repository owner, uses the same isolated dedicated V6 GitHub App publisher, publishes `schedule_kind: master_orchestrated`, and may set `authoritative_runtime_snapshot: true` only after the normal V6 source-health, lineage, identity, publish-integrity, and isolation checks pass.

A Master-orchestrated cycle counts as a completed operational slot but not as a completed natural scheduled slot. It never advances `last_scheduled_cycle_at`, never rewrites historical natural-scheduler evidence, and never uses V3/V4/V5 runtime data as fallback.

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

The current activation contract contains 21 scheduled active sources. Do not infer the active count from old documentation or from the number of configured definitions. `source_activation.json`, the resolved registry, and the published manifest are the authoritative runtime source-set evidence.

## Performance architecture

V6 is intentionally a modular in-process acquisition service rather than dozens of deployment units. Its logical domains are separated into registry, polling, HTTP acquisition, adapters, weather, identity, normalization, health, runtime control, publish integrity, storage, consumer trust, and orchestration.

Independent sources execute concurrently within topological dependency layers. Independent requests within a source use bounded request-level concurrency. Only declared dependencies serialize. Distributed microservices or workflow shards should be introduced only when telemetry proves a provider family needs a distinct failure domain, rate-limit envelope, network policy, or materially different resource profile.

Premature service fragmentation is explicitly avoided because it would increase orchestration, duplication, and operational failure surface without improving the current acquisition workload.

## Open-Meteo ownership

Open-Meteo is a native V6 source. V6 retrieves weather directly from `api.open-meteo.com` through the V6 acquisition client. V6 does not retrieve weather from V3 and V3 is not an upstream dependency of the V6 weather adapter.

The only declared dependency of `open_meteo_weather` is `official_fpl`, used for fixture, home-team, and kickoff authority. Venue coordinates come from the canonical 2026/27 venue registry rather than duplicated source configuration.

Weather is contextual evidence only. It cannot directly multiply xPts and weather alone cannot trigger a transfer decision.

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

A snapshot may become V6 consumer authority only when its governed provenance is `primary`, `recovery`, or `master_orchestrated`, `authoritative_runtime_snapshot` is true, publish integrity passes, freshness is valid, and no disqualifying control/source failures exist. A governed `manual_recovery` snapshot remains invalid for that role by design. Natural scheduler health is a separate operational signal and must not be inferred from a Master-orchestrated publication. If the latest V6 snapshot is stale or invalid, only the documented minimum-scope external-source fallback is eligible. Fallback into another engine's runtime artifacts is forbidden.

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
