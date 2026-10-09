# FPL iphoenk Engine v3.39.0

> **Last runtime/documentation sync:** `2026-10-09T19:55:46+07:00`

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
If authenticated personal refresh fails but the exact-occurrence public V6 snapshot is published, report delivery may continue from the existing private last-good personal snapshot. The report preserves its original GW and timestamp and marks it stale or degraded; auth-only finance fields remain unavailable. Public-core publication or validation failures still block this fallback.

Injury and availability evidence is target-aware and claim-aware. Raw and normalized claims, polarity, training or appearance evidence, manager assessment, target GW or fixture, timestamps and evidence cutoff remain provenance fields; FPL 50%/75% flags are observations, never medical or start probabilities.

Captain distributions now have an optional calibrated goalkeeper event layer and one shared-world C/VC simulation of exactly 500,000 paths. Missing goalkeeper calibration remains explicitly unavailable; no captain winner or goalkeeper event probability is hardcoded.

## Reports

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
