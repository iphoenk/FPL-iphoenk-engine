# V12 D2 Pre-Implementation Premise Audit

Date: 2026-09-25
Status: RECORDED BEFORE POSITION CACHE IMPLEMENTATION
Production base: `daf7247c320b1bb61eebd943b23f3ca694b088ef`
D2 branch: `perf/v12-d2-walkforward-index-cache-20260925`

## 1. Expanding-window authority

The scalar oracle is GW-based:

- `train = [row for row in clean if gw < target_gw]`
- `test = [row for row in clean if gw == target_gw]`

There is no `<=` cutoff and no row-index cutoff.

Same-GW / DGW-like rows remain test observations together and MUST NOT enter one another's historical state.

## 2. Position history is NOT leave-one-player-out

Current scalar code:

```python
position_train = [
    row
    for row in train
    if _position(row.get("position")) == position
]
```

There is no `player_id != pid` predicate.

Therefore, for a fixed `target_gw` and normalized `position`, every test row in that fold observes the same ordered `position_train` sequence.

This is materially different from the hierarchy team/role LOO paths and is the factual basis for position-level reuse in D2.

## 3. Recency reference point

Current recency weights are:

```python
0.5 ** (max(0, target_gw - _i(row.get("gw"))) / 2.5)
```

They depend only on:
- `target_gw`; and
- each historical player row's `gw`.

They do NOT depend on kickoff, fixture identity, match id, venue, or another attribute of the current test row.

This means two same-GW/DGW test observations for the same player would use the same player historical weights if such reuse exists. On the frozen snapshot, measured unique `(target_gw, player)` keys equal the evaluated test-row count (2,598), so there is effectively no player-key reuse to exploit there.

## 4. Exact _rate90 argument contract

Current signature:

```python
def _rate90(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    *,
    weights: Sequence[float] | None = None,
) -> float | None:
```

Current position call:

```python
pos_rate = _rate90(position_train, "xgi") or 0.0
```

Therefore the complete semantic input for the current position-rate computation is:
- the ordered `position_train` rows;
- `field == "xgi"`;
- `weights is None`, which means an implicit all-1.0 weight sequence.

For current code, `(target_gw, normalized_position)` is sufficient to identify the ordered position row sequence, while `"xgi"` and default weights are fixed call-site constants. An implementation SHOULD still make those constants explicit in the cache/helper contract rather than silently assuming a generic position cache is valid for arbitrary future fields/weights.

Position starter sum uses only the same ordered `position_train` rows and `row.get("starter")`; it has no additional test-row-dependent input.

## 5. Row-order preservation rule

The scalar oracle preserves original `clean` input order:

1. `clean` is constructed in input order;
2. `train` filters `clean` without sorting;
3. `player_train` and `position_train` filter `train` without sorting.

A safe D2 index MUST therefore be built by iterating `clean` once in original order and appending rows to per-player/per-position lists in that same order. Historical views must then be produced by filtering those smaller lists with `gw < target_gw`.

D2 MUST NOT:
- concatenate GW buckets in sorted-GW order;
- sort player or position histories;
- use bisect over a reordered list unless it separately proves the resulting row sequence is byte-for-byte/order-identical to the scalar subsequence.

The unsorted-input correctness fixture is mandatory.

## 6. Harness discrepancy and hardware logging

Measured harness ratios are not identical:

- post-D1 Stage C walk-forward baseline: ~2.726 s;
- refined instrumented walk-forward: ~1.965 s;
- ratio: ~1.39.

Separately, D1 hierarchy showed ~1.78-1.80x historical Stage-C-vs-A/B differences.

The 96.77% removable share was measured in the refined non-cProfile instrumentation, not directly in the original Stage C wrapper. Translating that share to the Stage C baseline assumes the harness slowdown is approximately multiplicative across the relevant work. This is plausible but not proven.

Starting with every D2 correctness/performance run, evidence MUST record:
- `/proc/cpuinfo` first `model name`;
- `nproc`;
- Python version;
- runner image/version;
- `sys.gettrace()`;
- `sys.getprofile()`;
- GC state;
- row count/fingerprint;
- native row type(s).

## 7. Pre-registered diagnostic prediction

Before any D2 candidate timing is observed:

- refined structural floor = ~3.23% of measured walk-forward;
- scaled to the authoritative Stage C 2.726 s baseline, expected pure retained work is approximately **0.09 s**, before new index/cache overhead;
- a well-shaped implementation may therefore plausibly land near **~0.10-0.15 s** Stage C walk-forward if indexing/cache overhead is small.

This is a diagnostic prediction, NOT the merge gate.

If a candidate passes the frozen Stage C absolute gate but lands materially above ~0.15 s, the unexplained cost MUST be decomposed before merge rather than dismissed as runner noise.

## 8. Implementation sequencing

D2 implementation is split deliberately:

**D2a — order-preserving index / full-scan removal**
- create invocation-local per-player and per-position ordered lists from `clean`;
- replace per-test-row full-`train` scans with `gw < target_gw` filters over the smaller ordered lists;
- NO position-rate or starter-sum cache yet.

**D2b — position-level reuse**
Only after D2a raw oracle/fingerprint correctness is green:
- reuse exact position historical state by `(target_gw, normalized_position)`;
- current rate contract is `field="xgi", weights=None`;
- starter sum uses the same position history;
- raw `float.hex()` and row-sequence fingerprints remain mandatory.

This sequencing isolates scan removal from position memoization and makes attribution auditable.

## 9. Evaluated-row count reconciliation

The frozen snapshot produces **2,598 test rows** in the walk-forward reference trace, but **74 rows are skipped before any `_rate90` call** because `player_train` is empty. Therefore:

- total test rows traced: **2,598**
- skipped before rate evaluation: **74**
- evaluated rows: **2,524**
- scalar position `_rate90` calls: **2,524**
- scalar player-level `_rate90` calls: **7,572 = 3 × 2,524**
- total scalar `_rate90` calls: **10,096**
- D2b candidate `_rate90` calls: **7,588 = 7,572 player-level + 16 position cache misses**
- repeated position-rate calls removed: **2,508 = 2,524 - 16**

This resolves the earlier apparent inconsistency between 2,598 unique `(target_gw, player)` keys and 2,524 position-rate calls. The cache remains lazy: rows that fail the `not player_train or not position_train` guard do not populate the rate cache.

## 10. Normalized-position equivalence proof

The scalar oracle computes:

```python
position = _position(actual.get("position"))
position_train = [
    row
    for row in train
    if _position(row.get("position")) == position
]
```

D2 builds its position index with the **same** normalization function:

```python
rows_by_position[_position(row.get("position"))].append(row)
```

Thus the cache/index equivalence class is exactly the oracle predicate's equivalence class.

Current `_position()` behavior:
- case-insensitive via `str(...).upper()`;
- `GK` and `GKP` both normalize to `GK`;
- other strings normalize by upper-casing only;
- numeric `element_type` values such as `1` normalize to `"1"`, not to `GK`.

Therefore a mixed-representation regression fixture must use representations the current normalizer itself treats as equivalent, such as `gk` / `GKP` and `mid` / `MID`. Numeric-vs-label equivalence is outside the current function contract and must not be invented by D2.

## 11. Cached position-history immutability

Current consumers of `position_train` are read-only:
- `_rate90()` iterates rows and does not mutate the sequence or rows;
- starter-rate computation iterates `row.get("starter")`;
- `len(position_train)` is read-only.

To make this invariant enforceable rather than merely observed, D2 stores cached position history as an invocation-local **tuple** while preserving the exact row-object order. This prevents append/sort/in-place list mutation by future consumers without changing the scalar-observed iteration order.

