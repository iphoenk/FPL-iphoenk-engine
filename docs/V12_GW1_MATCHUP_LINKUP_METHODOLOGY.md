# V12 GW1 Trajectory, Opponent Matchup, and Link-Up Dependency

Baseline: `f47947a8f6489598bdb2672e94e22b436e08b9c4`

Implementation branch: `v12-gw1-matchup-linkup-dynamics`

Authority remains `control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt`. This
document is implementation/audit evidence only.

## Architecture

The change is V12-native and consumes already-published factual evidence. V6
remains the only factual production data plane. P1.1 remains the minutes/start
owner. P1.3 remains the event and point-distribution owner. P1.6 remains the
tactical-role scorer. Existing lineup/captain, package, Monte Carlo and
mini-league owners remain downstream consumers.

No V7, scheduler, provider, methodology authority, named-player parameter or
parallel probability engine is introduced.

## Existing factual capability audit

| Required feature | Status | Existing evidence / treatment |
| --- | --- | --- |
| match ID | AVAILABLE | player-match rows |
| GW per player-match row | PARTIAL | used only when `gw/event/gameweek/round` is actually present; never inferred from arbitrary ordering |
| opponent | AVAILABLE when two teams are uniquely identifiable | deterministic team-presence derivation |
| home / away | PARTIAL | direct `home/is_home` when supplied |
| minutes | AVAILABLE | `minutes_played/minutes` |
| starter / substitute | AVAILABLE | `start_min/started` |
| substitution timing | PARTIAL | upstream timing may exist; no fabricated exact off-minute |
| actual role / position | PARTIAL | only direct role/deployment evidence when present |
| xG | AVAILABLE | player-match stats |
| xA | AVAILABLE | player-match stats |
| xGI | DERIVED AVAILABLE | xG + xA |
| shots | AVAILABLE | `total_shots` |
| shots on target | AVAILABLE | `shots_on_target` |
| big chances | PARTIAL | provider-dependent; missing stays missing |
| touches | AVAILABLE | player-match stats |
| opposition-box touches | AVAILABLE | `touches_opposition_box` |
| key passes as a distinct field | UNAVAILABLE | existing P1.3 audit explicitly forbids aliasing `chances_created` |
| chances created | AVAILABLE | player-match stats |
| progressive passes / receptions | PARTIAL | final-third/progression evidence can exist; no false direct-reception mapping |
| crosses | AVAILABLE | `accurate_crosses` where supplied |
| cutbacks | UNAVAILABLE | no canonical distinct field proven |
| set-piece involvement | AVAILABLE | corners/set-piece route evidence where supplied |
| penalty involvement | AVAILABLE | penalty fields / Official role hierarchy |
| defensive contribution | AVAILABLE | tackles/interceptions/blocks/clearances/recoveries and existing reconstruction |
| FPL points | AVAILABLE | Official/player-match output where supplied |
| score / game state | PARTIAL | no fabricated match-state sequence |
| team attacking metrics | AVAILABLE | existing observed tactical/team-strength owners |
| injury / suspension / availability | AVAILABLE | existing Official/current evidence |
| teammate presence | AVAILABLE | player-match identity/shared minutes |
| direct player-to-player pass | UNAVAILABLE | no canonical direct recipient data proven |
| direct creator-to-finisher chance recipient | UNAVAILABLE | no canonical recipient mapping proven |
| heatmap / true positional deployment | UNAVAILABLE | existing tactical audit already marks unavailable |

Unavailable direct link fields are not a blocker. They cap link confidence. If
there is neither direct process evidence nor a reproducible tactical role
bridge, co-return correlation has zero dependency authority.

## GW1-to-current trajectory

`build_player_trajectory` retains supportable completed player matches from
GW1 through the current completed GW. It publishes match rows, latest-match
evidence, role/minutes evolution, result-vs-process evidence and recency-aware
posterior rates.

Recency weights use a global exponential half-life. Recent rates are shrunk
toward the full GW1-current rate with a global equivalent-match prior. The
result is deliberately resistant to a one-match haul while allowing repeated
role/minutes changes to move the posterior more quickly.

## Result versus process

Result evidence is goals, assists, returns and FPL output.

Process evidence is minutes, xG/xA/xGI, shots, shots on target, box touches and
chance creation, with additional supported contextual fields retained when
available.

A blank with strong xG is therefore not automatically an adverse matchup. A
haul with weak process is not automatically an ACT signal.

## Opponent-specific matchup

`evaluate_opponent_matchup` compares the player's current recency-shrunk
baseline against historical meetings with the current opponent.

The H2H rate modifier is shrunk by:
1. historical meeting sample size; and
2. tactical similarity/relevance.

Manager, formation, block/pressing, defensive personnel, midfield structure
and player role are only used when present. Missing fields reduce coverage
rather than becoming assumed similarity.

The modifier is bounded. Visible classification is exactly SUPPORTIVE,
NEUTRAL, ADVERSE or INSUFFICIENT SAMPLE.

## Link-up dependency

`evaluate_linkup` supports directional teammate dependency using:
- shared matches/minutes;
- with-player versus without-player xGI process;
- direct connection rows when a governed source eventually supplies them;
- tactical role complementarity;
- current-vs-historical role relevance.

A large old sample is discounted if current roles are different. Direct-link
absence caps confidence, and pure correlation without a process/tactical bridge
gets zero authority.

`probability_weighted_link_modifier` marginalizes the link with the existing
teammate P(start), rather than treating the teammate as certainly present or
absent.

`evaluate_multi_player_chain` uses a bounded chain/intact-probability
approximation with a governed maximum length. It does not enumerate an
unbounded availability state space.

## P1.3 integration

`project_player_fixture` retains P1.3 ownership. Contextual dynamics supplies
optional bounded goal and assist rate multipliers before the existing joint
event/point PMF is built.

When contextual evidence is absent, both multipliers are exactly 1.0 and the
old numerical path is preserved.

Because the adjustment happens before the PMF, it propagates coherently into
goal/assist/return/2+ return/haul/blank probabilities, xPts, variance and
downstream captain/transfer/mini-league decisions rather than changing only a
headline mean.

## Production routing

`prediction_service.py` passes the already-existing
`data/stats/playermatchstats_current.json` rows into the projection consumer.
Missing player-match rows remain optional enrichment and never block the base
projection.

No new provider is created. Direct player-to-player connection rows are
explicitly unavailable in current production routing and are not fabricated.

## Visible reporting

The existing 19-section DEEP backbone is unchanged.

Where player-level detail is material,
`build_contextual_player_blocks` exposes nested:
- `OPPONENT-SPECIFIC MATCHUP`
- `LINK-UP / COMBINATION NETWORK`

Zero-confidence pairs are suppressed.

## Post-match validation

Post-match review must compare the pre-match hypothesis to observed process:
shot quality, box access, role/minutes, expected combination behavior,
with/without change and result-vs-process divergence. The next scan remains
full-universe-first and is not limited to scorers/assisters.

## Acceptance fixtures

Haaland versus Sunderland and Brobbey / Le Fee are test fixtures, not runtime
special cases.

The Haaland fixture asserts that zero historical goals plus strong process does
not produce a strong adverse rule from scoreline alone.

The Brobbey / Le Fee fixture asserts that a single shared match cannot create a
strong dependency even when a creator-finisher connection is observed.


## Runtime completion audit

The bounded completion wires qualified multi-player chains into the same
contextual path already consumed by P1.3. It does not create another model
owner.

Runtime flow:

```text
existing qualified directional pairwise edges
  -> bounded directional chain construction
  -> existing P1.1 upstream P(start)
  -> chain intact probability
  -> weakest-link confidence
  -> bounded chain multiplier
  -> existing pairwise + chain contextual multiplier
  -> existing P1.3 goal/assist rates
  -> existing joint event/point PMF
  -> probabilities, xPts, variance
  -> existing downstream XI/captain/transfer/MC/mini-league consumers
```

Chains are constructed only from qualified edges, with a configured maximum
number of incoming edges per node, maximum chain length and maximum chains per
target. Direction discontinuity, cycles, weak/incompatible edges and candidates
beyond the governed maximum fail closed.

For A -> B -> C, chain availability uses the existing P1.1 probabilities of A
and B. A low or zero P(start) on B therefore weakens the higher-order effect on
C rather than treating the chain as intact.

The visible LINK-UP / COMBINATION NETWORK block keeps the existing DEEP
structure and now distinguishes PAIRWISE LINKS from MULTI-PLAYER CHAINS.

## Prior-season factual artifact audit

The runtime V6 artifact catalog and effective source registry were audited
before any source change.

Evidence observed in the governed `runtime-data-v6` publication:

- `data/v6/evidence/artifact_catalog.json` contains no prior-season EPL
  player-match artifact suitable for opponent-specific player H2H.
- `data/v6/current/statsbomb.json` is the StatsBomb Open Data catalogue lane;
  the registered request is the competitions catalogue, not prior-season
  Premier League player-match events.
- `data/v6/normalized/sources/understat.json` is current-season EPL player
  aggregation. At the audited snapshot it contains 416 player records and zero
  fixture records, not prior-season player-match observations.
- `data/v6/normalized/sources/vaastav_fpl.json` is the configured 2026-27
  mirror. It contains current-season player aggregates and 380 fixture rows,
  but no prior-season player-match history.
- `data/v6/health/historical_backfill.json` is mini-league/manager history for
  the current season and is not player-match factual evidence.
- Other artifact-catalog history paths are mini-league history, not historical
  EPL player performance rows.

Therefore no new provider was added and current runtime truth is:

```text
OPPONENT HISTORY SCOPE: CURRENT-SEASON ONLY
PRIOR-SEASON MATCHUP:
UNAVAILABLE — NO GOVERNED MATCH-LEVEL FACTUAL SOURCE
```

The code keeps a separate `opponent_history_rows` input for a future governed
artifact. Those rows are never included in the GW1-current trajectory. When
present, older rows receive additional season-age decay and tactical relevance
discount before sample shrinkage.

## Current Sunderland factual evidence posture

The governed current V6 Understat normalization resolves Brian Brobbey to
Official element 552 and Enzo Le Fée to Official element 542. The audited
current-season aggregate snapshot has match/minute/xG/xA evidence for both.
Those aggregate rows do not by themselves prove direct creator-recipient
linkage or prior-season H2H.

Accordingly the runtime may use actual current-season player-match rows when the
existing `playermatchstats_current` consumer surface supplies them, but it
must retain the direct-link confidence cap when recipient-level evidence is not
available. A latest haul alone cannot promote Brobbey-Le Fée to a strong
dependency.

## Completion acceptance

Permanent deterministic coverage now extends through K-V:

- K: strong A -> B -> C chain reaches P1.3 distribution;
- L: middle node P(start)=0 materially weakens downstream projection;
- M: P(start)=0.5 lies between intact and broken states;
- N: incompatible direction cannot form a chain;
- O: cycles are rejected;
- P: chain confidence is governed by the weakest meaningful edge;
- Q: candidates beyond the configured maximum chain length fail closed;
- R: pairwise-only behavior remains numerically stable;
- S: prior-season H2H may affect matchup history but not current trajectory;
- T: old system/manager mismatch is discounted;
- U: zero goals with strong xG is not adverse from result alone;
- V: absent prior-season factual data produces explicit CURRENT-SEASON ONLY /
  UNAVAILABLE scope.


## Pairwise vs chain anti-double-count completion

Pairwise and chain now have explicit ownership.

For a terminal edge B -> C, the existing pairwise path owns the direct
P(start)-marginalized effect on C. A higher-order chain A -> B -> C may use
B -> C as evidence and as its terminal continuity bridge, but it does not
multiply the direct B -> C effect again.

Runtime decomposition exposes:

- `raw_chain_multiplier`;
- `overlapping_pairwise_multiplier`;
- `incremental_chain_multiplier`;
- `effective_chain_multiplier`;
- `anti_double_count_applied`;
- `overlap_edge_ids` / `overlapping_edges`;
- `chain_incremental_confidence`;
- per-channel raw, overlap-removed and incremental contributions.

The effective chain contribution is the neutral-relative upstream residual.
For a finisher target the pairwise goal contribution is applied once, while
the chain goal contribution is only the residual upstream interaction. Assist
uses the existing secondary-channel square-root semantics. Creator targets
retain assist-primary semantics.

Chain-intact P(start) remains authoritative. When a required middle node has
P(start)=0 the higher-order residual becomes neutral, but the existing pairwise
present/absent marginalization remains intact. Thus absence is not penalized
twice.

Within one target context, upstream edge IDs already consumed by a stronger
chain are not blindly multiplied again by another overlapping chain. Different
upstream evidence may still contribute through separate chains, and different
targets may reuse the same upstream relationship.

The final contextual cap remains unchanged and is explicitly not considered an
anti-double-count mechanism.
