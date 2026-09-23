# FPL iphoenk Engine — V6 Data Plane + Canonical V12 Decision Plane

> **Last runtime/documentation sync:** `2026-09-23T16:20:48+07:00`  
> **Synchronization basis:** active `main` architecture, `config/v6/schedule_policy.json`, `config/v6/source_activation.json`, and current V12 authority paths.  
> This timestamp describes when the human-readable repository documentation was last reconciled to the runtime/control-plane contract. Mutable live health still comes from `runtime-data-v6`.

> **CURRENT ACTIVE ARCHITECTURE**
>
> **V6** is the only factual production data plane.  
> **Canonical V12** is the model, probability, tactical, optimization, decision, comparator, and report plane.  
> **V3 / V4 / V5 are frozen legacy**: no production execution, no production fallback, no new features, and no scheduler authority.

This repository powers a governed personal Fantasy Premier League decision system. The active design deliberately separates **facts** from **models and decisions** so that factual acquisition can remain stable while V12 analytics evolve without creating duplicate authorities.

## DEEP human-facing report contract

Decision-critical COMPLETE sections are fail-closed to an **authoritative producer payload binding**. XI/C/VC, Watchlist20, governed Rise20/Fall20, package/MC frontier, mini-league, ALL15, and post-match surfaces carry producer identity plus payload fingerprint before rendering; presentation does not reconstruct or re-sort them. Exact Rise20/Fall20 preserve producer rank/direction/source and COMPLETE Watchlist20 preserves 5 GK / 5 DEF / 5 MID / 5 FWD.

The Canonical V12 DEEP report is a **23-section fail-closed human-facing contract**. The presentation may become easier to scan, but analytics and evidence must not be removed to shorten the report.

Occurrence-stage observability fingerprints normalize supported runtime `datetime` values to deterministic ISO-8601 strings before hashing. This keeps personal-evidence reconciliation auditable without changing evidence selection, football analytics, V6 facts, or decision semantics.

Required visible order:

```text
S01   Decision / Current Status
S02   OUR15
S03   Decision Delta
S04   Material Developments / Changes
S05   Fixtures / Rest / Conditions
S06   Formation / XI / Bench
S06B  Formation & Mini-League Strategy
S07   XI Battle
S08   Captain / Vice Captain
S09   Chip Strategy
S10   Actionable Price Radar
S11   Watchlist20
S12   RISE20
S13   FALL20
S14   Package Optimizer / Transfer Frontier
S14B  3-GW Squad Staging
S15   Evidence Quality
S15B  ICON+ Mini-League
S16   ALL15 Tactical / Probability Review
S16B  Post-Match Review GW1 → Now
S17   Source Health / Freshness / Lineage
S18   Action Board
S19   Final Judgement
```

`S06B` reuses the existing P1.7 football-optimal lineup evidence and P1.8 downstream mini-league evidence. It explicitly distinguishes the highest raw mean-xPts formation from the P1.7 distributional football choice and the supportable mini-league objective. It does **not** create a second lineup optimizer or allow ownership alone to override football evidence.

`S14B` is a non-binding three-GW roadmap. It can classify players/routes as `CORE / HOLD`, `WATCH`, `PREPARE OUT`, `PREPARE IN`, or `ACT CANDIDATE`, and must re-optimize when new injury, lineup, role, fixture, price, budget, or posterior evidence changes. Staging is never treated as a promise to execute a future transfer.

`S16B` makes the existing GW1→Now evidence visibly consumable: match-by-match minutes/start status, FPL output, xG/xA/xGI, shots/SOT, box involvement, chance creation, set-piece/penalty/defensive evidence when available, role/shape context, recency weighting, Bayesian state, genuine role-change versus noise, and link-up dependency. Material non-owned universe candidates use the same existing full-universe post-match materiality path.

DEEP acceptance is intentionally fail-closed across the Canonical catalog, semantic human-facing manifest, PRE_RENDER QA, actual visible-body POST_RENDER QA, and HUMAN_FACING QA. Missing `S06B`, `S14B`, or `S16B`, or silently removing any older DEEP backbone section, cannot pass. Exact15/exact20 completeness and anti-fabrication rules remain unchanged.

This contract does not move factual ownership out of V6. V6 acquisition, source adapters, publication, identity, scheduler, and factual schemas remain untouched by this report-plane enhancement.

## DEEP decision-content delivery barrier

DEEP success is now defined by the full delivery chain, not by section headings alone: **V6 facts → V12/P1.x analytics → Stage-3 payload → materialization → renderer → PRE_RENDER → POST_RENDER → HUMAN_FACING**. Report-plane consumes the existing canonical analytics and never creates a second xPts, package, Monte Carlo, lineup, or mini-league model.

CURRENT15 is occurrence-bound. Fresh valid authenticated or explicitly current user-confirmed evidence outranks stale AUTH_EXPIRED artifacts; previous-GW submitted picks are identity fallback only and cannot mint current selling values, bank, chips, FT, or hit economics. A proposed transfer never changes CURRENT15. If current ownership cannot be proved, identity may remain visibly STALE while unsupported private finance stays UNAVAILABLE.

Package execution is now explicitly **FULL_DIRECT + MATERIAL_FUNDED**. P1.2A exhaustively searches the complete legal one-transfer universe, P1.2B evaluates every direct route with the unchanged exact P1.7 owner, and the existing Stage-3 materiality surface selects a bounded set of already-evaluated direct legs. P1.2A then composes legal/affordable two-transfer packages from those material legs and P1.2B evaluates every composed funded package exactly before MC. This preserves real funding routes without sending the roughly million-scale global two-transfer cross-product through P1.7. The engine explicitly records that global two-transfer exhaustive coverage is **false**; no hidden player/package score or second decision authority is introduced.

Visible Section 14 must make the frontier decision-usable: explicit OUT → IN identities; HOLD comparator; selling/purchase values and bank before/after where supportable; affordability and FT/hit status; 1/2/3/5GW; raw/net gain; P(beat HOLD); MC path count and tails/quantiles; tactical/fixture effects; price optionality; mini-league utility; robustness/regret/reversal risk; and WAIT/PREPARE/ACT. A funded route is not allowed to disappear merely because the direct target is unaffordable.

Watchlist20, RISE20, FALL20, ALL15, post-match GW1→NOW, P1.7 XI/bench/C/VC, P1.8 mini-league evidence, and the Action Board are semantically validated against the visible body. HUMAN_FACING fails when supportable evidence is hidden, exact counts are falsely claimed, post-match detail collapses into season totals, mini-league evidence becomes decorative, Action Board loses its frontier link, or a legacy short narrative substitutes for the report. Fail-operational means field/scope-level degradation, never disappearance of available decision content.

## PRICE human-facing delivery barrier

Mandatory 05:30 PRICE is now a **12-section fail-operational structural contract**: Price Decision / Current Status, OUR15 Price & Value, Price Delta / Material Changes, Team-Needs Price Alert, Watchlist20, RISE20, FALL20, Package / Affordability / Transfer Economics, Mini-League Price Impact, Action Board, Source Health / Price-Cycle / Lineage, and Final Price Judgement. Data scopes may be stale/degraded/unavailable, but the structure may not collapse into a short narrative or status-only fallback.

CURRENT15 is resolved per occurrence from timestamped, GW-scoped evidence. A user screenshot/manual correction is evidence for its stated GW, not a permanent production override; newer applicable authenticated current-team evidence may supersede it. Recommendations and contemplated transfers never mutate ownership. If no current ownership can be proven, OUR15 remains visible with STALE/UNRESOLVED scope rather than fabricated ownership.

RISE20/FALL20 are materialized deterministically from healthy full-universe predictor inputs even when no pre-rendered exact20 artifact exists. Watchlist20 COMPLETE remains exactly 5 GK / 5 DEF / 5 MID / 5 FWD. Exact20 labels are forbidden when fewer than 20 valid rows exist, and no list is padded. ETA/status is mandatory for applicable price rows and is explicitly a MODEL/status surface unless it is a factual Official cycle timestamp.

Affordability uses authenticated selling value plus bank when available and remains separate from FT/HIT economics. A route may therefore be nominally affordable while FT/HIT economics is UNKNOWN. Price movement alone cannot force ACT; football decision quality stays upstream.

PRICE human-facing acceptance validates the **visible body**, including exact 12-section order, dynamic OUR15 exact15 when supportable, exact20 semantics, ETA/status, FACT/MODEL/INFERENCE separation, and the complete Action Board fields NOW / NEXT / TRIGGER TO ACT / LATEST SAFE DECISION POINT / COST OF WAITING / ABORT-REVERSAL. The integrated runner can execute PRICE without invoking Stage-3/Monte-Carlo; DEEP Stage-3 acceptance and its 500k-path requirement remain unchanged.


## V12 Stage 2 position-specific probabilistic engine

Report concurrency is versioned by production SHA so an obsolete in-flight controlled report from an older main commit cannot block acceptance of a newer merged Stage-3 implementation. Reports from the same production SHA remain serialized; cancel-in-progress remains false, so no due report is silently discarded.

Stage 3 MC performance repair: canonical Monte Carlo remains **500,000 correlated paths** with unchanged acceptance/convergence gates. Runtime now precomputes immutable Stage-2 fixture catalogs once per GW, replaces repeated path-sample clean-sheet calibration with deterministic Gauss-Hermite calibration of the same Poisson-lognormal zero-goal marginal, and processes larger bounded NumPy chunks. This changes execution efficiency, not V6 facts, Stage-1/Stage-2 authorities, 20/25/30/25, package economics, or report QA.

Stage 3 MC cache hardening: canonical package Monte Carlo now derives its common-random-number seed from the exact football projection + material lineup signature rather than the wall-clock report slot. The expensive deterministic simulation summary (500k-path metrics, pairwise outputs, sampling diagnostics and convergence evidence) is cached by exact model/code/config/projection/route/economics inputs and may be reused across occurrences; occurrence-specific run/evidence binding is always rebuilt. Cache restore/save happens before downstream acceptance, so a later report/auth gate failure cannot discard a valid simulation summary. A miss or any input/code/config change falls back to the unchanged canonical correlated simulation.

Stage 3 P1.2B runtime repair history: earlier controlled runs proved the hot path is exact P1.7 materialization inside `P1_2_PACKAGE_UTILITY`. Full direct search remains exhaustive and every direct route still receives exact P1.7. After funded two-transfer discovery expanded the global route set to roughly 1.5 million legal squads, controlled run `35819490932` proved brute-force exact P1.7 over the full two-transfer cross-product cannot finish inside the unchanged 60-minute report ceiling. Production therefore uses the governed **FULL_DIRECT + MATERIAL_FUNDED** execution scope: full direct P1.7 first, existing P1.7 materiality selection second, exact legal/affordable funded composition third, and exact P1.7 + canonical MC on every composed funded package. The engine does not claim exhaustive global two-transfer coverage. No V6 change, MC path reduction, timeout increase, second lineup model, or new decision score is introduced. Stage 3 remains **acceptance pending** until fresh controlled and natural DEEP evidence passes.

Stage 3 P1.7 hot-loop repair: follow-up controlled run `35703070607` proved that process-level parallelism alone is insufficient: all `1,965` package squads are unique and P1.2B still exhausted the unchanged 60-minute ceiling before P1.4 began. The existing P1.7 owner now vectorizes only the exact DNP-state × bench-appearance probability-mass accumulation while continuing to use the same canonical formation-legal resolver, all six bench permutations, the same captain/vice logic, and the complete P1.2A route set. Scalar-reference equivalence tests guard the probability and autosub outputs. No route pruning, model/owner change, Monte Carlo path reduction, V6 mutation, or QA relaxation is introduced. Stage 3 remains **acceptance pending** until controlled and natural DEEP proof passes.

Stage 3 P1.7 performance hardening: direct-route workers now prebuild immutable player decision surfaces once per material element × GW and reuse them across all squads, while legal-XI index masks are memoized by the 15-slot position signature. The existing exact decision-core cache is restored separately and is now persisted immediately after the integrated runner completes, before downstream Stage-3 acceptance, so a later auth/report gate failure cannot discard valid expensive P1.7 compute. These are execution-only changes: every route still uses the same P1.7 owner, all legal XI remain evaluated, model-evidence binding is rebuilt per occurrence, route search/MC/QA are unchanged, and any cache miss falls back to exact recomputation. The performance path also exposes cache hit/miss/write/corrupt-reject counts, legal-XI template reuse, player-surface build counts, and P1.7 wall/CPU timing; both P1.7 and deterministic MC caches use fail-operational save steps so valid completed compute is retained even if a later report acceptance step fails.

Stage 3 architecture-class latency hardening adds two execution-only layers without changing analytical ownership. First, P1.1/P1.3 full-universe output is restored from a fingerprinted derived snapshot only when the exact public/model inputs and source/config dependencies match; private CURRENT15/auth state is excluded from that key. Second, the P1.7 owner keeps its scalar implementation as the reference oracle but evaluates all 550 legal XI for one squad/GW through an exact NumPy batch kernel, while the canonical formation resolver, all six bench permutations, DNP/cameo semantics, reserve-GK rules, captain/vice ordering, and detailed selected-route materialization remain unchanged. Golden equivalence tests compare the batch kernel against the scalar oracle.

The controlled 15:48 DEEP baseline exposed an infrastructure-level cache defect specific to the owner-gated `issue_comment` trigger: GitHub granted read-only cache mode, so completed P1.7/MC caches could restore but could not be saved. The report job now explicitly requests cache write mode only after the existing repository-owner command gate and still checks out production `main` plus factual `runtime-data-v6`; no commenter-controlled ref is executed. Stage-2, P1.7 and MC cache contents remain non-authoritative and are validated by deterministic fingerprints before reuse.

Status: **STAGE 1 GREEN / STAGE 2 GREEN / STAGE 3 CODE MERGED — CONTROLLED + NATURAL DEEP ACCEPTANCE PENDING**.

Stage 2 starts from the exact GREEN Stage-1 head `d8a286a9428d8114125abb9093639de00c82103b` and preserves that commit as the immutable V6 behavior comparison baseline. V6 acquisition, source adapters, publisher, identity governance, scheduler, recovery transport, schedule policy, runtime-control, health semantics, schema, and `runtime-data-v6` are frozen and are not modified by Stage 2.

Final public-first live acceptance run `35671072769` (artifact `10671910220`, SHA-256 `0a952e39283f01c8f824731b0cf35f689287617265be0ac767e092cb27f30038`) is **GREEN**. It proves the Stage-2 engine **PASS** across all required analytics checks over all 667 projected Official players, Watchlist20 **COMPLETE**, full-universe/Watchlist single-chain lineage **PASS**, current squad evidence **PASS** via `PUBLIC_SUBMITTED_PICKS`, and public mini-league evidence **PASS**. Official FPL public submitted picks for entry `3462711` are HTTP 200 with 15/15 players; ICON+ League standings and GW5 manager picks are complete for 58/58 managers. Private `/me` remains `AUTH_EXPIRED` / HTTP 401, but is diagnostic only for Stage-2 acceptance and stays tracked separately in issue #640 for private-only facts. No V6 repair is included in PR #639.

The Canonical Stage-2 contract now requires explicit single-chain lineage from the same governed projection row through P1.1, P1.3 posterior, position engine, 20/25/30/25, and genuine 1/3/5GW distributions into full-universe and Watchlist20 rows. A mere subset relationship is not sufficient acceptance evidence.

Controlled Stage-3 runtime note: run `35693691787` reached the integrated analytics execution step but hit the previous 25-minute workflow ceiling before materialization. The report-runner workflow now allows up to 60 minutes and emits per-stage elapsed-time diagnostics; this changes neither V6 nor Stage-1/Stage-2/Stage-3 analytics mathematics or QA gates.

Stage-2 analytics work is confined to the V12 producer layer:

- dynamic position/role-specific matchup vector for goal, creation, attack, clean sheet, DefCon, save, set piece, aerial, transition, minutes, and bonus;
- Official FDR retained only as an external prior/sanity check, never as the final generic matchup number;
- tactical football-mechanism interactions that change event intensities without arbitrary final-point bonuses;
- empirically selected Poisson versus negative-binomial count models for save and defensive-contribution processes;
- settled-scoreline comparison of Poisson, Dixon-Coles, and bivariate Poisson, with the simplest calibrated family selected;
- stochastic conditional bonus/BPS layer, penalty and negative-event deductions, and posterior-predictive checks;
- position-specific complete discrete FPL point distributions;
- genuine per-GW and 1GW/3GW/5GW PMF aggregation rather than multiplying current xPts by horizon length;
- read-only consumption of already-normalized V6 Understat, Statmuse, and Rotowire evidence where exact identity joins are available;
- full-universe and Watchlist20 remain on the same canonical 20/25/30/25 lineage.

Stage 2 is **READY / GREEN** and remains frozen. Stage 3 is now implemented on PR #641 as a downstream-only completion layer. **Stage 3 is not yet GREEN**: controlled DEEP and subsequent natural scheduled DEEP acceptance are still mandatory.

Stage 3 reuses the existing owners rather than creating competing authorities: P1.2A performs structural package search over the same Stage-2 universe, P1.2B owns package utility, bounded future-FT rollout, transfer economics and WAIT/PREPARE/ACT closure, P1.4 owns correlated match-state Monte Carlo, P1.7 remains the XI/bench/captain/vice owner, and P1.8 remains a downstream mini-league overlay. The integrated runner now requires these producers to execute before a DEEP occurrence can pass.

Current private FPL authentication is not used to suppress public squad or mini-league analytics. When bank, selling price, free-transfer or chip facts are genuinely unavailable, Stage 3 preserves that factual gap, continues gross-football package/MC analysis, and **does not fabricate transfer economics or permit ACT**. Official FPL price-predictor likelihood classes are also not converted into invented rise/fall probabilities.

Durable evidence is recorded in `control/fpl_master_v12/FPL_MASTER_STAGE2_ANALYTICS_AUDIT.json`; it is evidence only and does not become a second methodology or factual authority.

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
| Package/search layer | `src/engines/v12_package_search.py` — **P1.2A structural search** |
| Package utility / sequential decision / transfer economics | `src/engines/v12_package_utility.py` — **P1.2B** |
| Correlated Monte Carlo | `src/engines/v12_monte_carlo.py` — **P1.4 match-state/shared-world MC** |
| XI / bench / captain / vice | `src/engines/v12_lineup_optimizer.py` — **P1.7** |
| Mini-league downstream overlay | `src/engines/v12_mini_league_overlay.py` — **P1.8** |
| Integrated DEEP execution and QA binding | `src/engines/v12_integrated_report_runner.py` |
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

A 21 Sep 2026 report-plane audit hardened mode/section conformance end to end. Runtime QA catalogs now match the Canonical V12 backbones for DEEP/FULL/DEADLINE/OVERLAP, MATCH 1–13, PRICE 1–12, POST-ALL-MATCH 1–13, and FINAL with the inserted GW LOCK PACKAGE. Visible parsing now supports two-digit mode sections and uses the current DEEP section mapping (XI/bench S06, Watchlist20 S11, RISE20 S12, FALL20 S13, ALL15 S16). Mode-specific count contracts prevent PRICE or POST-ALL-MATCH from inheriting unrelated Full-report counts, and visible OUR15/XI identity validation now runs only in modes whose contract actually requires those counts. Mini-league pre-render now binds the Canonical S15B surface rather than the obsolete S14B, and pre-delivery Watchlist/RISE/FALL validation now binds S11/S12/S13 rather than the prior S10/S11/S12 mapping. COMPLETE sections cannot silently materialize without human-facing content, post-render QA rejects status-only visible sections, degraded/unavailable sections retain a visible reason, and decision-bearing DEEP/FULL/Deadline/Final reports retain their existing action-board contract; PRICE additionally requires NOW / NEXT / TRIGGER TO ACT / LATEST SAFE DECISION POINT / COST OF WAITING / ABORT-REVERSAL.

The `official_price_predictor` artifact represents the verified 2026/27 **Official FPL Price Change Predictor**. Current price and confirmed overnight price changes remain Official FPL FACT. Predictor current progress, predicted progress, likelihood/status and >100% threshold guidance are Official FPL predictor/model outputs and remain guidance rather than guaranteed outcomes. V12 may add decision-layer interpretation such as affordability impact or WAIT/PREPARE/ACT, but it must not relabel the official predictor as third-party or merely V6-derived.


Mandatory DEEP and PRICE occurrences now have explicit integrated execution paths rather than relying on report prose to opportunistically call disconnected libraries. For DEEP, the non-scheduled `V12 integrated report runner` keeps the existing same-occurrence `full_master` binding and Stage-3 path. For PRICE, the same runner uses the dedicated V12 PRICE delivery barrier to bind current factual/model evidence, dynamically resolve ownership, materialize exact lists when supportable, render all 12 Canonical sections and validate the actual visible body. Both modes emit occurrence-bound `report_bundle.json`, `report_body.md` and `execution_proof.json`. It creates no scheduler, never publishes decisions into `runtime-data-v6`, and may not import/execute V3/V4/V5 or legacy optimizer/oracle paths. FPL Master Monitor V12 remains the only recurring scheduler and consumes the applicable bundle for mandatory delivery. If the runner is blocked, the due report remains fail-operational but must keep every Canonical section and expose the exact blocked stage instead of collapsing into a short manual summary.

The integrated runner now distinguishes the Stage 1 canonical-universe boundary from Stage 2 package execution. When the V12-native PROVEN/HISTORICAL, TACTICAL/ROLE, CURRENT UNDERLYING and FIXTURE/SECURITY producers materialize a complete 20/25/30/25 universe, Stage 1 may mark that universe PASS. Section 14 remains truthfully DEGRADED until Stage 2 package/frontier and material Monte Carlo are actually executed, and must carry that explicit reason. No ad-hoc percentile score, hidden package execution, or legacy runtime fallback is permitted.


Integrated DEEP execution is fail-operational at the **analytics-stage** level. A P1.1/P1.3/P1.6/P1.7/package/Monte-Carlo stage failure must be preserved in the occurrence stage ledger and degrade only dependent sections; it must not terminate before Canonical materialization. When the factual occurrence and OUR15 remain bound, the runner still emits `report_bundle.json`, `report_body.md`, and `execution_proof.json`, executes PRE_RENDER_QA / POST_RENDER_QA / HUMAN_FACING_QA, and labels unsupported model outputs NOT_RUN/DEGRADED rather than substituting manual prose or fabricated numbers. Only catastrophic inability to bind the governed occurrence itself may prevent a runner bundle; the recurring scheduler still owes the due report with the exact blocker visible.

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

## Stage 1 analytics completion status

**Stage 1 is CLOSED / GREEN. Stage 2 is ready to start but has not started.**

Final controlled acceptance:

- integrated DEEP workflow run: `35659879299`;
- artifact: `v12-report-DEEP-35659879299` (artifact id `10667026143`);
- report slot: `2026-09-22T05:00:00+07:00`;
- accepted `main`: `e20313c497d27e0cc9e800ab9de6280a7781510c`;
- accepted `runtime-data-v6`: `b851d72f7183395c8d632e8d8f14e6c9282b17f0`;
- same-occurrence `full_master` prefetch id:
  `22098ecb-4c96-4924-bc5e-2cf96691f7c6`;
- runner: **PASS**;
- canonical catalog: **PASS**;
- PRE_RENDER: **PASS**;
- POST_RENDER: **PASS**;
- HUMAN_FACING: **PASS**.

The accepted factual history is normalized **Official FPL finalized event-live**
history for GW1→GW5 with 3,191 normalized player-match rows, 3,191 exact
element/fixture/opponent identities, no missing finished GW, exact Official
fixture resolution, and no fabricated DGW aggregate splitting.

Stage 1 now includes and has acceptance proof for:

- exact root-cause repair for controlled run `35597594711`;
- P1.3-owned horizons with no runner-private shorter horizon;
- finalized Official FPL GW1→current match-by-match facts;
- opponent-adjusted historical recency with venue-specific strength;
- recency × opponent × regime weighting without hard reset;
- Bayesian change-point evidence and `P(role stable)`;
- empirical-Bayes league → position → factual-role-if-available → team
  leave-one-player-out priors feeding the existing P1.3 owner;
- credible intervals and sample exposure;
- target-specific distribution diagnostics/selection;
- P1.1 six-state minutes:
  `START_FULL / START_SUBBED / EARLY_SUB / CAMEO / LATE_CAMEO / DNP`;
- expanding-window GW walk-forward validation with no future leakage;
- exact Canonical 20/25/30/25 full-universe materialization;
- full OUR15, XI/bench, Watchlist20, price radar and mini-league visible
  acceptance;
- actual visible DEEP render validation.

Stage 2 boundaries remain explicit. `P1_2_PACKAGE_UTILITY` and material
`P1_4_MONTE_CARLO` are intentionally `NOT_RUN` in the Stage 1 acceptance;
they were not fabricated or silently executed. Unsupported optional factual
features remain explicit `UNAVAILABLE`, never silently zero-filled.

### Controlled Stage 1 runtime recovery

The existing V6 `manual_recovery` mode remains available as a bounded,
owner-only, non-natural recovery transport through issue #431. It is never
scheduler proof, never completes an operational/scheduled slot, never changes
the single ChatGPT scheduler authority, and never creates a second recurring
acquisition path. It may bypass only ordinary same-slot polling cadence while
verification and request-budget gates remain enforced.



### P1.2B/P1.7 bounded runtime repair

Controlled DEEP run `35709678609` proved that PR #646 and PR #647 were
still insufficient: all 2,043 exact P1.2A routes / 2,043 unique squads entered
exact P1.2B P1.7 materialization and the job was cancelled after more than
3,527 seconds in P1.2B, before P1.4 began.

A fail-closed pre-repair profile measured one representative exact squad across
five GWs at 6.950154 seconds. Of that, compact route evaluation consumed
6.848297 seconds; exact bench-order optimization consumed 5.964454 seconds and
exact compact C/VC selection 0.769681 seconds. Player-surface construction,
legal-XI enumeration, full selected/best-alternative materialization and model
evidence were not the primary bottleneck.

The bounded repair keeps all 550 legal XI per GW, all six outfield bench
permutations, the canonical autosub resolver, exact ordered captain/vice
semantics, deterministic tie-breaking, all 2,043 package routes and all five
GW evaluations. It reuses only mathematically invariant resolver state
matrices, batches the six exact compact bench permutations, materializes only
the compact winner payload during route ranking, and reuses one canonical
15-player C/VC rank table per squad/GW. Full selected and best-alternative
P1.7 routes are still materialized through the canonical owner.

The corresponding post-repair profile measured 1.040479 seconds for the same
five-GW representative workload, a 6.68x end-to-end speedup; warm per-GW
runtime was about 0.164 seconds versus about 1.33 seconds before repair. The
P1.2B execution proof now records wall time, per-unique-squad and per-GW timing
distributions, worker-utilization estimate and a coordination/serialization
upper bound. No route pruning, sampling, heuristic lineup, timeout increase,
Monte Carlo reduction, alternate decision owner, V6 mutation or QA relaxation
is introduced.

Stage 1 remains GREEN. Stage 2 remains GREEN. Stage 3 remains
code-merged / acceptance pending until a fresh controlled acceptance and the
required genuine natural DEEP acceptance pass.



### Mandatory report time-budget continuity

Natural 21:30 on 22 Sep 2026 exposed a report-plane edge case: the exact
same-slot core run was correctly bound and not duplicated, but remained queued
until the scheduler execution budget expired. The prior scheduler hotfix then
rendered a status-only `TIME_BUDGET_EXHAUSTED` blocker instead of the mandatory
DEEP body, even though Canonical V12 already requires due reports to remain
fail-operational.

Canonical V12 now distinguishes core terminal acceptance from visible delivery.
If an exact bound core run remains queued/in-progress when the platform budget
expires, the run identity stays fixed and no second core attempt is allowed,
but a mandatory DEEP/PRICE/Deadline/Final must still render the full Canonical
structure from the freshest valid evidence ladder. Current-core-dependent
fields are marked `BOUND_IN_PROGRESS_TIME_BUDGET_EXHAUSTED` / `NOT_RUN`
rather than fabricated. This delivery escape does not count as natural
Stage-3 acceptance and does not convert a non-terminal core into success or
failure. V6 acquisition, cadence, model math, QA, route search, Monte Carlo and
decision ownership are unchanged.


### Exact P1.7 decision-core reuse

Mandatory DEEP latency is now allowed to reuse only the expensive canonical
P1.7 decision core when its complete deterministic fingerprint is identical.
The key includes the normalized 15-player decision surfaces, lineup config,
ruleset, Canonical revision and exact optimizer source hash. Any change forces a
cold exact recomputation. The cache never owns decisions, never stores outputs
in V6, never prunes routes, never approximates XI/bench/C/VC, and
`optimize_lineup` still rebuilds the current model-evidence envelope after a
cache hit.

The integrated V12 report workflow restores/saves this non-authoritative
execution cache between runs. This targets repeated mandatory reports with
unchanged numerical P1.7 inputs so they do not repeat the full 550-XI exact
search for every identical squad/GW state.
