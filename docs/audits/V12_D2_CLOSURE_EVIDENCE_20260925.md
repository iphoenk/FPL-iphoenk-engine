# V12 D2 Closure Evidence — 2026-09-25

Status: CORRECTNESS CLOSED + PERFORMANCE CLOSED
Production oracle: `daf7247c320b1bb61eebd943b23f3ca694b088ef`
D2a source: `b00ffb14e3cc3b7347f5dabb7a4059baa4a6d3f3`
D2 final source: `8309ddaf0da87546bf92e3e9a2ea21e7c409a2a4`
Frozen runtime-data-v6: `9fc2ce5e590518c399765e6fd576bb96db6e5897`

## Correctness closure

Final correctness run: `36078362621` — SUCCESS.

Verified:
- frozen 3,191 adjusted rows and exact rows fingerprint;
- full foundation fingerprint unchanged;
- walk-forward payload fingerprint unchanged;
- raw `float.hex()` semantic trace unchanged;
- five explicit `PYTHONHASHSEED` values stable;
- input immutability;
- exact `gw < target_gw` / `gw == target_gw` leakage contract;
- unsorted input preserves scalar row order;
- same-GW DGW rows do not enter one another's history;
- mixed normalized-position representations (`gk` / `GKP`, `mid` / `MID`) preserve scalar behavior;
- cached position history is a tuple and therefore cannot be list-mutated by consumers.

### Evaluated-row reconciliation

Frozen reference trace:
- total test rows: **2,598**
- skipped before any `_rate90`: **74**
- evaluated rows: **2,524**

The 74 skipped rows have empty `player_train` and hit the existing:
`if not player_train or not position_train: continue`

Therefore:
- oracle position-rate calls = **2,524**
- oracle player-level calls = **7,572 = 3 × 2,524**
- oracle total = **10,096**
- D2 final total = **7,588**
- D2 position misses = **16**
- repeated position-rate calls removed = **2,508**

The final correctness gate proves that the D2 call trace is exactly the scalar trace with only repeated position-rate calls removed.

## Position-key authority

The scalar oracle normalizes both sides with the same `_position()` function:

```python
position = _position(actual.get("position"))
_position(row.get("position")) == position
```

D2 indexes by:
```python
rows_by_position[_position(row.get("position"))]
```

Thus the cache/index equivalence class exactly matches the scalar predicate.

Current normalization:
- case-insensitive;
- `GK` and `GKP` -> `GK`;
- other string labels upper-cased;
- numeric element types are NOT translated to labels.

## Performance closure

Performance run: `36078691709` — SUCCESS.

All absolute and relative measurements were executed in **one GitHub Actions job on the same hosted runner**, so CPU metadata is identical by construction:

- CPU: **AMD EPYC 7763 64-Core Processor**
- `nproc = 4`
- Ubuntu image: `20260920.314.1`
- Python: 3.12.14
- GC enabled
- `sys.gettrace() is None`
- `sys.getprofile() is None`
- rows are native `builtins.dict`

### Harness A — Stage C production-like

Same-host oracle:
- walk-forward median: **2.927355 s**
- full foundation median: **3.563829 s**

D2 final:
- walk-forward median: **0.074320 s**
- full foundation median: **0.698040 s**

Frozen gates:
- walk-forward <= 0.55 s: **PASS**
- full foundation <= 1.25 s: **PASS**

Observed Stage C walk-forward reduction from the same-host oracle is approximately **97.46%**.

### Harness B — 13 interleaved triads

Median direct walk-forward:
- oracle: **2.947526 s**
- D2a: **1.559846 s**
- D2 final: **0.074458 s**

Paired median oracle -> D2 final reduction:
- **97.47699%**
- frozen requirement: >= 82%
- **PASS**

Median-ratio reduction:
- **97.47388%**

### D2a / D2b diagnostic attribution

Observed:
- oracle -> D2a gain: **1.387679 s**
- D2a -> D2 final gain: **1.485388 s**

Pre-registered refined-harness diagnostic expectation:
- D2a scan-removal gain: ~1.17 s
- D2b position-reuse gain: ~0.73 s

The D2b gain is materially larger than the pre-registered 0.73 s estimate. This is now explained by a modeling omission, not an unexplained candidate cost.

The pre-registered 0.73 s estimate counted:
- repeated position `_rate90` (~0.666 s in the refined timing);
- repeated position starter sum (~0.063 s).

It did **not** include the residual D2a work:
- D2a replaces a full-`train` position scan with a smaller `rows_by_position[position]` scan, but still performs that smaller `gw < target_gw` filter once per test row.
- D2b caches the exact ordered position history by `(target_gw, normalized_position)`, eliminating those repeated subset filters as well.

On the same-host runner, this additional saved position-history filtering accounts for the larger D2b gain. Directionally this is consistent with the earlier refined timing, where position-history construction was itself material.

Therefore the cost model was incomplete in attribution, while the implementation behavior is consistent with the allowed D2 design.

### Diagnostic floor

The pre-registered diagnostic said a well-shaped candidate might land around 0.10–0.15 s Stage C WFV, with ~0.09 s as a scaled structural estimate before new index/cache overhead.

Observed:
- **0.0743 s**

There is therefore no unexplained excess cost before merge. The candidate is slightly below the earlier structural estimate, confirming that estimate was not a mathematical lower bound and included instrumentation/control effects.

## GC gate

Full-foundation median collections:

- generation 0: oracle 50, candidate 51, limit 60 — PASS
- generation 1: oracle 5, candidate 5, limit 6 — PASS
- generation 2: oracle 0, candidate 0 — PASS

No generation increases by more than the frozen 20% allowance.

## RSS gate

Same-host separate-process Stage C probes:

- oracle peak RSS: **148,132 KiB**
- candidate peak RSS: **147,916 KiB**
- delta: **-216 KiB**
- allowed increase: <= 8,192 KiB
- **PASS**

## Historical ~1.8x harness discrepancy

New same-host evidence materially narrows the historical question.

On this runner:
- Stage C oracle WFV: 2.927355 s
- direct interleaved oracle WFV: 2.947526 s
- ratio is approximately 0.993

For D2 final:
- Stage C WFV: 0.074320 s
- direct interleaved WFV: 0.074458 s
- ratio is approximately 0.998

Thus, when the code is measured on the **same host**, Stage C and direct A/B timings agree closely. This strongly argues against a systematic ~1.8x harness slowdown.

The old ~1.8x D1 discrepancy is therefore most consistent with different hosted-runner hardware/runtime allocation, but this remains an attribution rather than proof because the historical A/B run did not record CPU model / nproc.

All D2 performance runs now record CPU model and nproc to prevent recurrence.

## Closure

D2 final source `8309ddaf0da87546bf92e3e9a2ea21e7c409a2a4` has:

- correctness: CLOSED
- position-key premise: CLOSED
- row-order preservation: CLOSED
- DGW/leakage: CLOSED
- normalized-position equivalence: CLOSED
- cached-history immutability: CLOSED
- absolute Stage C performance: CLOSED
- paired relative performance: CLOSED
- GC gate: CLOSED
- RSS gate: CLOSED

No production merge is implied by this memo. Repository governance / required verification remains the next gate before merge.
