# V12 Stage 1 Analytics Completion Audit

Observed: 2026-09-21 20:07 WIB  
Controlled DEEP run: 35597594711  
Initial main: `4955f91ab2ba560a0221a4d42a6fd672eafcd277`  
Runtime-data-v6: `81f7fc2260eac1e5f8b00e2b8c72e789f2734500`

## Exact root cause

The earliest broken analytics node is the integrated occurrence invocation of
P1.1/P1.3. The runner passed `horizon=5`, while the P1.3 owner publishes
`[1,3,5,10,15]` and explicitly rejects a runtime horizon shorter than its
maximum published horizon. The resulting exception was:

`RuntimeError: projection runtime horizon cannot be shorter than published horizons`

Everything from Official Role Evidence through P1.6, ALL15, P1.7, the
canonical 20/25/30/25 universe, package utility and Monte Carlo was therefore
downstream-not-run/partial. PRE_RENDER then correctly failed XI, BENCH and
WATCHLIST20. CANONICAL_RENDER itself passed the complete 20-section catalog,
so renderer completeness is not the root cause.

## Second-order foundation defect

Even without the horizon exception, the controlled runner supplied an empty
historical prior, empty `player_features_payload`, empty
`player_match_rows` and empty `opponent_history_rows`. Therefore changing
5 to 15 alone would have removed the exception while leaving the requested
analytics foundation materially incomplete.

The repair removes the runner-owned horizon entirely and wires a read-only
V12 foundation consumer over V6 normalized facts. The existing Vaastav V6
provider is extended with its factual season `gws/merged_gw.csv` request and
the V6 source-native normalizer publishes deterministically joined
`player_matches`. V12 rejects unmapped/conflicted player, fixture or
opponent identities and refuses stale/incomplete match history.

## A-F classification

| Capability | Class | Stage 1 finding |
|---|---|---|
| Full-universe P1.1/P1.3 | B/C | Owners exist; occurrence foundation was not wired |
| GW1-current match rows | F -> B | Current runtime lacks normalized merged_gw; bounded V6 request/normalizer added |
| Recency | A/B | Exponential recency exists; opponent-weight product is not yet implemented |
| Opponent adjustment | D | Existing strength model is not the requested latent multidimensional opponent model |
| Coach/formation/role | C/F | Code exists, governed production factual coverage is incomplete |
| Change point | D | Heuristic role/start shifts exist; no formal regime posterior/P(role stable) |
| 20/25/30/25 | A/C | Authority weights correct; numeric full-universe producer incomplete |
| Bayesian | D | Shrinkage exists, full hierarchical posterior uncertainty/credible intervals incomplete |
| Distribution selection | D | Existing event distributions are governed but not selected target-by-target from dispersion/zero diagnostics |
| P1.1 xMins | C/D | Native owner exists; requested six-state split and match-row context incomplete |
| Renderer | A | Catalog complete; did not cause analytics failure |
| PRE_RENDER | A | Correctly rejected missing XI/BENCH/WATCHLIST20 compute outputs |

## Source-feature status

The new Vaastav match-level normalizer can supply: GW, fixture, element,
opponent, H/A, minutes, start flag, xG/xA/xGI/xGC, goals/assists, clean sheet,
goals conceded, saves, penalties saved/missed, cards, bonus/BPS, FPL points,
DefCon-related totals, recoveries/tackles and provenance.

It does **not** invent sub minute, actual tactical role, npxG, shots/SoT,
shots in box, big chances, box touches, key passes, crosses, team shares,
PSxG/xGOT, goals prevented, errors, coach, formations, in/out-of-possession
shape, press/block, width, transition/build-up style or substitution
tendencies. Those remain explicit factual-source gaps.

## Stage 1 acceptance

Stage 1 is **NOT GREEN** yet. The exact root cause is fixed at the invocation
contract and match-level factual wiring is implemented, but the remaining
statistical/tactical requirements are substantive, not renderer defects.
Stage 2 has not started.

The machine-readable ledger and gap assignment live in
`control/fpl_master_v12/FPL_MASTER_STAGE1_ANALYTICS_AUDIT.json`.
