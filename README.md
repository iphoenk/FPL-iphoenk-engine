# FPL iphoenk Engine v3.39.0

> **Last runtime/documentation sync:** `2026-10-10T21:37:00+07:00`

A governed Fantasy Premier League decision-support engine combining public football facts, probabilistic modelling, full-universe discovery, squad optimisation, Monte Carlo, mini-league context, and private report delivery.

> **V6 establishes factual truth. Canonical V12 interprets those facts for FPL decisions. Manager-specific state and reports remain private.**

## Core architecture

`Official/Public Data → V6 Facts → Canonical V12 → Optimisation → WAIT / PREPARE / ACT → Reports`

- **V6 factual plane:** governed facts, freshness, fixtures, prices, and source evidence.
- **Canonical V12:** xMins, probability, tactics, full-universe scanning, optimisation, Monte Carlo, and decision semantics.
- **Private delivery:** manager-specific squad state, scenarios, mini-league context, decisions, and full reports.

Canonical FPL entry identity is repository-configured. Authenticated personal acquisition is an optional enrichment for private/current finance facts; when auth is intentionally unavailable, governed Official FPL submitted-picks or explicit owner evidence may still support Current15 identity, while auth-only finance fields remain unavailable.

Stage3 upstream failure diagnostics are documented in [docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md](docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md); blocked Stage3 remains degraded and privacy-safe.

When Stage3 is blocked upstream, the report remains explicitly `BLOCKED_UPSTREAM` and records only bounded allowlisted guard predicates plus Monte Carlo path/convergence facts. This diagnostic path never claims Stage3 execution or relaxes the 500,000-path and convergence gates.
Optional precompute, warm-worker, and freeze telemetry is reported with explicit `NOT_APPLICABLE`, `OPTIONAL_UNAVAILABLE`, `REQUIRED_PASS`, or `REQUIRED_FAIL` semantics; missing optional telemetry never becomes a delivery failure or a false PASS.

Stage2 public acceptance binds to the latest occurrence-bound `full_master` prefetch. An ad-hoc personal prefetch cannot mask the public manager-picks evidence required for acceptance.
The V6 private publisher validates the freshly isolated `private-reports/personal/current_team.json` after private-boundary splitting, not the previously saved snapshot. The saved file is used only for a strictly degraded fallback, and logs expose only the safe refresh auth-state classification.
If authenticated personal refresh fails but the exact-occurrence public V6 snapshot is published, report delivery may continue from the existing private last-good personal snapshot. The expired-auth fallback validates age from that saved snapshot, never from the fresh failed-attempt artifact. The report preserves its original GW and timestamp and marks it stale or degraded; auth-only finance fields remain unavailable. Public-core publication or validation failures still block this fallback.

Injury and availability evidence is target-aware and claim-aware. Raw and normalized claims, polarity, training or appearance evidence, manager assessment, target GW or fixture, timestamps and evidence cutoff remain provenance fields; FPL 50%/75% flags are observations, never medical or start probabilities.

Captain distributions now have an optional calibrated goalkeeper event layer and one shared-world C/VC simulation of exactly 500,000 paths. Missing goalkeeper calibration remains explicitly unavailable; no captain winner or goalkeeper event probability is hardcoded.

## Reports

S06 mobile pitch displays the entire already-calculated **CURRENT15** P1.7 formation frontier (including 3-4-3 where a legal canonical row exists), not only two leading routes. Formation xPts remain unchanged. Missing rows are explicitly labelled unavailable. DCL→Barry and DCL→Gonzalo are roster-transfer scenarios **not computed** by the S06 presentation change; each still requires validated finance, legality, canonical lineup optimization and full 500K MC before any recommendation. GW6 team news from 20 clubs and 113 player signals is ingested as bounded secondary evidence via the existing P1.1 adapter. V6 facts and P1.7 decision ownership are unchanged.

**DEEP** is the full planning report, **PRICE** handles price/timing, **DEADLINE / FINAL** is the final pre-deadline checkpoint, and **MATCH** covers post-deadline and matchday monitoring.

Primary schedule: **DEEP 04:30 / 12:30 / 21:30 Asia/Jakarta** and **PRICE 23:30 Europe/London**. Deadline and Matchday use governed checkpoints. T-24 through T-3 bind to the official deadline and emit one occurrence-bound DEEP report; T-2 through T-5 remain delta/final overlays.
ChatGPT automation `FPL Master Monitor V12` is the sole recurring scheduler, running every HH:30 Asia/Jakarta. Only due DEEP/PRICE checkpoints post an occurrence-bound `/fpl-master-tick` comment to issue #431; non-due hourly ticks are silent. The GitHub issue-comment orchestrator starts governed prefetch, V12 and private report publication. No independent production GitHub cron, issue-title upkeep or alternate scheduler is authoritative. PRICE remains bound to 23:30 Europe/London (DST-safe).

Occurrence commands are exact-time only: future report slots are rejected, and private serving state created before its claimed occurrence cannot satisfy idempotent reuse.

S09 chip availability is fail-closed: a missing/`UNAVAILABLE` chip ledger is **not** evidence that Bench Boost, Wildcard, Triple Captain or Free Hit remains usable. Only explicitly verified `AVAILABLE`/`UNUSED` entries appear as remaining; incomplete states are labeled unresolved without guessing. This affects presentation only, not the canonical chip decision or authenticated source authority.

S18 action board keeps all six canonical decision axes and projects the best-alternative route as a bounded, two-column decision table (route, outbound/inbound names, executable status, hit, 1/3/5GW net deltas, P(beats HOLD), robustness). Mini-league evidence (football EV priority and rank-gain utility) remains visible in a small labeled subsection. The full optimizer route stays intact in its original canonical evidence; no nested matchup/route dictionaries are dumped in the mobile-visible S18 presentation. Missing values remain UNAVAILABLE; this is presentation-only and does not change ACT authority or Monte Carlo.

The S18 production human-facing presentation lock now derives an **exact** one-table route contract and optional second mini-league evidence table from the *bound canonical route fields*. It verifies column order, 13 mandatory route labels, matching mini-league row labels, and exact row/table counts, rejecting missing or unexpected tables instead of weakening validation. This closes the `S18_RENDERED_TABLE_COUNT` production failure observed during controlled DEEP at 19:45 WIB on 9 Oct 2026. No change to route mathematics or MC.

S08 human-facing QA is state-aware: `LOCK` requires visible `Current C:` / `Current VC:` labels, while `PREPARE` and other non-locked states require `Current C baseline:` / `Current VC baseline:`. This preserves explicit provisional captain identity without weakening rendered-content acceptance.

## Captain risk and mini-league review

For a CLOSE football frontier, a goalkeeper captain with weaker 10+ haul
probability and Q90 than an equally secure attacking alternative is marked
PREPARE rather than falsely LOCKed. A review pair is shown, never automatically
executed. LEAGUE / RIVALS / COMPETITIVE captain share and EO, denominator
coverage, current rank/gaps and PROTECT/BALANCED/ATTACK posture are reported
as observed historical mini-league context; they are not target-GW forecasts
or a substitute for correlated captain/vice Monte Carlo. Missing scopes and
unverified GK clean-sheet/conceded/saves/bonus/penalty-save calibration remain
explicitly unavailable. S08, S18 and S19 must share the canonical C/VC.

## DEEP decision-content delivery barrier

DEEP is occurrence-bound, provenance-aware, privacy-safe, and may degrade explicitly when evidence is unavailable rather than inventing data. Its visible renderer is presentation-lock driven: the header carries report identity only, S04 owns material news/developments, S14 is bounded to optimizer/search evidence, S15 owns decision-evidence quality, S17 owns technical health/freshness/lineage, and mini-league context uses the dynamic Competitive Window.

## PRICE human-facing delivery barrier

PRICE follows the same factual/provenance boundary and never invents unavailable manager state or decision output.

## Captaincy

Captaincy is now distribution-first: S08 compares legal selected-XI candidates using canonical P1.3B one-GW return distributions, treats Phaul as the existing P(points ≥ 10) tail rather than a second weighted signal, and classifies the football frontier as CLEAR, CLOSE, or FRAGILE. Mini-league LEAGUE/Competitive Window exposure may break only a CLOSE football decision when standing-gap context is complete; EO never overrides a clear football edge, and nonnumeric competitive EO is treated as unavailable rather than coerced. S15B is evidence-only, while S08, S18, and S19 consume one canonical C/VC decision. Cross-player joint correlation and candidate-specific relative-points captain MC are not currently fabricated when unavailable.

## Governance

The engine scans the **full eligible FPL universe**, separates facts from inference, preserves uncertainty, and keeps manager-specific state private.

**Current-state authority** comes from governed CI/runtime evidence and `runtime-data/data/runtime_manifest.json`; this README and `MASTER_TASK_LIST_V3.md` are only a **human-readable projection**.

Detailed methodology, formulas, evidence weighting, privacy, scheduler, delivery architecture, presentation contracts, P4/P6, cache behaviour, and performance governance live under `docs/v12/`.

Delivery authority: `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`  
Schedule authority: `config/delivery/v12_delivery_schedule.json`

> **Caveat:** this is a decision-support system, not an oracle. FPL outcomes remain stochastic and source evidence can change quickly.


## DEEP captain presentation integrity (9 October 2026)

The canonical captain frontier remains distribution-first and position-neutral. When the goalkeeper captain is classified CLOSE and the decision is PREPARE, the DEEP S08 and S19 surfaces label the named C/VC as a **provisional baseline**, not a locked or executable captain recommendation. The existing attacking review challenger (when available) is explicitly displayed as an advisory candidate, with the goalkeeper-event calibration and shared-world relative-points evidence still required before lock. A genuinely LOCKed captain retains the canonical display contract. S08, S18 and S19 must remain consistent. This change does not alter P1.7, MC 500k, squad optimisation, or mini-league exposure mathematics.

## S19 cross-position captain decision visibility (9 October 2026)

S19 FINAL JUDGEMENT now renders the canonical S08 captain frontier for all
eligible selected-XI positions (GK/DEF/MID/FWD), especially CLOSE decisions.
The bounded comparison shows xPts, P(blank), P(10+), Q90, P(start), xMins
and evidence completeness without new weights, invented probabilities,
arbitrary xPts near-tie thresholds, or a second captain owner. Competitive
Window posture and tie-break status are explicitly identified as secondary
to canonical football distributions. LOCK means a canonical resolved C/VC;
PREPARE labels the displayed C/VC as provisional, not executable.
The S19 human-facing gate rejects missing or reordered CLOSE-frontier
evidence relative to S08. This change does not touch P1.7, MC 500k,
universe/routes, S16B, scheduler, private publisher, or PR #809.

## S19 seven-layer captain acceptance boundary (9 October 2026)

The S19 judgement now exposes the owner-approved seven evidence layers:
canonical xPts; PMF-derived P(10+)/P(15+), Q75/Q90 and multiple-return
availability; P(blank)/P(DNP)/P(start)/xMins; variance and head-to-head
with explicit cross-player dependence assumptions; Competitive Window plus
actual relative-rank simulation status; C/VC fallback plus joint-simulation
and vice-activation status; and explicit evidence-confidence status.
Unimplemented event-joint multiple returns, covariance, or rank MC
must show UNAVAILABLE. A canonical LOCK is not automatically proof that
all seven layers have complete evidence. S19 must state PARTIAL_EVIDENCE
where those inputs remain unresolved. No new CaptainScore, EO-derived
points, position preference, substitute optimizer, or fabricated MC.

## CLOSE captain production LOCK evidence guard (9 October 2026)

A CLOSE football frontier may preserve or recommend an eligible, owned
C/VC provisionally, but observed captain/EO percentages must not certify
the pair as LOCK. The existing canonical captain reconciler now requires
a valid shared-world C/VC simulation with exactly 500,000 paths and an
explicit convergence PASS; an exposure-driven switch also requires
simulated mini-league rank consequences. Until these checks pass the state
is PREPARE, and S08/S18/S19 must label the selected pair provisional.
This does not forbid goalkeeper captaincy: a robustly CLEAR GK can still
LOCK. No new CaptainScore, changed P1.7, pseudo-consensus or fabricated
relative-points estimates are introduced.

## Seven-layer captain permanent CI regression gate (9 October 2026)

The required V12 verification suite explicitly includes goalkeeper-tail,
cross-position seven-layer visible-report, and distributional captain
frontier governance tests. It rejects false CLOSE LOCK when real joint
C/VC confidence or mini-league rank evidence is unavailable, preserves
valid CLEAR goalkeeper captains, and checks S08/S19 consistency.


**GW6 what-if transfer / formation matrix (10 Oct 2026):** `python -m src.engines.v12_transfer_matrix --output artifacts/gw6_transfer_matrix.json` enumerates 42 roster combinations, including **Konsa→Lewis Hall** with/without Tavernier→Saka and Bruno→Mbeumo, over all eight P1.7 legal formations (**336 rows**); previous Davis/Castagne/Mykolenko alternatives remain for comparison. Hall's Newcastle identity and £5.3m price come from public V6 predictor (addendum `config/intelligence/gw6_hall_candidate.json`). Hall frees an Arsenal slot when Saka enters. With illustrative stale-value £0.2m bank, Bruno→Mbeumo + Tavernier→Saka + Konsa→Hall is indicatively £0.2m short; DCL→Barry changes that to +£0.1m, whereas DCL→Gonzalo changes it to -£0.3m. Private bank, selling price, free transfers and hits are **not authenticated**. Only the no-transfer baseline has verified 500K P1.4 MC. All what-ifs require distinct canonical P1.7 and 500K MC before action. No CURRENT15, P1.7, MC engine, scheduler, or private delivery mutation.


**GW6 P1.4 3-4-3 MC closure (10 Oct 2026):** The private DEEP what-if step now materializes the exact P1.7 3-4-3 winner per GW with the unchanged canonical bench-order and captain/vice evaluator. Correlated P1.4 runs 500,000 paired worlds for optimized HOLD, DCL→Barry, DCL→Gonzalo and three explicitly fixed 3-4-3 lineups; captain challenger remains optional. Output is a private `gw6-forward-mc.json` attached to the DEEP occurrence, not a bank/FT/transfer authorization. Tests exercise route-specific outcomes and fail-closed formation completeness. Personal finance and hits remain unavailable pending authenticated V6 evidence.


Public Official FPL submitted picks, live data, and mini-league evidence are independent from authenticated personal enrichment. When private authentication is expired, public MATCH delivery continues with explicit unavailable finance fields; authenticated bank, free transfers, purchase prices, and selling values are never derived from public data.

### P0 MATCH public-first recovery (10 October 2026)

MATCH reports use immutable current-GW Official FPL submitted picks (15/15) and current Official FPL live player points; an expired private credential cannot override the locked team. The governed V6 exact match-mode prefetch binds ICON+ league 9477 manager and picks coverage. MATCH1..MATCH13 have their own delivery catalog rather than DEEP sections. The public bridge emits truthful READY_DEGRADED and withholds provisional live rank or net score until transfer hits, automatic substitutions and league tie-break rules are verified. Authenticated bank, free transfers, buying and selling prices remain unavailable when FPL auth is expired. This P0 continuity repair is not evidence of FULL GREEN until CI, live acceptance and private report receipt are verified.
