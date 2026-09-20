# FPL iphoenk Engine — V6 Data Plane + Canonical V12 Decision Plane

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
| FPL recurring orchestration | **FPL Master Monitor V12** — single scheduler, methodology remains in Canonical TXT |

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

A scoring GW still in progress is not a reason to suppress supportable next-GW analytics.

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
- No second scheduler is permitted.
- No second xPts model is permitted.
- No second xMins model is permitted.
- No second tactical scorer is permitted.
- No second price predictor is permitted.
- State remains non-authoritative.
- Raw V6 payloads are not persisted into decision state.
- Current runtime truth is never inferred from historical README text.

Repository governance and V6 CI must remain GREEN before a bounded repair is treated as accepted.

## Legacy

V3 / V4 / V5 source and documentation may remain in the repository for migration archaeology, static validation, and capability mining only.

They are **FROZEN LEGACY**, not production runtime.

See:

`docs/LEGACY_V3_V4_V5_FREEZE_V12_PORTING_ASSESSMENT.md`

## Repository principle

The intended invariant is simple:

> **V6 tells V12 what is factually true. V12 decides what those facts mean for FPL.**

Facts, probability models, tactics, optimization, decisions, and reports remain separately owned and auditable.
