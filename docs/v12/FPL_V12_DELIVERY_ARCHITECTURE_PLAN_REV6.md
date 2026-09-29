# FPL Master V12 — Delivery Architecture Plan

**Authority revision:** 6  
**Effective:** 2026-09-27T04:02:05+07:00  
**Repository:** iphoenk/FPL-iphoenk-engine  
**Supersedes:** Delivery Architecture Plan Revision 4 and earlier delivery-plan wording where inconsistent with this document.

This document is the delivery/performance/validation authority for FPL Master V12. It does not replace Canonical V12 football methodology or V6 factual-source governance. Where this plan changes operational behavior, implementation must remain compatible with the Canonical V12 decision engine and V6 factual data plane.

## 0. Non-negotiable architecture

1. **One factual plane:** V6 is the production factual data plane.
2. **One decision brain:** Canonical V12 remains the only authority for projections, probabilities, tactics, package optimization, XI/bench/C/VC, chips and final WAIT/PREPARE/ACT decisions.
3. **One scheduler authority:** ChatGPT `FPL Master Monitor V12` is the only authoritative recurring FPL scheduler. GitHub cron/watchdog jobs are not substitute scheduler authorities.
4. **Public compute, private personal state:** `iphoenk/FPL-iphoenk-engine` is the public factual/compute plane. Manager-specific state and decision output live in `iphoenk/fpl-reports-private`.
5. **Zero-cost execution:** standard public GitHub-hosted runners only. No paid VM, no private-repository Actions compute, no always-on paid service.
6. **No second model:** scenarios, stability analysis, challengers, PWA and MCP consume or perturb the canonical engine. They may not implement a second scorer, optimizer or captain model.
7. **No legacy production execution:** V3/V4/V5 remain frozen and non-executable.
8. **No performance shortcut may weaken correctness:** do not reduce MC paths, prune exact route search, loosen QA, bypass private-plane rules, or rewrite acceptance evidence to hit latency targets.

## 1. Production continuity and privacy prerequisites

Architecture changes that can affect delivery must not be stacked blindly.

Before a major production merge:
- fetch exact latest main;
- branch from latest main;
- run required CI/governance;
- require terminal GREEN;
- merge with exact-head guard using a repository-supported merge method.

After a major production merge:
- require the next genuine natural `:30` FPL Master occurrence on that merged main before another major architecture merge;
- manual, diagnostic, workflow_dispatch, report-prefetch and backfill runs do not count as natural acceptance.

Current production continuity contract:
- scheduler health becomes established after **6 consecutive genuine ChatGPT scheduler slots**;
- each accepted slot must have exactly one governed acquisition, collect/publish/orchestration success, `authoritative_runtime_snapshot=true`, `fulfilled_by=CHATGPT`, `chatgpt_scheduler_fulfillment=true`, and `duplicate_trigger_count=0`;
- historical missing slots remain historical and are never rewritten.

Privacy contract:
- public runtime must fail closed on manager-specific files;
- no public `data/v6/personal/` content;
- private-only includes current team, bank, selling values, free transfers, chips, pending transfers, submitted picks, bench order, captain/vice state, owner league memberships, exact routes, scenarios and full decision reports;
- private-delivery failure must not fall back to public publication;
- public logs and proof artifacts may contain only explicitly safe observability, never personal payload.

## 2. Visible schedule and timing authority

### 2.1 Fixed visible slots

| Slot | Visible report |
|---|---|
| 04:30 Asia/Jakarta | DEEP, 23 canonical sections |
| 12:30 Asia/Jakarta | DEEP, 23 canonical sections |
| 21:30 Asia/Jakarta | DEEP, 23 canonical sections |
| 23:30 Europe/London | PRICE |

PRICE is defined in **Europe/London local time**, not as a fixed WIB hour:
- BST: 23:30 London = 05:30 WIB next day;
- GMT: 23:30 London = 06:30 WIB next day.

DST transitions must be tested around 24/25/26 October 2026 and must produce exactly one PRICE publication.

### 2.2 Silent core cadence

Every natural `HH:30` ChatGPT scheduler occurrence owns current `HH:00` core upkeep. Core upkeep is silent unless a visible report is independently due.

GitHub watchdog is monitoring-only:
- it may diagnose;
- it may not trigger V6 acquisition;
- it may not publish runtime;
- it may not advance scheduler proof.

### 2.3 Quiet hours

Quiet window: **21:30 through 04:30 Asia/Jakarta**.

No extra visible report is emitted in quiet hours except:
- owner-requested ADHOC output;
- deadline window beginning at T-3 hours;
- mandatory final/deadline handling explicitly defined below.

### 2.4 Deadline checkpoints

All checkpoints derive from the authoritative Official FPL deadline.

| Checkpoint | Contract |
|---|---|
| T-24h | full DEEP deadline contract |
| T-12h | full DEEP deadline contract |
| T-6h | full DEEP deadline contract |
| T-3h | full DEEP deadline contract; opens warm deadline worker |
| T-2h | delta-first |
| T-1h | delta-first + execution card |
| T-30m | FINAL REVIEW execution card |
| T-15m | GO/NO-GO confirmation |
| T-5m | final confirmation only |

Delta-first content uses existing canonical ownership rather than creating new top-level sections:
- S01 Decision / Current Status;
- S03 Decision Delta;
- S18 Action Board;
- S19 Final Judgement;
- execution card embedded inside those canonical sections.

Execution card includes transfer/roll, hit, XI, bench GK, bench 1–3, C, VC, chip, GO/NO-GO, remaining risk and data-freeze time.

### 2.5 Overlap resolver

When multiple report families coincide, emit **one coherent report** using the richest applicable contract. No duplicate DEEP+MATCH, PRICE+deadline, or multiple checkpoint reports for the same instant.

## 3. Precompute and visible delivery

Scheduled visible reports are precomputed before their visible slot.

Default precompute window:
- begin approximately T-15 to T-10 minutes;
- validate, freeze and publish at the visible slot;
- record actual compute-ready time, freeze time and publication time.

The user-visible goal is not “cold compute in ≤15 s.” The goal is:
- scheduled report open: effectively immediate because already computed;
- scenario lookup: immediate from precomputed package;
- warm recompute: ≤15 s under the explicit warm-worker contract;
- cold recompute: measured and monitored, but not a hard ≤15 s gate.

## 4. Scenario package P4

P4 is a canonical-engine scenario cache, not a second decision model.

Required base package:
- current actual base state;
- 15 OUR15 unavailable scenarios;
- top captain/vice doubt scenarios where supportable.

Rules:
- each scenario uses official input override paths and the same canonical P1.1 → P1.3 → P1.3B → P1.6 → P1.2A/B → P1.7 → P1.4 → P1.8 decision chain as applicable;
- every package is bound to a deterministic base fingerprint;
- base-fingerprint change invalidates the package;
- scenario output remains private;
- scenario labels can never be promoted silently to actual state;
- scenario records include the mandatory decision core plus every canonical report section whose content differs from BASE_CURRENT15, and preserve the canonical Stage3 action needed by the semantic oracle;
- P6 scenario refresh is copy-on-write over the frozen warm state: it applies all persisted changed sections, rematerializes the canonical report, rebuilds serving artifacts, and reruns pre-render, post-render, human-facing and final-delivery QA without deep-copying the full model state;
- warm scenario publication must be semantically identical to the same controlled canonical-cold input; partial scenario refresh may never expose stale baseline sections or stale optional serving artifacts;
- scenario lookup feeds the stability layer but never bypasses it once stability is integrated.

## 5. Warm window worker P6

P6 is the mechanism that makes event-to-result ≤15 s achievable on zero-cost infrastructure.

### 5.1 Deadline window

From T-3h through deadline:
- run one long GitHub-hosted public-runner job;
- load reusable state once;
- keep valid structural state in memory;
- poll Official FPL/material inputs approximately every 2–3 minutes;
- poll owner command transport at a safe short cadence;
- use minimum valid invalidation rather than cold rebuilding everything;
- checkpoint T-2/T-1/T-30/T-15/T-5 is published by this worker.

No single job may exceed GitHub-hosted limits. If rollover is necessary, hand off only small validated state and cache envelopes; never private plaintext through public artifacts.

### 5.2 Match window

A warm worker may cover a live-match window:
- poll live facts periodically;
- maintain incremental match/post-match state in memory;
- render visibly only when a canonical visible slot is due;
- quiet-hour match work remains silent and feeds the next allowed slot.

### 5.3 Warm latency definition

Warm latency is measured from:
**T0 = worker has already received/detected the owner command or material factual change**
to
**T1 = validated private result/digest is published and consumable**.

It includes:
- required partial recompute;
- canonical decision materialization;
- render;
- private publish.

It excludes:
- GitHub queue time before the warm worker exists;
- runner provisioning;
- dependency installation;
- initial state bootstrap.

A warm latency result is invalid if it skips required compute, lowers MC, prunes routes, or relaxes QA.

## 6. On-demand owner commands P5

Supported owner-gated commands:
- `/status`
- `/show deep`
- `/show price`
- `/show league`
- `/scenario <player>`
- `/deep`
- `/price`
- `/league`

Rules:
- only owner-authorized transport executes compute;
- non-owner public issue comments must not consume production compute;
- `/show` reads the latest valid private result;
- fresh commands compute using the canonical engine;
- commands do not replace scheduled slots;
- if an identical scheduled computation is already in progress, reuse/bind that state rather than duplicate it;
- exact command time, data-freeze time and source lineage are recorded.

## 7. Cache classes, dependency matrix and crypto

### 7.1 Freeze expectations before experiments

The cache dependency matrix must be declared before measuring a partial-change experiment.

Required change classes:
- UNCHANGED
- PRICE_ONLY
- INJURY_STATUS
- OWNED_AVAILABILITY
- XMINS
- ROLE
- SET_PIECE_ROLE
- FIXTURE
- TEAM_FINANCE
- MINI_LEAGUE_ONLY
- RUNTIME_CLASS
- SCENARIO_OVERRIDE
- CHALLENGER_ONLY

Required layers:
- Stage-2;
- P1.7;
- MC;
- scenario package;
- stability package.

Interpretation:
- observed HIT when expected MISS = correctness failure;
- observed MISS when expected HIT = performance over-invalidation;
- warm output different from canonical cold output for the same state = correctness failure.

### 7.2 Personal cache encryption D-P3

Personal/decision caches for P1.7, MC, scenario and later stability are private-only and encrypted at rest when persisted.

Required cryptographic contract:
- AEAD, default AES-256-GCM;
- fresh random 96-bit nonce on every encryption;
- key material never stored in cache payload or public artifact;
- opaque envelope versioning;
- deterministic AAD includes at least `cache_key`, `schema_version`, `crypto_version`;
- copying ciphertext to a different cache key must fail authentication;
- decrypt/auth failure causes safe cache MISS and canonical recompute;
- PR/fork workflows never receive decryption secrets;
- no plaintext personal cache in GitHub public Actions cache/artifact/log.

Profiles:
1. `SECURE_NO_PERSONAL_CACHE` — correctness baseline.
2. `SECURE_ENCRYPTED_PERSONAL_CACHE` — target secure warm profile.

## 8. Performance experiment order

Experiments are evidence-driven and performed in this order.

### PERF-0
Close the baseline with **6 comparable canonical production-main DEEP executions**.

Qualifying primary samples may be either genuine natural runs or controlled production-equivalent runs, provided all of the following hold:
- exact production-main SHA;
- canonical DEEP semantics;
- actual Monte Carlo paths >= 500,000;
- complete required phases;
- correct runtime/cache metadata;
- no semantic shortcut;
- branch-only acceptance excluded;
- synthetic semantic fixtures excluded;
- normalized and native runtime classes are never mixed in one percentile distribution;
- controlled samples never count as scheduler continuity proof.

Capture:
- production main SHA and runtime-data SHA;
- run ID;
- logical CPU count;
- physical core count only when directly supportable;
- CPU model where available;
- runtime class;
- Python, NumPy, OpenBLAS and SIMD where available;
- thread count;
- cache profile and cache state;
- queue/provision/setup;
- factual acquisition;
- Stage-2;
- P1.2A;
- P1.2B route/package search;
- P1.7 decision materialization;
- P1.4 MC;
- render/QA;
- private publication;
- cold total.

Never infer missing timing or physical-core metadata. Three historical diagnostic runs with `REQUIRED_CORE_SLOT_BINDING_PARTIAL_CORE_SLOT_MISMATCH` remain excluded and may not be promoted merely to reach the target.

Summary rules:
- p50 is valid at n>=3;
- max is valid at n>=1;
- PERF-0 closure requires n>=6;
- p90 is valid only at n>=10;
- p90 availability is **not** a prerequisite for PERF-0 closure at n=6.

### PERF-A
A/B Monte Carlo normalized-runtime versus native-runtime on the **same host**, same SHA, snapshot, routes and seed. Use ABAB order. Freeze the latency metric and acceptance rule before reading results.

### PERF-B
Only if native runtime is materially better: run MC as a native subprocess on the same GitHub runner and define a reproducibility contract by runtime class.

### PERF-C
Only if MC remains a material bottleneck: profile internal MC parallelism/vectorization without changing 500k-path semantics.

### PERF-D
Profile Stage-2 with worker counts 1/2/4 under the same input state.

### PERF-E
Freeze immutable B→C→D handoff schemas so downstream workers can reuse validated state without semantic drift.

### PERF-F
Measure cold end-to-end execution after the above improvements. Cold ≤15 s is not required.

### PERF-F2
Measure warm P6 end-to-end T0→T1 and require ≤15 s for supported warm classes:
- unchanged/show;
- price-only;
- injury/status;
- owned availability;
- xMins;
- role;
- mini-league;
- scenario lookup;
- set-piece role where supportable.

### PERF-F3
For each class, verify warm output equals canonical cold output for the same final state.

### PERF-G
Consider additional machine separation only if P6 still materially misses ≤15 s after the above work. Under the zero-cost constraint, do not introduce paid infrastructure without a new explicit owner decision.

## 9. Factual additions

### FACT-1 Event-status / bonus lifecycle
Audit Official FPL event/fixture lifecycle and BPS/bonus finalization semantics. Reports must distinguish live/provisional from final data.

### FACT-2 Official set-piece notes
Official set-piece/tactical notes may become evidence for P1.6 role inference. They do not directly set xMins/xPts and do not replace the tactical model.

## 10. Historical point-in-time truth

Historical evaluation must use only information available at the historical decision instant.

Required properties:
- pre-deadline factual snapshots;
- stable identity keyed by canonical IDs;
- no future injuries, prices, results, ownership or lineups leaking backward;
- partial historical coverage is labelled PARTIAL rather than imputed as known;
- ambiguous identity fails closed;
- historical data is for calibration/replay, never current production fact substitution.

A historical cache/mirror such as the design inspired by public FPL cache repositories is an input archive, not a second model.

## 11. Validation hierarchy

Validation is layered. Passing a lower layer never substitutes for a higher one.

### VAL-1 Probability calibration
For supported probability outputs:
- Brier score;
- log loss;
- reliability/calibration curves;
- sample count and coverage;
- by position and relevant horizon where sample size allows.

### VAL-2 Ranking quality
Evaluate:
- Spearman;
- NDCG;
- top-K/high-return recall;
- position and horizon slices;
- coverage and uncertainty.

### Decision Surface Stability
Stability is downstream of canonical MC and optimizer output.

It measures whether small supported input uncertainty changes the decision surface:
- best action;
- second-best action;
- HOLD;
- EV delta;
- selection probability;
- regret;
- reversal probability;
- route survival;
- number of near-optimal alternatives.

Required decision classes:
- 1FT;
- multi-transfer packages;
- hits;
- Wildcard;
- XI/bench;
- captain;
- chip.

Perturbations must come from supportable uncertainty distributions, never arbitrary hand-tuned noise.

Stability is observational first. It may not alter WAIT/PREPARE/ACT until historical replay calibrates thresholds.

### VAL-3 Policy replay
Historical replay is no-lookahead and point-in-time.

Frozen baselines include:
- B0 HOLD;
- B1 legal greedy xPts;
- B2 highest-xPts captain;
- B3 simple fixture heuristic;
- B4 canonical V12 without Stability decision thresholds.

Measure decision utility/regret and reversal behavior. Do not retro-fit thresholds after reading the final evaluation set.

### DS-3 Threshold freeze
WAIT/PREPARE/ACT stability thresholds are frozen from calibration/training replay before integration into production decisions.

### VAL-4 Ablation
Measure marginal contribution of major evidence/model blocks. Challenger/context sources may not be retained merely because they sound useful.

## 12. Challenger layer rules

External models/data can be:
- fact source;
- challenger;
- retrospective validator;
- context.

They may not become a second production decision engine.

Examples:
- elite-manager cohort;
- bookmaker market probabilities after de-vig;
- structural/value models;
- retrospective ML challengers;
- external xG/xA/tactical feeds.

Rules:
- preserve quoted versus derived distinction;
- calibrate any translation/threshold before production use;
- do not inject elite ownership/EO into football xPts;
- do not let bookmaker probability silently replace canonical scoring;
- external disagreement appears as evidence/challenge, not hidden arbitration;
- optional provider outages degrade only their own challenger scope.

## 13. Elite/market/value workstreams

### ELITE
Cohorts may include:
- overall;
- current-form;
- proven/historical;
- ICON+ 58;
- direct rivals.

Show denominator, sample size and uncertainty. Context only until validated.

### OPTA pilot
Use stable exact IDs such as `opta_code`. No fuzzy identity joins.

### MARKET
Bookmaker probabilities must be de-vigged, source-labelled and treated as challenger evidence until calibration proves incremental utility.

### VALUE
Structural/value analysis remains a distinct low-priority challenger. Do not conflate structural value with price-movement prediction or canonical transfer action.

### MLR
Retrospective machine-learning challengers are validation/challenge tools unless separately proven and explicitly promoted. They do not silently replace V12.

## 14. Private decision bundle and consumption

### BUNDLE
Every delivered decision may have a compact private machine-readable bundle representing the same canonical state as the human report.

It contains references/values for:
- current decision status;
- squad/XI/bench;
- C/VC/chip;
- transfer/package frontier;
- scenario/stability summary;
- mini-league context;
- evidence/lineage;
- canonical section status.

It may not contain a separate scoring model.

### PWA
A PWA is a thin private renderer for four primary views:
- Decision;
- Squad;
- Rivals;
- Evidence.

It reads the canonical private bundle. It may not independently score, optimize transfers, select captain or maintain another decision state.

Private cache policy:
- network-first;
- no generic service-worker persistence of sensitive payload;
- explicit short-lived or encrypted storage only where governed.

### MCP
MCP access is read-only over the canonical bundle/digest unless a separately governed owner command action is explicitly invoked. MCP may not implement an independent scorer or optimizer.

## 15. Canonical human report contract

The DEEP backbone remains exactly the existing 23-section contract:

1. DECISION / CURRENT STATUS  
2. OUR15  
3. DECISION DELTA  
4. MATERIAL DEVELOPMENTS / CHANGES  
5. FIXTURES / REST / CONDITIONS  
6. FORMATION / XI / BENCH  
6B. FORMATION & MINI-LEAGUE STRATEGY  
7. XI BATTLE  
8. CAPTAIN / VICE CAPTAIN  
9. CHIP STRATEGY  
10. ACTIONABLE PRICE RADAR  
11. WATCHLIST20  
12. RISE20  
13. FALL20  
14. PACKAGE OPTIMIZER / TRANSFER FRONTIER  
14B. 3-GW SQUAD STAGING  
15. EVIDENCE QUALITY  
15B. ICON+ MINI-LEAGUE  
16. ALL15 TACTICAL / PROBABILITY REVIEW  
16B. POST-MATCH REVIEW GW1 → NOW  
17. SOURCE HEALTH / FRESHNESS / LINEAGE  
18. ACTION BOARD  
19. FINAL JUDGEMENT

No new top-level sections are introduced by this delivery plan.

S08 is final captain/vice authority. S19 must not contradict S08.

S15B may inform leverage/exposure, but mini-league ownership cannot silently override a materially superior football captain decision.

Qualitative-news parsing may structure evidence but may not directly manufacture numeric xMins/xPts.

## 16. Explicitly rejected shortcuts

Do **not** adopt:
- a fixed injury penalty;
- LLM-generated numeric xMins as canonical input;
- fixed home/away/position captain penalties;
- EO embedded in intrinsic football xPts;
- arbitrary persistence coefficients;
- arbitrary defender/team limits;
- player-ID final tie-break as a football preference;
- top-15 pruning presented as exact search;
- top-N managers labelled automatically as “proven”;
- cold GitHub-runner ≤15 s as a hard gate;
- a second engine, optimizer, scheduler or private-compute service;
- public plaintext personal cache;
- lower MC path counts as a latency workaround.

## 17. Final production acceptance

FINAL PRODUCTION READY / CLOSED requires all mandatory hard gates below to be GREEN with evidence:

1. **PC** — one scheduler, established natural continuity, duplicate count zero.
2. **PRIVACY** — public factual/compute and private personal/decision boundary proven naturally.
3. **DELIVERY** — P4 scenario package and P6 warm delivery architecture operational; scheduled visible reports precomputed.
4. **CRYPTO** — governed encrypted personal-cache profile passes tamper/key/AAD/fork-safety acceptance.
5. **LATENCY** — supported P6 warm classes meet ≤15 s T0→T1 without correctness shortcuts.
6. **STABILITY** — Decision Surface Stability is calibrated and integrated only after replay-supported thresholds are frozen.
7. **POLICY** — point-in-time no-lookahead policy replay passes its declared acceptance against frozen baselines.
8. **REPORT** — canonical 23-section DEEP and other visible-mode contracts remain structurally and semantically valid.
9. **GOVERNANCE** — required CI/governance GREEN on exact latest main and no unresolved production blocker.

Challenger workstreams, PWA and MCP must preserve the no-second-engine invariant.

## 18. Execution order

The governed order is:

1. PC continuity + POST-P1 privacy acceptance.
2. DOC-0 Revision 6.
3. D0–D5 schedule/delivery contracts and D-P2.
4. FACT-1 and FACT-2.
5. PERF-0 baseline.
6. CRYPTO / D-P3.
7. PERF-A → B only if justified → C only if justified → D → E.
8. D-P4 scenario package.
9. D-P6 warm worker.
10. PERF-F, PERF-F2 and PERF-F3.
11. D-P5 owner commands.
12. D-P7 ChatGPT compact-private-context interface.
13. HDT historical point-in-time plane.
14. VAL-1 and VAL-2.
15. DS-0/1/2 observational stability.
16. VAL-3 policy replay.
17. DS-3 threshold freeze and production integration.
18. VAL-4 ablation.
19. ELITE, OPTA, MARKET, MLR and VALUE as evidence justifies.
20. BUNDLE.
21. PWA.
22. MCP.
23. D-P8 end-to-end consumption acceptance.
24. PERF-G only if P6 remains materially above the warm latency target.

Every major merge is followed by a genuine natural production occurrence before the next major architecture merge.

## 19. Evidence format per workstream

Return:
- phase/workstream;
- baseline main SHA;
- branch;
- head SHA;
- PR;
- files changed;
- targeted tests;
- required CI/governance;
- production/natural run IDs where applicable;
- latency numbers using the definitions above;
- privacy evidence;
- PASS/FAIL/UNVERIFIED per gate;
- remaining blocker and whether owner action is actually required.

Unsupported claims are labelled **UNVERIFIED**, never promoted to GREEN.
