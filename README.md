# FPL iphoenk Engine v3.39.0

> **Last runtime/documentation sync:** `2026-10-11T16:27:00+07:00`

A governed Fantasy Premier League decision-support engine combining public football facts, probabilistic modelling, full-universe discovery, squad optimisation, Monte Carlo, mini-league context, and private report delivery.

> **V6 establishes factual truth. Canonical V12 interprets those facts for FPL decisions. Manager-specific state and reports remain private.**

- **P0 Stage3/OUR15 provenance (11 Oct 2026):** public submitted picks are an explicitly stale, non-financial identity fallback, never editable authenticated CURRENT15. Exact team/GW and live /me + /my-team lineage must be bound before private finance is authoritative; Stage3 only accepts S02 degraded after cross-checking 15 distinct submitted IDs, position counts, XI/bench, C/VC, Official provenance and occurrence timestamp. Wrong identity/fixture facts still fail closed. Natural, native visual and full-green production remain independent acceptance gates. See [Stage3 diagnostics](docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md).

- **GW7 owner what-if MC:** PR #963 tests four paired 500K routes (HOLD, Mbeumo only with assumed 1 FT, Mbeumo + Palmer with -4, and Mbeumo + Saka with -4), using P1.7/P1.4 unchanged, and keeping the full result private. Future mini-league top-3 probability is not modelled; GW6 rival ownership is descriptive, not a probabilistic rank claim.


- **Protected hourly OIDC upkeep (11 Oct 2026, PR #975):** the existing genuine ChatGPT hourly core issues-edit event now has a private downstream maintenance job. It reads encrypted access expiry on every eligible real natural occurrence, reuses a healthy token, and only attempts one CAS-guarded refresh within 15 minutes of expiry. It verifies /me and /my-team/3462711 after rotation and retains report-prefetch's 90-second default. The protected emergency pause applies to both workers; ambiguous rotation remains IN_FLIGHT and requires owner action. This adds no scheduler and never blocks Official public acquisition. CI/merge are not proof that the next real near-expiry grant or native delivery succeeded.\n\n- **OIDC private natural V6 activation (11 Oct 2026):** after real owner-controlled refresh and #19 independent reuse (HTTP 200, version 3 unchanged), protected private V6 prefetch defaults to rotating encrypted OIDC; public collection stays independent. Protected `FPL_PRIVATE_AUTO_REFRESH_PAUSED=true` is an emergency stop. Verified finance-only publication requires bank, FT or explicit unlimited, and 15/15 prices. Stale fallback nulls all unauthenticated economics. Natural V12 and next-expiry rotation/delivery remain separate acceptance gates. See [OIDC security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC second-worker reuse-only proof (11 Oct 2026):** the protected V6 auth probe offers owner-only `REUSE_ONLY` (new runner, encrypted store read, current saved access token only; GET /me and /my-team; never refresh or write ciphertext). Green requires correct identity and no store version change; expired tokens fail safely. See [security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC controlled-first-grant gate (11 Oct 2026):** after encrypted iPhone enrollment, owner may choose `CONTROLLED_ONCE` in existing V6 auth probe to test a single official refresh without enabling rotating auth for natural jobs. Possible Safari session collision must be understood; live grant, persistent rotation, /me identity, subsequent reuse and natural V12 delivery are separately verified. Restored hard cross-CPU governance proof from direct 3-model PASS run 38101198457 (not waived). [Security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC rotating auth P0 (11 Oct 2026):** official discovery verified; initial fail-closed rotation core merged in #959. Follow-on opt-in V6 integration adds encrypted private Git CAS secret state and owner-only GitHub Actions enrollment, with key protected as an environment secret. This does not enable real refresh until the owner supplies credentials and explicitly verifies the client policy. See [OIDC security and iPhone steps](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **Authenticated FT recovery (11 Oct 2026):** V6 private my-team normalizes remaining free transfers from an explicit field or, when absent, from verified `transfers.limit` minus `transfers.made` with bounded integers and explicit provenance. `limit=null` stays UNLIMITED, incomplete evidence stays NOT_SUPPORTED. Never derive private finance from public picks; bearer auto-renewal is a separate unresolved credential-lifecycle task.

- **P0 governance sharding (11 Oct 2026):** preserves the original 49 required V12 test files and 1,345 parameterized node IDs with deterministic, disjoint fail-closed test shards. Exactness-heavy P1.7 reference tests are isolated without changing model mathematics; each job captures per-test durations and CPU identity. The existing `v12-required-verify` branch-protection check remains a mandatory aggregator. PR and postmerge push evidence must both be GREEN before production governance is declared recovered.

## Core architecture

`Official/Public Data → V6 Facts → Canonical V12 → Optimisation → WAIT / PREPARE / ACT → Reports`

- **V6 factual plane:** governed facts, freshness, fixtures, prices, and source evidence.
- **Canonical V12:** xMins, probability, tactics, full-universe scanning, optimisation, Monte Carlo, and decision semantics.
- **Private delivery:** manager-specific squad state, scenarios, mini-league context, decisions, and full reports.

A guarded private FPL auth diagnostic is available via the owner-only `/fpl-auth-probe` command on issue #431. It checks `/me`, the configured entry identity, then `/my-team`, and prints only redacted HTTP statuses and availability flags. An unverified JWT expiry claim does not prove accepted authorization. No credential, private payload, or finance amount is logged or published; `AUTH_AVAILABLE` requires verified HTTP 200 for both endpoints and 15 distinct players. Public MATCH remains independent of this probe.

Canonical FPL entry identity is repository-configured. Authenticated personal acquisition is an optional enrichment for private/current finance facts; when auth is intentionally unavailable, governed Official FPL submitted-picks or explicit owner evidence may still support Current15 identity, while auth-only finance fields remain unavailable.

Stage3 upstream failure diagnostics are documented in [docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md](docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md); blocked Stage3 remains degraded and privacy-safe.

When Stage3 is blocked upstream, the report remains explicitly `BLOCKED_UPSTREAM` and records only bounded allowlisted guard predicates plus Monte Carlo path/convergence facts. This diagnostic path never claims Stage3 execution or relaxes the 500,000-path and convergence gates.
Optional precompute, warm-worker, and freeze telemetry is reported with explicit `NOT_APPLICABLE`, `OPTIONAL_UNAVAILABLE`, `REQUIRED_PASS`, or `REQUIRED_FAIL` semantics; missing optional telemetry never becomes a delivery failure or a false PASS.

Stage2 public acceptance binds to the latest occurrence-bound `full_master` prefetch. An ad-hoc personal prefetch cannot mask the public manager-picks evidence required for acceptance.
The V6 private publisher validates the freshly isolated `private-reports/personal/current_team.json` after private-boundary splitting, not the previously saved snapshot. The saved file is used only for a strictly degraded fallback, and logs expose only the safe refresh auth-state classification.
If authenticated personal refresh fails but the exact-occurrence public V6 snapshot is published, report delivery may continue from the existing private last-good personal snapshot. The expired-auth fallback validates age from that saved snapshot, never from the fresh failed-attempt artifact. The report preserves its original GW and timestamp and marks it stale or degraded; auth-only finance fields remain unavailable. Public-core publication or validation failures still block this fallback.

Injury and availability evidence is target-aware and claim-aware. Raw and normalized claims, polarity, training or appearance evidence, manager assessment, target GW or fixture, timestamps and evidence cutoff remain provenance fields; FPL 50%/75% flags are observations, never medical or start probabilities.

Captain distributions now have an optional calibrated goalkeeper event layer and one shared-world C/VC simulation of exactly 500,000 paths. Missing goalkeeper calibration remains explicitly unavailable; no captain winner or goalkeeper event probability is hardcoded.


### Stage C full-universe scanner (11 Oct 2026)

Stage C is enabled for canonical DEEP candidate discovery by the `feature_default_enabled` configuration default; `V12_STAGEC_SCANNER_ENABLED=0` is the deliberate emergency override. The Stage A multiwindow / Stage B shadow / Stage C pipeline scans the full projection input, reconciles unique projection IDs against Official FPL `bootstrap.elements`, and records the Official denominator, eligible denominator, missing/duplicate/unrecognized IDs, position coverage and screening reason codes. Missing or partial evidence is reported as `DEGRADED` rather than claiming full universe coverage. The scanner contributes bounded, provenance-aware candidate intelligence under S04 and route context, not a second Watchlist20 score, transfer authority, P1.7, or Monte Carlo engine. An actual production PASS still requires an occurrence-bound DEEP execution proof, 20-row S11, canonical 500K Monte Carlo, private delivery receipt and matching latest pointer; passing CI is not that proof.

### S05 planning-GW display scope (11 Oct 2026)

Verified 12:27 WIB production S05 completed and passed Stage3, but the visible fixture table included all 380 season fixtures rather than the ten GW7 matches. The integrated report now passes `planning_gw` into the **display-only** fixture projection; only fixtures whose Official FPL `event` exactly matches the planning GW are rendered. Full-season fixture inputs remain available for workload mathematics, source evidence and historical context. An existing regression test now verifies that all ten target-GW cards survive, unrelated-GW/unknown-event rows do not leak, and another GW maps only its own fixtures. The strict conditional S05 table rows/columns QA remains active.

### S05 exact rendered-table verification (11 Oct 2026)

The 49 required V12 files now contain 1,345 parameterized node IDs (five additional S05 regression tests, zero removals); the governance fail-closed manifest baseline has been ratcheted accordingly. S05 can display two occurrence-bound tables: verified Official PL fixture identity and optional verified weather. The presentation lock now requires **exact header columns and complete row counts** for every actually bound S05 table. When weather is unavailable, the weather table is omitted without hiding valid fixture rows; any missing bound fixture, missing bound weather table, extra unauthorized table or malformed column fails closed at final human-facing QA. The strict check repairs the first post-#968 production failure `S05_RENDERED_TABLE_COUNT` without downgrading report validation or changing V12 scoring.

### S05 verified non-PL schedule acquisition (11 Oct 2026)

ESPN scoreboard date ranges `dates=YYYYMMDD-YYYYMMDD` began returning HTTP 400 in September 2026. The S05 report-time acquisition now requests separate calendar months with `dates=YYYYMM`, deduplicates native event IDs, filters verified source events to the exact report window, and retains event-specific source URLs. Any failed monthly response fails its competition coverage rather than being interpreted as zero fixtures; when non-PL authority is still incomplete, S05 remains truthfully `DEGRADED` while Official FPL remains the Premier League fixture authority. This does not alter V6, xPts/xMins, optimiser, Monte Carlo, private finance, or scheduler ownership.

## Reports

Official Public API MATCH adoption (#954) extends V6 per-entry GW facts with Official transfer hit, automatic substitutions, raw submitted picks, verified previous-GW cumulative totals (58 manager histories), fresh fixture/score and event-status snapshots, with source lineage. V12 produces provisional net/live ranks only from verified evidence, never promotes static standings to live, and remains independent of private /me and /my-team authentication. [Endpoint inventory and remaining proof requirements](docs/official_public_api_inventory.md). The production FULL GREEN acceptance still requires a verified exact-occurrence prefetch, 58/58 hit/baseline coverage, 13/13 rendered sections and delivery receipt.\n\nMATCH public-first recovery: the canonical V12 runner previously accepted DEEP/PRICE only and rejected governed MATCH requests before creating report artifacts. An isolated MATCH adapter now consumes exact-occurrence Official FPL V6 submitted picks (11 XI, 4 bench), GW live points, all 58 ICON+ managers, and displays the 13 locked MATCH sections including fixture scores, MATCH10 exposure and MATCH13 source status. Auth-only bank/FT/purchase/selling values remain unavailable on AUTH_EXPIRED; provisional gross scores are explicitly not verified net league ranks until transfer hit/autosub authority is complete. No private session, P1.7, MC 500K, chip ledger, or scheduler behavior changes.


S06 mobile pitch displays the entire already-calculated **CURRENT15** P1.7 formation frontier (including 3-4-3 where a legal canonical row exists), not only two leading routes. Formation xPts remain unchanged. Missing rows are explicitly labelled unavailable. DCL→Barry and DCL→Gonzalo are roster-transfer scenarios **not computed** by the S06 presentation change; each still requires validated finance, legality, canonical lineup optimization and full 500K MC before any recommendation. GW6 team news from 20 clubs and 113 player signals is ingested as bounded secondary evidence via the existing P1.1 adapter. V6 facts and P1.7 decision ownership are unchanged.

**DEEP** is the full planning report, **PRICE** handles price/timing, **DEADLINE / FINAL** is the final pre-deadline checkpoint, and **MATCH** covers post-deadline and matchday monitoring.

Primary schedule: **DEEP 04:30 / 12:30 / 21:30 Asia/Jakarta** and **PRICE 23:30 Europe/London**. Deadline and Matchday use governed checkpoints. T-24 through T-3 bind to the official deadline and emit one occurrence-bound DEEP report; T-2 through T-5 remain delta/final overlays.
ChatGPT automation `FPL Master Monitor V12` is the sole recurring scheduler, running every HH:30 Asia/Jakarta. At each genuine natural occurrence, its **first production-side effect** is the governed update of issue #431 TITLE with the exact hourly logical slot, followed by title readback. This triggers the V6 core via `event=issues`; report-prefetch cannot substitute for scheduler health. For due DEEP/PRICE or verified live MATCH checkpoints, the same master may post exactly one occurrence-bound `/fpl-master-tick` comment on #431 after verifying no existing exact-slot command/receipt. The downstream GitHub issue-comment orchestrator runs report prefetch, V12, QA and private publication, but cannot prove user-visible native delivery on its own. No independent GitHub clock/cron, ad-hoc replay, or alternate scheduler is authoritative. PRICE remains bound to 23:30 Europe/London (DST-safe).

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

### P0 public-first natural delivery repair (2026-10-11T05:57:00+07:00)

PR #957 isolates the known live command parser failure: audited `reason` metadata is bounded and `MATCH` routes to governed `match_mode` with exact `latest/match.json` verification. Canonical MATCH terminality remains fail-closed on publication, body hash, QA and private receipt; private personal authentication is **not** a public-report prerequisite. In S15B, Official FPL can assign tied league ranks, so Top 10 displays exact first-ten standings positions while retaining actual rank values and rejects missing/duplicate entries. No QA relaxations, MC/universe reductions or alternate scheduler are permitted. Controlled CI, generated Markdown and private latest **do not** prove natural ChatGPT delivery; require genuine scheduler title mutation, exact issue command, orchestration, same-slot prefetch and rendered native user-visible evidence. Historical missing slots remain missing.

- **Stage3 temporal-integrity and OIDC store diagnostics (11 Oct 2026):** an explicit DEEP Stage3 `acceptance_class=INTEGRITY_FAIL` is now forbidden to publish as `READY_FULL` (including `S02_OBSERVATION_TIMESTAMP_INVALID` on an after-slot retry). Independent engineering-only Stage3 closure remains advisory under report-first. Owner-only auth diagnostic `STORE_HEALTH` reads encrypted credential phase/version and coarse expiry metadata without making a refresh request, writing secrets or pretending natural success. Keep natural/receipt/MC500K/P1.7 untouched and use this read-only gate before any possibly destructive re-enrollment.
- **OIDC STORE_HEALTH connected-control command (11 Oct 2026):** control issue #431 accepts the exact owner-only comment `/fpl-auth-probe STORE_HEALTH` as an alias for the existing read-only `STORE_HEALTH` diagnostic. It checks only encrypted-store metadata; it never issues an OIDC grant, refreshes credentials, writes the store, exposes tokens, or counts as natural scheduler proof.
