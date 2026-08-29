# V3 P0 Decision-Quality Audit

## Scope

This note records the P0 findings from the V3 improvement review. It does not treat V4 as calibration truth and does not change Official FPL or user authority.

## 1. GW2 -> GW3 wildcard state leakage

Confirmed root cause: `config/locked_squad.json` retains the historical/manual WC draft state with `wildcard_active=true`, `authoritative_phase=pre_deadline_wc`, and `target_gw=2`. The previous lineup chip resolver checked the first two fields but did not require the lock target to match the current `planning_gw`. When planning advanced to GW3, the old GW2 lock could therefore still emit an active wildcard.

Fix: planning chip activation is now explicitly GW-scoped. When an explicit `target_gw` exists and differs from `planning_gw`, the chip is suppressed and the output publishes `stale_chip_override_suppressed=true`. Historical submitted chip state is not rewritten. Legacy untargeted locks retain their prior behavior for backward compatibility.

## 2. xMins / start-security decomposition

Audit result: the active V3 xMins model already computes mutually exclusive start, bench and DNP probabilities, overall availability, conditional starter minutes, conditional bench minutes, and expected minutes as a probability-weighted total. The weakness was mainly contract visibility and invariant enforcement rather than absence of the decomposition.

Improvement: V3 now publishes `expected_minutes_if_start`, `overall_availability`, `probability_sum`, and `expected_minutes_components`, while preserving existing `expected_minutes`, `starter_minutes_if_start`, `bench_minutes_if_used`, and probability fields. Runtime fails if the probability sum is materially different from 1 or if published expected minutes cannot be reconciled to the explicit probability components.

No mechanical xMins cap/boost or V4-matching adjustment was introduced.

## 3. GK/DEF projection inflation audit

The active production projection is `historical_projection` + `projection_components`, not the legacy simple projection helper. Its fixture mean is decomposed into appearance, attack, clean-sheet, saves, defensive contribution and bonus terms.

The audit did not find an active tactical xPts double count. Tactical matchup enrichment is attached after base projections and is currently advisory-only. A new fail-closed signature guard captures all decision-bearing player/GW xPts before tactical enrichment and verifies they are unchanged after enrichment.

To diagnose defensive uplift without forcing V3 toward V4, V3 now publishes position-level non-mutating diagnostics. For GK/DEF/MID/FWD it reports mean xPts per fixture, mean component contribution, defensive-component share, and ablation means with clean-sheet, saves, defensive contribution or bonus removed one at a time.

This makes the material contributors observable. Calibration changes must use settled realized validation evidence; V4 is explicitly not treated as ground truth.

## Acceptance intent

- GW2 wildcard history remains historical truth.
- GW3 planning cannot inherit the GW2 wildcard solely from the stale targeted lock.
- Existing xMins output remains backward-compatible while its probability derivation becomes auditable.
- Projection diagnostics are observational and do not mutate xPts.
- Tactical enrichment cannot silently alter xPts.
- Gate0, DSS, Official authority, user authority, roster contracts, watchlist contracts and report scheduling are unchanged by this P0 patch.
