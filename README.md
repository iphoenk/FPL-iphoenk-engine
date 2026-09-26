# FPL iphoenk Engine

> **Last README sync:** `2026-09-26T21:38:22+07:00`  
> **Production main at sync:** `bc086a030a49440a1703943c2844dd6d1831a865`  
> This timestamp records when this human-readable README was reconciled with the repository. Live runtime health and current production evidence must be read from the active workflows and runtime artifacts, not inferred from this timestamp.

A governed Fantasy Premier League decision engine that separates **public football facts and reproducible compute** from **private manager-specific state and decisions**.

The active architecture is deliberately simple:

- **V6** owns the factual data plane.
- **Canonical V12** owns analytics, probability, tactics, optimization, decisions, and report semantics.
- **Private delivery** owns manager-specific state and decision output.
- **V3 / V4 / V5** are frozen legacy and are not production authorities.

The core principle is:

> **V6 tells V12 what is factually true. V12 decides what those facts mean for FPL.**

## Questions it answers

1. Who should start, sit on the bench, captain, and vice-captain?
2. Which transfer or transfer package improves the squad over 1, 2, 3, and 5 gameweeks?
3. How secure are a player's minutes and starting probability?
4. What do xG, xA, xGI, shots, box involvement, role, set pieces, fixtures, and recent match evidence imply?
5. Which players are breaking out, regressing, or becoming materially more relevant across the full FPL universe?
6. How do price movement, affordability, free transfers, hits, and reversal risk affect a decision?
7. How should mini-league exposure, captaincy, overlap, differentials, and direct rivals be interpreted without overriding stronger football evidence?
8. What changed after each match, and should the action remain **WAIT**, move to **PREPARE**, or become **ACT**?

## Architecture

| Plane | Responsibility | Production status |
| --- | --- | --- |
| **V6 factual plane** | Official/public football facts, source normalization, freshness, identity, fixture and price evidence | Active |
| **V12 analytics plane** | xMins, start probability, projections, posterior distributions, tactical/role evidence, post-match interpretation | Active |
| **V12 decision plane** | XI/bench, captain/vice, transfer packages, Monte Carlo, staging, mini-league overlay, final action | Active |
| **Private delivery plane** | Current squad state, private finance, exact routes, XI/bench/C/VC, chips, scenarios, full reports | Active |
| **V3 / V4 / V5** | Historical implementation and migration archaeology | Frozen legacy |

The public repository may contain source code, models, reproducible football facts, non-sensitive QA/proof, performance metadata, and public-safe caches. Manager-specific state and decision material must remain outside the public factual plane.

## Decision model

The engine does not reduce player evaluation to one headline stat. Current decision surfaces combine four evidence families:

| Evidence family | Weight |
| --- | ---: |
| Proven / historical | 20% |
| Tactical / role | 25% |
| Current underlying | 30% |
| Fixture / security | 25% |

Those surfaces feed the downstream probability, lineup, transfer-package, Monte Carlo, and mini-league layers. Missing evidence is surfaced as unavailable or degraded rather than silently replaced with invented values.

## How it works

1. **Acquire facts**  
   V6 ingests and normalizes governed public sources, preserving freshness, lineage, fixture identity, and source health.

2. **Build player distributions**  
   V12 converts the factual plane into xMins / starting probability, underlying attacking and defensive evidence, tactical context, historical trajectory, uncertainty, and multi-GW projections.

3. **Scan the full universe**  
   Candidate discovery is not limited to the owned squad or a hand-picked watchlist. Position-aware scanning looks for material breakout, regression, role, fixture, and value changes across the eligible player universe.

4. **Optimize exact decisions**  
   The decision core evaluates legal XI, bench ordering, captain/vice combinations, transfer routes, package utility, and relevant future horizons without allowing presentation code to become a second optimizer.

5. **Model uncertainty**  
   Probability distributions and Monte Carlo are used where supportable so decisions can consider upside, downside, blank risk, regret, and optionality rather than mean xPts alone.

6. **Apply manager context privately**  
   Current team state, budget, free transfers, selling values, chips, scenarios, exact routes, and mini-league context are combined only in the private decision/delivery plane.

7. **Render fail-closed reports**  
   Human-facing reports retain canonical section ownership, evidence lineage, degradation reasons, and cross-section validation before a result is treated as deliverable.

## Main report surfaces

Canonical DEEP reporting covers:

- current status and OUR15;
- decision delta and material developments;
- fixtures, rest, workload, and conditions;
- formation, XI, bench, captain and vice-captain;
- price radar and full-universe watchlist;
- RISE / FALL movers;
- transfer-package frontier and three-GW staging;
- evidence quality and source health;
- mini-league exposure and direct-rival context;
- ALL15 tactical/probability review;
- GW1-to-now post-match review;
- action board and final judgement.

The detailed section contract is intentionally maintained outside this README so the front page stays readable.

## Public / private boundary

The repository is public compute, not a public diary of one manager's decisions.

**Public-safe examples**

- source code and model definitions;
- public football facts;
- reproducible projections where they do not disclose private manager state;
- non-sensitive validation and performance proof;
- public-safe execution caches.

**Private-only examples**

- authenticated current-team state;
- bank, selling values, free transfers, chips, and pending private state;
- exact transfer routes and squad scenarios;
- final XI, bench, captain, vice-captain, staging, and manager-specific action;
- full human-facing decision reports.

A private-delivery failure must not fall back to publishing the same material publicly.

## Data and evidence

The engine is **Official-FPL-first** for facts that the official game can authoritatively provide. Other football data and analyst evidence can enrich the model when governed by their source contracts, but they do not silently replace Official FPL authority.

Historical match evidence is kept observational until an authoritative model recomputation has occurred. Post-match rows, tactical interpretation, and link-up dependencies are therefore separated from claims that a posterior has actually been updated.

## Repository layout

```text
src/                production engine and analytics code
config/             runtime, source, schedule and model configuration
control/            control-plane and governed execution state
scripts/            operational and validation entry points
tests/              regression, semantic and architecture tests
test_support/       test fixtures and support utilities
docs/               architecture, migration, governance and audit detail
.github/workflows/  CI, report execution and repository governance
```

Useful documentation:

- [Repository documentation sync policy](docs/REPOSITORY_DOCUMENTATION_SYNC_POLICY.md)
- [FPL Master Monitor schedule governance](docs/FPL_MASTER_MONITOR_TIME_SCHEDULE_GOVERNANCE.md)
- [Legacy V3/V4/V5 freeze assessment](docs/LEGACY_V3_V4_V5_FREEZE_V12_PORTING_ASSESSMENT.md)
- [P1.2A package search](docs/P1_2A_PACKAGE_SEARCH.md)
- [P1.2B package utility](docs/P1_2B_PACKAGE_UTILITY.md)
- [P1.7 lineup migration](docs/P1_7_LINEUP_MIGRATION.md)
- [P1.8 mini-league overlay](docs/P1_8_MINI_LEAGUE_OVERLAY.md)
- [GW1 matchup and link-up methodology](docs/V12_GW1_MATCHUP_LINKUP_METHODOLOGY.md)

## Development

Install the repository dependencies appropriate to the target runtime, then run the relevant test scope before proposing a change.

Typical local regression entry point:

```bash
python -m pytest -q
```

Repository changes are governed by CI and the documentation-sync contract. A change is not production truth merely because code exists on a branch or because an older README says it passed.

## Current status

As of the README sync timestamp above:

- production `main` is `bc086a030a49440a1703943c2844dd6d1831a865`;
- the V6 public factual plane is the active factual architecture;
- Canonical V12 is the active analytics and decision architecture;
- the public/private decision-data boundary has been cut over on production main;
- V3 / V4 / V5 remain frozen legacy;
- private manager-specific output is not intended to be published through the public repository.

For current runtime acceptance, workflow state, or source freshness, inspect the latest production evidence rather than treating this section as a live dashboard.

## Caveat

This is a decision-support system, not an oracle. FPL outcomes remain highly stochastic, player availability can change quickly, and some evidence can be delayed or unavailable. The engine therefore distinguishes factual authority, model output, uncertainty, and final manager action instead of presenting every estimate as a fact.
