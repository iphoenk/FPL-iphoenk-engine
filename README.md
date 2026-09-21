# FPL iphoenk Engine — V6 Data Plane + Canonical V12 Decision Plane

> **Last runtime/documentation sync:** `2026-09-21T14:05:00+07:00`  
> **Synchronization basis:** active `main` architecture, `config/v6/schedule_policy.json`, `config/v6/source_activation.json`, and current V12 authority paths.  
> This timestamp describes when the human-readable repository documentation was last reconciled to the runtime/control-plane contract. Mutable live health still comes from `runtime-data-v6`.

> **CURRENT ACTIVE ARCHITECTURE**
>
> **V6** is the only factual production data plane.  
> **Canonical V12** is the model, probability, tactical, optimization, decision, comparator, and report plane.  
> **V3 / V4 / V5 are frozen legacy**: no production execution, no production fallback, no new features, and no scheduler authority.

This repository powers a governed personal Fantasy Premier League decision system. The active design deliberately separates **facts** from **models and decisions** so that factual acquisition can remain stable while V12 analytics evolve without creating duplicate authorities.

## Active authority map

| Responsibility | Active owner |
|---|---|
| Factual acquisition / normalized production data | **V6** |
| Operational + methodology + decision + visible-report authority | `control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt` |
| Durable decision/report context | `control/fpl_master_v12/FPL_MASTER_STATE_V12.json` — **non-authoritative** |
| Minutes / start-state model | `src/engines/v12_player_minutes.py` — **P1.1 / V12_PLAYER_MINUTES** |
| Event / xPts / predictive distribution model | `src/engines/v12_player_events.py` — **P1.3/P1.3B / V12_PLAYER_EVENTS** |
| Tactical / role canonical scorer | `src/engines/v12_tactical_role.py` — **P1.6 / V12_TACTICAL_ROLE** |
| Generic player-vs-player comparator | `src/engines/v12_player_comparator.py` — orchestration only, **not a model owner** |
| Canonical decision methodology / economics contracts | `src/engines/canonical_decision_methodology.py` |
| Package/search layer | `src/engines/v12_package_search.py` |
| Correlated Monte Carlo | `src/engines/v12_monte_carlo.py` |
| Visible DEEP/PRICE/report orchestration | `src/engines/v12_report_orchestration.py` |
| Natural report acceptance observability | existing `src/runtime_v6/domains/report_plane/report_delivery.py` same-slot evidence owner; durable evidence only, **not** authority |
| FPL recurring orchestration | **FPL Master Monitor V12** — only recurring FPL acquisition/report scheduler authority; methodology remains in Canonical TXT |
| GitHub continuity watchdog | `v6-scheduler-watchdog.yml` — scheduled monitoring only; cannot acquire, publish, mutate #431, or advance scheduler proof |
| Emergency V6 recovery | `v6-core-recovery-guard.yml` — explicit `workflow_dispatch` only; non-recurring, non-authoritative, non-natural-slot recovery |

The README is a human-readable projection of the architecture. It is **not** a second methodology or mutable runtime authority.

## End-to-end active flow

```text
V6 factual acquisition
        │
        ▼
runtime-data-v6 factual snapshot
        │
        ├── Official FPL facts / fixtures / player universe
        ├── authenticated personal squad facts
        ├── mini-league facts where available
        ├── source / publication / identity health
        └── official_price_predictor artifact
        │
        ▼
Canonical V12 analytic execution
        │
        ├── P1.1  native minutes / availability / P(start) / DNP / xMins
        ├── P1.3  posterior event rates + fixture xPts
        ├── P1.3B point distribution / blank / return / tails / quantiles
        ├── P1.6  canonical tactical-role score
        ├── comparator 1GW / 2GW / 3GW / 5GW
        ├── package / economics / structural consequences
        ├── P1.7 XI / bench / captain / vice
        ├── Monte Carlo when governed and supportable
        └── P1.8 mini-league overlay after football baseline
        │
        ▼
WAIT / PREPARE / ACT
        │
        ▼
DEEP / PRICE / Match / Deadline / Final / Post-Match reports
```

No V12 projection is allowed to become a competing factual source. No V6 artifact is allowed to become a decision authority.

## V6 factual production plane

V6 is **DATA ONLY**.

It may acquire, normalize, validate, join, health-check, and publish factual/evidence artifacts. It must not own:

- xPts or projected player points;
- xMins / start probabilities;
- tactical scores;
- transfer recommendations;
- XI / bench / captain decisions;
- package optimization;
- Monte Carlo decisions;
- mini-league strategic decisions.

Important runtime artifacts are published on the `runtime-data-v6` branch, including:

```text
data/v6/current/official_fpl.json
data/v6/current/official_price_predictor.json

data/v6/personal/current_team.json
data/v6/personal/memberships.json
data/v6/personal/submitted_picks.json

data/v6/mini_leagues/...

data/v6/health/source_health.json
data/v6/health/publish_integrity.json
data/v6/health/runtime_control.json
data/v6/health/operational_slots.json
data/v6/health/report_prefetch.json
```

Official FPL remains the canonical authority for Official-FPL-native identities, fixtures, rules, prices, squad facts, and scoring facts.

V6 architecture and governance documentation:

- `docs/V6_FRESH_DATA_PLATFORM.md`
- `docs/V6_IDENTITY_BRIDGE_ROADMAP.md`

Mutable source health, universe size, identity coverage, and runtime timestamps must be read from runtime artifacts rather than hardcoded into this README.

## Native V12 owner chain

### P1.1 — minutes / availability owner

`V12_PLAYER_MINUTES` owns the finite-state minutes model.

Native comparator binding consumes, without recalculation when native values exist:

```text
conditional_probabilities.p_available
derived_probabilities.p_start
derived_probabilities.p_dnp
derived_probabilities.p_cameo
derived_probabilities.p_late_cameo
xmins_distribution.mean
xmins_distribution.states
```

The comparator may normalize these fields for presentation, but cannot create a second xMins model.

### P1.3 / P1.3B — event and xPts owner

`V12_PLAYER_EVENTS` consumes P1.1 minute-state evidence and publishes native predictive outputs including:

```text
aggregate.expected_fpl_points
aggregate.points_variance
aggregate.points_std
event_probabilities.p_attacking_return
point_distribution.p_fpl_blank
point_distribution.quantiles
point_distribution.tails
point_distribution
```

Floor/downside and ceiling/upside are taken from the existing governed point distribution. Production comparator logic must not manufacture arbitrary `xPts ± N` ranges.

P(60+) evidence is exposed only from the existing governed finite-state + bounded-quadrature path. No Gaussian approximation, normal fallback, or second minutes model is introduced.

### P1.6 — tactical / role owner

`V12_TACTICAL_ROLE` owns the Canonical tactical-role component, including fields such as:

```text
canonical_tactical_role_score
scoring_channel_vector
scoring_channel_diversity
tactical_role_fit
role_resilience
fixture_suppression_raw
fixture_suppression_effective
feature_evidence
```

Verified tactical profile narrative is kept separate from the P1.6 numerical owner. Coach, formation, build-up, pressing, width, opponent-profile narrative, and similar descriptive context must not be fabricated merely to make a tactical score look complete.

Tactical evidence classes remain:

`OBSERVED_ROLE / INFERRED_ROLE / FPL_POSITION_ONLY / UNKNOWN`.

## Generic player comparator

The V12 comparator is **read-only orchestration**, not another projection model.

It binds existing owner outputs and exposes pairwise evidence for:

- per-GW opponent and H/A;
- xPts;
- xMins;
- P(start), P(DNP), governed P60 when supportable;
- P(return), P(blank), point distribution;
- tactical-role evidence and route to points;
- rest / congestion evidence;
- 1GW, 2GW, 3GW, and 5GW horizons;
- raw football gain;
- downstream affordability / economics / structure / robustness evidence;
- mini-league overlay only after football-optimal baseline;
- final operational state: **WAIT / PREPARE / ACT**.

It must preserve:

```text
duplicate_xpts_model = false
duplicate_xmins_model = false
duplicate_tactical_scorer = false
decision_authority = false
ranking_authority = false
```

Candidate input order is not a hidden ranking.

## Price prediction integration

V6 publishes the existing `official_price_predictor` artifact. V12 report orchestration **consumes it; it does not create a second price predictor**.

Primary production schema:

```text
data.players[]
  id
  web_name
  now_cost
  selected_by_percent
  transfers_in_event
  transfers_out_event
  price_change_percent
  price_change_hourly_rate
  price_change_projections[]
  price_change_locked_until
  price_change_calibrating
```

V12 uses only the projection with:

`offset == 0`

for the current RISE20/FALL20 surface.

Sorting contract:

```text
RISE20: projected_percent DESC, id ASC
FALL20: projected_percent ASC,  id ASC
```

Current Official price is a **FACT**. Projected movement is a **MODEL / PREDICTION**. They must never be conflated.

If a healthy artifact contains at least 20 usable offset-0 rows, both RISE20 and FALL20 must render exactly 20 rows. No padding is allowed.

A healthy predictor does **not** need to predict a threshold crossing for every selected row. `NO_CROSSING_WITHIN_GOVERNED_HORIZON` is a valid healthy terminal result and does not by itself make RISE20/FALL20 DEGRADED. DEGRADED is reserved for actual source/evidence problems such as stale or missing predictor data, insufficient offset-0 coverage, invalid schema/identity, unavailable cycle timing evidence, or `DATE_UNAVAILABLE`. Official FPL current-price facts remain independently authoritative and do not inherit degradation from unrelated predictor/model/workflow plumbing.

## Decision methodology

The canonical player-evaluation weighting remains:

```text
20% historical / proven evidence
25% tactical / role
30% current underlying evidence
25% fixture / security
```

This weighting is owned by Canonical V12 methodology, not by V6 and not by the comparator.

Serious decision flow is expected to distinguish:

```text
Gate0 / legality
→ factual universe and search scope
→ native owner probabilities
→ tactical / role evidence
→ horizon distributions
→ package / transfer economics
→ structural XI / bench consequences
→ Monte Carlo when governed
→ mini-league overlay
→ WAIT / PREPARE / ACT
```

Missing evidence must remain explicit. A report must never silently convert missing evidence into zero, neutral fact, fabricated tactical context, or an invented probability.

## Reporting

Visible reporting is governed by:

`control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt`

The scheduler is intentionally a minimal bootstrap. It reads Canonical authority rather than duplicating methodology in its prompt.

Canonical routing includes static and dynamic report modes such as:

- DEEP;
- PRICE;
- Deadline / Final;
- scoring-GW Match;
- Post-Match;
- Post-All-Match.

Dynamic Match routing is evaluated from actual scoring-GW fixture state. “Matchday” by itself does not mean every hourly occurrence must render a visible Match report.

Interactive mode-equivalent requests use the same report-plane contract. A user request such as “DEEP sekarang”, “PRICE sekarang”, or “format 04:30 tapi mode sekarang” is an **AD_HOC occurrence of that Canonical mode**, not a request to imitate its headings manually. It must pass the same pre-render and actual visible-body post-render QA as the scheduled mode; for RISE20/FALL20, supported cycle/ETA fields must be visibly rendered or the same-request render is rejected and rebuilt.

DEEP is also an analytic report, not a thin summary surface. After a completed GW, the next applicable DEEP carries the full completed-fixture match-by-match scout inside the existing Changes section. For every serious XI/transfer/package/captain decision, a visible **MATHEMATICAL DECISION STACK** must expose Bayesian/shrinkage, availability and xMins mixtures, event probabilities, horizon distributions, regret/robustness/covariance, and Monte Carlo execution state. If Monte Carlo is not actually run, the report must say NOT RUN/PARTIAL with the reason rather than silently omitting it.

Visible event probabilities are bound directly to the existing V12 P1.3/P1.3B posterior-predictive outputs. Goal, assist, attacking-return, multiple-return, FPL-blank and haul probabilities must not be reconstructed by the report renderer from xG/xA or mean xPts. The report plane exposes the native distribution and labels unavailable evidence truthfully.

A second 21 Sep 2026 natural-occurrence audit found a different class of failure in the actual 12:30 DEEP path: the natural automation could reuse the previous hourly V6 snapshot as if it were the current HH:00 core slot, omit a same-report-slot full_master report-prefetch, and compose freeform prose without proving the Canonical section catalog or actual post-render/human-facing QA. Natural acceptance now proves that core_logical_slot is the exact hour floor of scheduler_occurrence after timezone normalization, proves the actual mode section catalog rather than trusting critical_sections_present, and requires post-render plus human-facing QA. Canonical natural DEEP also requires an exact-report-slot report-scope refresh decision and forbids freeform prose as a substitute for S01-S15, S15B, S16-S19. The runtime refresh planner now uses the governed issue #431 report-prefetch COMMENT transport and explicitly refuses to treat core-slot fulfillment as proof that report-specific personal/mini-league/live scopes are current. For example, a 12:30 WIB occurrence can only reuse a 12:00 WIB (05:00Z) core snapshot; 11:00 WIB (04:00Z) is not same-slot.

The missing execution bridge is now explicit in-repository rather than prompt-only. `src.engines.v12_integrated_report_runner` is the executor-only DEEP composition layer and `.github/workflows/v12-integrated-report-runner.yml` accepts only owner-authored issue #431 `/v12-report-run` comments (or explicit workflow_dispatch diagnostics). It hydrates `runtime-data-v6` read-only, binds each expected V12 owner stage, materializes the exact Canonical DEEP section catalog, runs pre-render / post-render / human-facing QA, and uploads `report_bundle.json`, `report_body.md`, and `execution_proof.json` as `v12-report-DEEP-<run_id>`. Missing prerequisites remain explicit PARTIAL/NOT_RUN stage results; no silent owner-stage skip, no fabricated Monte Carlo, no V6 publication mutation, and no second scheduler are allowed. This closes the earlier gap where the automation prompt referenced `/v12-report-run` but no repository command/workflow/artifact implementation existed.

A 21 Sep 2026 report-plane audit hardened mode/section conformance end to end. Runtime QA catalogs now match the Canonical V12 backbones for DEEP/FULL/DEADLINE/OVERLAP, MATCH 1–13, PRICE 1–11, POST-ALL-MATCH 1–13, and FINAL with the inserted GW LOCK PACKAGE. Visible parsing now supports two-digit mode sections and uses the current DEEP section mapping (XI/bench S06, Watchlist20 S11, RISE20 S12, FALL20 S13, ALL15 S16). Mode-specific count contracts prevent PRICE or POST-ALL-MATCH from inheriting unrelated Full-report counts, and visible OUR15/XI identity validation now runs only in modes whose contract actually requires those counts. Mini-league pre-render now binds the Canonical S15B surface rather than the obsolete S14B, and pre-delivery Watchlist/RISE/FALL validation now binds S11/S12/S13 rather than the prior S10/S11/S12 mapping. COMPLETE sections cannot silently materialize without human-facing content, post-render QA rejects status-only visible sections, degraded/unavailable sections retain a visible reason, and decision-bearing DEEP/FULL/Deadline/Final/PRICE reports require the Canonical NOW / TRIGGER TO ACT / ABORT-REVERSAL / NEXT CHECKPOINT action board.

The `official_price_predictor` artifact represents the verified 2026/27 **Official FPL Price Change Predictor**. Current price and confirmed overnight price changes remain Official FPL FACT. Predictor current progress, predicted progress, likelihood/status and >100% threshold guidance are Official FPL predictor/model outputs and remain guidance rather than guaranteed outcomes. V12 may add decision-layer interpretation such as affordability impact or WAIT/PREPARE/ACT, but it must not relabel the official predictor as third-party or merely V6-derived.

Section 14 **Package Optimizer / Frontier** is explicitly full-universe-first. A serious DEEP/FULL/Deadline/Final squad-improvement report must evaluate all 15 owned players as possible outgoing weak links and scan the complete currently eligible Official FPL universe before publishing challengers. The visible block `UNIVERSE SCAN / OPTIMAL TEAM IMPACT` must show search coverage, scan-derived candidate players, their best outgoing/package pairing, canonical 20/25/30/25 and probability/horizon evidence, package utility versus HOLD, economics/structure/regret/information-value effects, and then the legal package frontier. A hand-picked shortlist or user-mentioned names cannot masquerade as a full optimizer result; incomplete scope remains visibly PARTIAL/DEGRADED.

Prospective natural occurrences also retain one bounded, machine-readable acceptance proof on the existing same-slot report-delivery evidence surface. It records the executed two-stage REPORT_DUE result, fixture evidence, render structure/digest, locked-team source/status, ICON+ coverage metadata, and a separate UI-delivery-ack state. This proof is observability only: `RENDER_PROVEN=true` never means the client UI acknowledged delivery, and `DELIVERY_UI_ACK=UNAVAILABLE` does not invalidate a proven routing/render pass. Historical occurrences are not retrofitted.

A scoring GW still in progress is not a reason to suppress supportable next-GW analytics.

When the current V6 factual plane is fresh and healthy for the routed report, with `publish_integrity=PASS` and an authoritative runtime snapshot, V12 must consume those facts and execute every supportable Canonical analytic path needed by the report. A missing proof of repository Python execution, missing precomputed repository-model artifact, or unrelated plumbing status may not by itself collapse a healthy report into broad `DEGRADED`. Only the exact unsupported field or scope may degrade, with its reason stated explicitly.

## State semantics

`FPL_MASTER_STATE_V12.json` is durable context/evidence only.

It is explicitly **non-authoritative**. It may not become a second methodology source or persist raw V6 payloads as a competing factual store.

Latest explicit user state may be carried as decision/report context, while Canonical TXT remains the methodology and operational authority.

## Governance invariants

The active system enforces these architectural boundaries:

- V6 remains factual and data-only.
- V12 owns modeling and decision logic.
- V3/V4/V5 have zero active production execution.
- No legacy fallback is permitted.
- No second FPL acquisition scheduler is permitted.
- The only scheduled V6 GitHub control workflow is the monitoring-only watchdog at :50; it cannot initiate acquisition.
- Emergency recovery is explicit/manual-only via workflow_dispatch and can never count as natural scheduler proof.
- Issue #431 is the only normal full-core attempt transport and is mandatory only in ATTEMPT_REQUIRED; its success is never a prerequisite for a due visible report.
- No second xPts model is permitted.
- No second xMins model is permitted.
- No second tactical scorer is permitted.
- No second price predictor is permitted.
- State remains non-authoritative.
- Raw V6 payloads are not persisted into decision state.
- Current runtime truth is never inferred from historical README text.

Repository governance and V6 CI must remain GREEN before a bounded repair is treated as accepted.

### Documentation synchronization contract

Every pull request must include an ISO-8601 `Change timestamp`, `Documentation sync: UPDATED`, and a matching `Documentation timestamp` in its description. **Every repository change must update `README.md` in the same PR**, even when the implementation change is small or otherwise documentation-neutral. The README's visible `Last runtime/documentation sync` timestamp must equal the PR's `Documentation timestamp`. Relevant deeper documentation must also be updated whenever runtime, architecture, control-plane, methodology, scheduler, source activation, workflow, or governance behavior changes. `Documentation sync: NOT_APPLICABLE` is no longer accepted.

The README update should remain concise and describe the resulting repository/runtime truth in the relevant section; it must not become a second authority or a noisy commit log. The machine-enforced contract lives in `.github/workflows/repository-governance.yml`; the human-readable policy is `docs/REPOSITORY_DOCUMENTATION_SYNC_POLICY.md`. PR authors should start from `.github/PULL_REQUEST_TEMPLATE.md`.

## Legacy

V3 / V4 / V5 source and documentation may remain in the repository for migration archaeology, static validation, and capability mining only.

They are **FROZEN LEGACY**, not production runtime.

See:

`docs/LEGACY_V3_V4_V5_FREEZE_V12_PORTING_ASSESSMENT.md`

## Repository principle

The intended invariant is simple:

> **V6 tells V12 what is factually true. V12 decides what those facts mean for FPL.**

Facts, probability models, tactics, optimization, decisions, and reports remain separately owned and auditable.
