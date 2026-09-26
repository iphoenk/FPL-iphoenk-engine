# FPL iphoenk Engine

> **Last runtime/documentation sync:** `2026-09-26T22:09:45+07:00`  
> **Production main at sync:** `88a5c79dcfecd5032e6893dd422b620231b90f37`  
> This timestamp records when this human-readable README was reconciled with the repository. Live runtime health and current production evidence come from the active workflows and runtime artifacts, not from this timestamp.

A governed Fantasy Premier League decision engine that separates **public football facts and reproducible compute** from **private manager-specific state and decisions**.

The active architecture is deliberately simple:

- **V6** owns the factual data plane.
- **Canonical V12** owns analytics, probability, tactics, optimization, decisions, and report semantics.
- **Private delivery** owns manager-specific state and decision output.

The core principle is:

> **V6 tells V12 what is factually true. V12 decides what those facts mean for FPL.**

## Questions it answers

1. Who should start, sit on the bench, captain, and vice-captain?
2. Which transfer or transfer package improves the squad over 1, 2, 3, and 5 gameweeks?
3. How secure are a player's minutes and starting probability?
4. What do underlying numbers, tactical role, opponent matchup, set pieces, penalties, workload, and recent match evidence imply?
5. Which players are breaking out, regressing, or becoming materially more relevant across the full FPL universe?
6. How do price movement, affordability, free transfers, hits, regret, and reversal risk affect a decision?
7. How should mini-league exposure, captaincy, overlap, differentials, and direct rivals alter decision utility without overriding stronger football evidence?
8. What changed after each match, and should the action remain **WAIT**, move to **PREPARE**, or become **ACT**?

## Architecture

| Plane | Responsibility | Production status |
| --- | --- | --- |
| **V6 factual plane** | Official/public football facts, source normalization, freshness, identity, fixture and price evidence | Active |
| **V12 analytics plane** | xMins, start probability, position-specific probability components, posterior distributions, tactical/role evidence, post-match interpretation | Active |
| **V12 decision plane** | XI/bench, captain/vice, transfer packages, Monte Carlo, staging, mini-league overlay, final action | Active |
| **Private delivery plane** | Current squad state, private finance, exact routes, XI/bench/C/VC, chips, scenarios, full reports | Active |

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

## What the engine measures by position

Every player is evaluated with shared foundations such as **availability, xMins, P(start), role security, fixture context, recent trajectory, price/value, uncertainty, and multi-GW projection**. The event model then changes by FPL position instead of applying one generic formula to everyone.

| Position | Main measured / modelled components |
| --- | --- |
| **GK** | xMins and P(start); shots on target faced; save-count distribution; save percentage; P(3/6/9/12+ saves); expected save points; clean-sheet probability; goals-conceded distribution; penalty-save probability; BPS/bonus behaviour; opponent shot volume and pressure |
| **DEF** | xMins and P(start); clean-sheet probability; goals-conceded downside; DefCon probability and defensive workload; xG/npxG, xA/xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; aerial and set-piece threat; attacking full-back/wing-back role; BPS/bonus |
| **MID** | xMins and P(start); xG/npxG, xA/xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; goal and assist processes; penalty involvement; set-piece role; clean-sheet point probability; DefCon contribution; tactical creation/transition matchup; BPS/bonus |
| **FWD** | xMins and P(start); xG/npxG and goal-generation process; xA and assist process; xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; penalty involvement; set-piece and aerial threat; striker/runner role versus high line, central centre-backs and transition weakness; BPS/bonus |

The matchup layer is role-aware. Examples include runner vs high defensive line, central striker vs central centre-backs, aerial target vs aerial weakness, creator vs weak central pressure, winger vs vulnerable full-back, attacking full-back vs narrow defence, set-piece target vs weak set-piece defence, and goalkeeper vs opponent shot volume.

The model also keeps FPL scoring mechanics explicit, including appearance points, clean sheets, goals conceded, save intervals, DefCon, goals, assists, cards, own goals, penalty misses/saves, and stochastic bonus rather than applying a generic final-point uplift.

## What sets this engine apart

The repositories and models we reviewed are useful, but many are intentionally narrower: a structural/value model, a solver fed by precomputed xPts, a dashboard, a cache/mirror, a watchlist, or a validation layer. This project combines those concerns into one governed decision pipeline.

| Dimension | Narrower pattern seen in reviewed FPL projects | FPL iphoenk Engine |
| --- | --- | --- |
| **Player universe** | shortlist, watchlist, top-N or preselected candidates | scans the **full eligible FPL universe** first; Watchlist/RISE/FALL are outputs, not the search boundary |
| **Position modelling** | one common player formula or mostly headline xPts/value | separate **GK / DEF / MID / FWD event mechanics**, role context and position-specific matchup components |
| **Minutes risk** | projected minutes as one fixed number | **xMins distribution + P(start)**, availability, cameo/DNP risk and role security |
| **Underlying data** | xG/xA/value summary | xG/npxG/xA/xGI plus shots, SIB, SOT, big chances, box touches, creation, role, set pieces, penalties and defensive contribution where applicable |
| **Tactical layer** | fixture difficulty or team-level strength only | player archetype × actual role × coach/system × opponent mechanism, including link-up dependencies |
| **Uncertainty** | mean xPts | event probabilities, point PMFs, blank/haul risk, tails and quantiles, plus correlated Monte Carlo when required |
| **Transfers** | best single transfer or solver from supplied projections | legal **1/2/3+ transfer packages**, funded routes, exact affordability, hits/FT economics, 1/2/3/5-GW horizons, robustness, regret and reversal |
| **Decision search** | optimizer starts from a reduced candidate list | serious transfer decisions carry explicit full-universe search proof and owned-squad outgoing scan |
| **Mini-league** | global ownership or EO only | league/rival/direct-rival exposure, captaincy and rank utility applied **after** the football-optimal baseline |
| **Post-match learning** | latest form snapshot | **GW1-to-now** match-by-match review of minutes, role, underlying vs returns, tactical changes, injury/rotation and signal vs noise |
| **External opinions** | analyst/model output directly blended into score | external analyst/model evidence is a **challenger**, not factual authority; disagreement is preserved instead of averaged away |
| **Personal data** | squad and recommendations stored beside public compute | **public factual/compute plane separated from private personal/decision plane** |
| **Delivery** | generate a report and stop | precompute/cache, semantic cross-section validation, fail-closed rendering, delivery state and visible report proof |
| **Performance** | recompute the whole pipeline | fingerprinted cache and partial-change reuse are designed to accelerate repeated decisions without shrinking the universe or weakening the model |

A useful example is `fpl-value-model`: its structural/value perspective is a useful challenger, but this engine intentionally goes beyond structural value into minutes probability, position-specific scoring distributions, tactics, exact squad decisions, multi-GW package optimization, Monte Carlo, mini-league context, post-match learning, privacy separation, and delivery governance.

## How it works

1. **Acquire facts**  
   V6 ingests and normalizes governed public sources, preserving freshness, lineage, fixture identity, and source health.

2. **Build player distributions**  
   V12 converts the factual plane into xMins / starting probability, position-specific event processes, underlying attacking and defensive evidence, tactical context, historical trajectory, uncertainty, and multi-GW projections.

3. **Scan the full universe**  
   Candidate discovery is not limited to the owned squad or a hand-picked watchlist. Position-aware scanning looks for material breakout, positive/negative regression, role gain/loss, minutes changes, fixture swings, defensive contribution value, and hidden-gem signals across the eligible player universe.

4. **Optimize exact decisions**  
   The decision core evaluates legal XI, bench ordering, captain/vice combinations, transfer routes, package utility, affordability, transfer costs, and future horizons without allowing presentation code to become a second optimizer.

5. **Model uncertainty**  
   Probability distributions and Monte Carlo are used where supportable so decisions can consider upside, downside, blank risk, haul probability, regret, correlation, and optionality rather than mean xPts alone.

6. **Apply manager context privately**  
   Current team state, budget, free transfers, selling values, chips, scenarios, exact routes, and mini-league context are combined only in the private decision/delivery plane.

7. **Render fail-closed reports**  
   Human-facing reports retain canonical section ownership, evidence lineage, degradation reasons, and cross-section validation before a result is treated as deliverable.

## Main report surfaces

Canonical DEEP reporting covers:

- current status and OUR15;
- decision delta and material developments;
- fixtures, rest, workload, travel and conditions;
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

## DEEP decision-content delivery barrier

A DEEP report is deliverable only when its governed analytics, canonical materialization, render, semantic validation, and final human-facing barrier agree. Unsupported fields degrade explicitly rather than being reconstructed by presentation code or replaced with manager-specific constants.

## PRICE human-facing delivery barrier

PRICE reporting uses the same fail-closed principle: factual price evidence, freshness, decision context, and WAIT / PREPARE / ACT interpretation must remain traceable to their governed producers. A price report cannot silently invent unavailable manager state or decision output.

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

Historical match evidence is kept observational until an authoritative model recomputation has occurred. Post-match rows, tactical interpretation, link-up dependencies, breakout/regression signals, and external challenges therefore remain distinguishable from facts and from model updates.

## Repository layout

```text
src/                production engine and analytics code
config/             runtime, source, schedule and model configuration
control/            control-plane and governed execution state
scripts/            operational and validation entry points
tests/              regression, semantic and architecture tests
test_support/       test fixtures and support utilities
docs/               architecture, methodology, governance and audit detail
.github/workflows/  CI, report execution and repository governance
```

Useful documentation:

- [Repository documentation sync policy](docs/REPOSITORY_DOCUMENTATION_SYNC_POLICY.md)
- [FPL Master Monitor schedule governance](docs/FPL_MASTER_MONITOR_TIME_SCHEDULE_GOVERNANCE.md)
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

- production `main` is `88a5c79dcfecd5032e6893dd422b620231b90f37`;
- V6 is the active factual plane;
- Canonical V12 is the active analytics and decision plane;
- the public/private decision-data boundary is active;
- full-universe, position-specific analytics, exact decision optimization, Monte Carlo, mini-league and governed report delivery are part of the active architecture;
- private manager-specific output is not intended to be published through the public repository.

For current runtime acceptance, workflow state, or source freshness, inspect the latest production evidence rather than treating this section as a live dashboard.

## Caveat

This is a decision-support system, not an oracle. FPL outcomes remain highly stochastic, player availability can change quickly, and some evidence can be delayed or unavailable. The engine therefore distinguishes factual authority, model output, uncertainty, challenger evidence, and final manager action instead of presenting every estimate as a fact.
