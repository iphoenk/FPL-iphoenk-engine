# V12 Parallel Architecture — Phase P1 Discovery DAG

Status: **P1 COMPLETE / P2+ BLOCKED BY GO-LIVE PREREQUISITES**  
Source main SHA: `b279a55c2b933d10a3c1cf35ac1e86f4cc414d5e`  
Discovery date: 2026-09-24  
Scope: source-only/read-only architecture discovery. No runtime, workflow, config, V6, or mathematical-owner changes.

## 0. Gate state

The parallel-architecture plan requires P1.7 go-live to be CLOSED and no overlapping performance PR on the same files before P2+.

At this source snapshot those prerequisites are not satisfied:

- production README still states Stage 3 is code-merged with controlled + natural DEEP acceptance pending;
- multiple P1.7/performance/recovery PRs remain open, including #686 (prepared rollback) and #682 (secondary-boundary/fail-operational path);
- therefore this branch contains **documentation only** and does not start P2/P3.

## 1. Current execution DAG

```text
V6_REPORT_PREFETCH_BINDING
        |
        +--> V6_OFFICIAL_FACTS -------------------------------+
        |                                                    |
        v                                                    v
V12_ANALYTICS_FOUNDATION                           P1_8_MINI_LEAGUE_SNAPSHOT
        |
        v
P1_1_P1_3_FULL_UNIVERSE
        |
        +--> P1_6_TACTICAL_ROLE
        +--> ALL15_MATERIALIZATION
        +--> P1_7_LINEUP (owned)
        |
        v
P1_2A_PACKAGE_SEARCH (full direct, max_transfers=1)
        |
        v
P1_2_PACKAGE_UTILITY (direct exact P1.7 horizons)
        |
        v
P1_2_MATERIAL_FUNDING_LEGS
        |
        v
P1_2A_FUNDED_PACKAGE_SEARCH
        |
        v
P1_2B_FUNDED_PACKAGE_UTILITY
        |
        v
P1_2B_PACKAGE_COMBINE
        |
        v
P1_4_MATERIAL_ROUTE_SELECTION
        |
        v
P1_4_MONTE_CARLO (HOLD + material routes, 500k)
        |
        v
P1_4_PACKAGE_BINDING
        |
        v
P1_2_STAGE3_DECISION_CLOSURE
        |
        v
P1_2_STAGE3_DECISION_BINDING
        |
        +--------------------> P1_8_MINI_LEAGUE_OVERLAY
                                  |
                                  v
                         P1_8_MINI_LEAGUE_BINDING
                                  |
                                  v
                         MATERIALIZE_DEEP_REPORT
                                  |
                                  v
                             PRE_RENDER_QA
                                  |
                                  v
                               RENDER
                                  |
                                  v
                     POST_RENDER_QA + HUMAN_FACING_QA
```

Primary source:
- V6 report-prefetch binding: `src/engines/v12_integrated_report_runner.py:2234-2246`
- Foundation -> Stage2: `src/engines/v12_integrated_report_runner.py:2302-2372`
- Owned P1.7: `src/engines/v12_integrated_report_runner.py:2390-2421`
- Direct/funded/package chain: `src/engines/v12_integrated_report_runner.py:2637-2775`
- MC and Stage3: `src/engines/v12_integrated_report_runner.py:2784-2863`
- P1.8 overlay: `src/engines/v12_integrated_report_runner.py:2872-2898`
- Materialize/render/QA: `src/engines/v12_integrated_report_runner.py:3479-3554`

## 2. Stage dependency table

| Stage | Entry / owner | Main inputs | Main output | Consumed by |
|---|---|---|---|---|
| V6 prefetch binding | `_require_report_prefetch` | V6 report-prefetch latest/health + report_slot | same-occurrence bound prefetch | whole DEEP occurrence |
| Foundation | `load_v6_analytics_foundation` + `require_match_foundation` | runtime-data V6, current Official bootstrap, planning_gw, strength | match/statistical foundation | Stage2 |
| Stage2 P1.1/P1.3 | `load_or_build_stage2_projections` -> canonical `historical_projection.build` | bootstrap, strength, foundation match/features/history, planning_gw | full-universe projections | P1.6, P1.7, P1.2A/B, MC |
| P1.7 owned | `optimize_lineup` | projections + owned15 + planning_gw | full owned lineup decision | report/ALL15 decision surfaces |
| P1.2A direct | `search_packages` | owned15, full eligible candidates, bank | exact direct legal route set incl. HOLD | P1.2B direct |
| P1.2B direct | `evaluate_packages` | direct route set, projections, finance | per-route exact P1.7 horizon utility | material funding-leg selection |
| Funded search/utility | `compose_material_two_transfer_packages` -> `evaluate_packages` | material direct legs, owned15, bank, projections | funded package utility | combine |
| Combine | `combine_package_utility_surfaces` | direct + funded utility | unified package utility | MC route selection |
| MC P1.4 | `canonical_package_seed` -> `run_package_monte_carlo` | projections, final package utility, material route IDs | correlated route distributions | Stage3 closure |
| P1.8 snapshot | `build_mini_league_snapshot` | standings + manager picks | mini-league factual snapshot | overlay |
| P1.8 overlay | `evaluate_mini_league_overlay` | Stage3 package decision + mini snapshot + MC | downstream mini-league overlay | package binding/report |
| Stage3 | `finalize_stage3_decision` + `attach_stage3_decision` | package utility + MC + price uncertainty + projections | final Stage3 action surface | P1.8/render |
| Materialize/render | `materialize_deep_report` -> `render_deep_text` | canonical text + section payloads + decision stack | report object + visible body | QA |
| QA | `validate_pre_render_qa`, `validate_post_render_qa`, human-facing validators | report/manifest/body | PASS/FAIL + execution proof | delivery |

Additional sources:
- Stage2 cache is execution-only; canonical builder remains mathematical owner: `src/engines/v12_stage2_derived_cache.py:1-9,107-130,181-202`.
- V6 prefetch exact occurrence checks: `src/engines/v12_integrated_report_runner.py:248-316`.

## 3. Q1–Q7

### Q1. Does Foundation use current-GW snapshot data, or historical-only?

**Answer: CURRENT SNAPSHOT + CURRENT-SEASON MATCH FACTS; not historical-only. VERIFIED.**

Evidence:
- Foundation receives current `bootstrap`, `planning_gw`, and `strength`: `src/models/v12_analytics_foundation.py:346-356`.
- It selects match data up to the latest completed GW and reads current Official element identity from bootstrap: `src/models/v12_analytics_foundation.py:357-376`.
- It emits `planning_gw`, `latest_completed_gw`, current-season match rows, and current-season opponent history: `src/models/v12_analytics_foundation.py:614-641`.
- The foundation's historical prior is explicitly empty at this boundary, while supplemental V6 sources remain read-only: `src/models/v12_analytics_foundation.py:642-660`.
- Governance marks V6-only factual inputs and Official match history as primary: `src/models/v12_analytics_foundation.py:679-685`.

Implication for parallel work: Foundation cannot be initialized independently from the current factual snapshot. I/O/import overlap is only safe after preserving this input binding.

### Q2. Are Stage2 player×fixture units truly independent?

**Answer: CONDITIONALLY INDEPENDENT AFTER IMMUTABLE PARENT PRECOMPUTE. VERIFIED.**

The per-player/per-fixture projection path itself uses local objects and does not expose a decision-state dependency between fixture tasks. However, a raw `(player, fixture)` call is not self-contained:

- Stage2 first builds universe-wide `global_position_calibration` from all match rows: `src/models/historical_projection.py:95-116`.
- It builds shared team matchup maps and per-player historical maps before the player loop: `src/models/historical_projection.py:118-130,180-192`.
- Each player fixture consumes precomputed player/context evidence, opponent history, teammate links/start probabilities, and the global calibration: `src/models/historical_projection.py:400-516`.
- `enhance_fixture_projection` deep-copies its base projection and mutates only local structures: `src/engines/v12_position_probability_components.py:1258-1285`.
- The only cache observed in contextual dynamics on this path is config loading via `@lru_cache(maxsize=1)`: `src/engines/v12_contextual_dynamics.py:43-50`.

Therefore P4-A should fan out **player chunks after parent precompute**, passing immutable/read-only calibration/context inputs. Do not make each worker rebuild global calibration or write a shared cache.

### Q3. Are `build_player_trajectory` and `build_contextual_dynamics` separable exactly as assumed?

**Answer: trajectory = player-specific; contextual = NOT context-only. VERIFIED.**

- `build_player_trajectory(match_rows, player_id, current_gw)` filters rows to that player and GW cutoff: `src/engines/v12_contextual_dynamics.py:312-349`.
- A safe memo key therefore needs at least player identity + GW + deterministic input/fingerprint context. Player ID alone is insufficient across snapshots.
- `build_contextual_dynamics` is not merely team/opponent/GW context. It consumes player match rows, player_id, current_gw, opponent, current context, linkups, chains, teammate start probabilities, opponent historical rows, and history scope: `src/engines/v12_contextual_dynamics.py:2222-2247`.
- It then applies teammate/link dependency evidence: `src/engines/v12_contextual_dynamics.py:2268-2314`.

Implication: P4-B as written must be narrowed. Memoizing `build_contextual_dynamics` only by a team/opponent/GW context key would be incorrect. Any memoization key must include the player-specific and linkup/teammate/history dependencies or their deterministic fingerprint.

### Q4. Is owned P1.7 identical to P1.2B HOLD?

**Answer: SAME FOOTBALL OWNER + SAME SQUAD/GW SEMANTICS, but RAW PAYLOAD IS NOT IDENTICAL. VERIFIED.**

- Direct HOLD is constructed from the unchanged current squad: `src/engines/v12_package_search.py:293-307,333-348,368-372`.
- P1.2B requires exactly one HOLD and derives each route's exact 15-player identity from `final_squad_elements`: `src/engines/v12_package_utility.py:106-127`.
- P1.2B's `_lineup_decision` calls the same `optimize_lineup` owner on that squad/GW: `src/engines/v12_package_utility.py:130-159`.
- Owned P1.7 in the integrated runner also calls `optimize_lineup` on sorted owned IDs for the planning GW: `src/engines/v12_integrated_report_runner.py:2390-2421`.
- But `_lineup_decision` then projects the full P1.7 payload into a reduced route-utility structure: `src/engines/v12_package_utility.py:160-198`.

Therefore the football decision should be semantically identical on identical inputs, but the two returned objects are not object-equal. P5.2 cannot simply substitute the current compressed HOLD payload for the full owned P1.7 payload. Reuse requires an explicit canonical shared-result boundary plus equality tests on decision-critical fields/full payload as appropriate.

### Q5. How is MC RNG seeded; does HOLD depend on route list/count?

**Answer: ROOT SEED DEPENDS ON THE MATERIAL ROUTE SET. P5.1 MUST STOP AS CONTRACT-CHANGE. VERIFIED.**

- `canonical_package_seed` hashes the full projection fingerprint plus `football_route_signature` for the selected route definitions: `src/engines/v12_monte_carlo.py:940-963`.
- That route signature contains each route ID and each route's per-GW XI/bench/C/VC: `src/engines/v12_monte_carlo.py:889-937`.
- Canonical process sharding then derives deterministic child streams with `SeedSequence(seed).spawn(workers)`: `src/engines/v12_monte_carlo.py:2414-2482`.

Changing which material routes are present can change the root seed even when HOLD itself is unchanged. Therefore running HOLD MC early, before P1.2B/material route selection finishes, is not bit-identical to current canonical MC. Do not overlap MC HOLD with P1.2B without an explicit RNG-contract redesign.

### Q6. Is HOLD always present in MC?

**Answer: YES. VERIFIED.**

- `_route_rows_from_package` fails if HOLD is absent and prepends HOLD whether route IDs are implicit or explicit: `src/engines/v12_monte_carlo.py:801-835`.
- Canonical MC separately fails if HOLD is absent: `src/engines/v12_monte_carlo.py:2856-2866`.
- The integrated runner passes material non-HOLD route IDs; the MC owner adds HOLD itself: `src/engines/v12_integrated_report_runner.py:2784-2817`.

### Q7. Do P1.2B family×GW tasks carry semantic state across GWs?

**Answer: NO SEMANTIC CROSS-GW STATE; YES REUSABLE PURE/IMMUTABLE CACHE STATE. VERIFIED.**

Current cross-route execution:
- groups direct squads by HOLD-relative route family and invokes one exact 5-GW batch owner: `src/engines/v12_package_utility.py:1292-1336`;
- primes player surfaces for all five GWs before the GW loop and materializes a read-only surface catalog per GW: `src/engines/v12_lineup_batch.py:3036-3076`;
- then loops GW independently and evaluates HOLD/families against the GW-specific catalog: `src/engines/v12_lineup_batch.py:3078-3154`;
- reuses GW-invariant structural plans through pure `lru_cache`: `src/engines/v12_lineup_batch.py:293-330`;
- reuses a pure bench tie-rank matrix explicitly across the five-GW horizon: `src/engines/v12_lineup_batch.py:1368-1385`.

Important task-count correction:
- direct one-transfer families are inferred by outgoing player and HOLD is tracked separately: `src/engines/v12_lineup_batch.py:2774-2833`.
- Therefore “75 family×GW tasks” is not a safe hard-coded total unless it explicitly means 15 change families × 5 GWs and handles HOLD separately. Current source has separate `hold_indices`. A deterministic executor should derive task keys from the actual family plan, not assume 75 total tasks.

Implication for P2/P3: prebuild/prime immutable surfaces and static family structures in the parent before fork where possible. Workers may consume them read-only; worker-local cache fills must not become correctness dependencies.

## 4. P1 conclusions that modify later phases

1. **P2 design remains valid**, but prewarming immutable/static cache state in the parent is important before `fork`.
2. **P3 must not hard-code 75 total tasks.** Derive deterministic `(family_key, gw)` tasks from the actual family plan and model HOLD explicitly.
3. **P4-A should parallelize by player chunks after shared parent precompute**, not rebuild global calibration/context in every worker.
4. **P4-B requires a corrected memo key.** `build_contextual_dynamics` cannot be cached by team/opponent/GW alone.
5. **P5.1 is blocked by RNG contract.** HOLD MC cannot start before material route set finalization while preserving current canonical seed.
6. **P5.2 is not direct object reuse today.** Owned and HOLD share P1.7 semantics but expose different payload shapes.
7. **P6 route-level MC parallelism requires care beyond “one stream per route”.** Current canonical MC intentionally uses common random numbers across routes inside each shard. A route-per-process redesign would change that contract unless it reproduces the same shared-world draws exactly.

## 5. P1 acceptance

| Requirement | Result |
|---|---|
| Stage DAG documented | PASS |
| Q1–Q7 answered | PASS |
| Every Q1–Q7 answer has `path:line` evidence | PASS |
| Unverified claims presented as verified | NONE |
| Production/runtime code changed | NO |
| V6 changed | NO |
| P2+ started before prerequisite closure | NO |

**P1 verdict: PASS.**

Next legal action under the plan: wait for the P1.7/go-live prerequisites to close, then re-read exact main and start P2 on a separate phase branch/PR.