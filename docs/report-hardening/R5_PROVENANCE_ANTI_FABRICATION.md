# R5 Provenance and Anti-Fabrication Guard

## Purpose

R5 prevents report-compute from claiming factual, model, inference, weather, optimizer, Monte Carlo, or frontier results without evidence that can be traced to the inputs or execution that produced them.

R5 is a report-plane integrity layer. It does not acquire V6 data, replace R4 section-shape validation, inspect the final rendered body, or perform delivery recovery.

## Authority and ownership

- V6 remains the factual data plane.
- R4 remains the authority for mandatory section structure and cardinality.
- R5 has one validation authority: `src/runtime_v6/domains/report_plane/provenance_guard.py`.
- `report_compute` consumes the R5 result and cannot become compute-ready unless R4 and R5 both PASS.
- `FACT_MODEL` is retained only as a compatibility projection of the R5 partition result. It is not a second validator.
- V3/V4/V5 are never fallback sources.

## FACT / MODEL / INFERENCE contract

The three namespaces must be pairwise disjoint.

FACT rows require:

- `source`
- timezone-aware `effective_at`
- one or more immutable `source_snapshot_ids`

MODEL rows require:

- `model`
- timezone-aware `computed_at`
- one or more immutable `input_snapshot_ids`
- every model input snapshot must belong to the active FACT lineage for the report compute

INFERENCE rows require:

- `basis`
- explicit `fact_refs` and/or `model_refs`
- every reference must resolve to an existing key in the corresponding namespace

The report compute fingerprint includes INFERENCE content, so changing a decision implication changes the fingerprint even when the underlying FACT and MODEL rows are unchanged.

## Weather source proof

A Weather section claiming factual rows must carry `source_proof` with:

- `fact_ref`
- `source`
- timezone-aware `effective_at`
- immutable `source_snapshot_ids`

`fact_ref` must resolve to a declared FACT row. The Weather proof source must match that FACT source, and the proof snapshot IDs must be contained in that FACT's snapshot lineage. A Weather claim cannot borrow a different FACT's otherwise valid snapshot hash.

A truthfully degraded Weather section with no factual rows is handled by the R4 degradation contract and does not need fabricated source proof.

## Optimizer / Monte Carlo / frontier execution proof

Configuration is not execution proof.

When the Optimizer section claims PASS or contains routes, `execution_proof` is mandatory. The optimizer run must have an explicit execution state and run identity. Its output fingerprint is bound to the exact route payload, so post-run route mutation fails validation.

Monte Carlo and frontier components must always be stated explicitly when optimizer execution proof is required. Valid states are:

- `EXECUTED`
- `PARTIAL`
- `NOT_RUN`

`NOT_RUN` requires a reason and does not require fabricated run identity. `PARTIAL` requires a degradation reason. Executed or partial Monte Carlo requires the actual path count; configured simulation count is never accepted as proof that the simulation ran.

Execution evidence uses `run_id`, `method`, timezone-aware `executed_at`, and SHA-256 input/output fingerprints. R5 does not claim that an optimizer input fingerprint is fully reproducible unless the producer actually supplies the canonical input manifest; R5 therefore validates the fingerprint's presence/shape and binds the produced output without inventing missing input lineage.

## Failure behavior

R5 is fail-closed. `report_compute` returns compute failure when the provenance guard fails. No compatibility path auto-fabricates INFERENCE rows, Weather evidence, or execution proof.

Typical deterministic failures include:

- namespace overlap
- FACT or MODEL provenance missing/invalid
- MODEL input lineage not grounded in active FACT snapshots
- INFERENCE references unknown FACT/MODEL keys
- Weather source proof missing or bound to the wrong FACT lineage
- Optimizer execution proof missing
- Monte Carlo/frontier state omitted
- Monte Carlo claimed executed without actual path count
- Optimizer output fingerprint mismatch after route tampering

## TDD evidence

R5 was developed RED first. The initial baseline failed because `provenance_guard` did not exist. After production wiring and caller migration, a second focused RED phase left exactly three intentional failures while 1481 tests passed and 34 were skipped:

1. MODEL inputs could reference a well-formed but unrelated snapshot.
2. Weather proof could borrow another FACT's snapshot.
3. Monte Carlo/frontier could be silently omitted instead of explicitly reporting a state.

The GREEN implementation closes those three gaps without weakening the mandatory R5 contract.

## Explicit boundaries

R5 does not:

- parse or validate the actual visible rendered report body: R6
- implement report retry, rerender, or delivery recovery: R7
- prove a simulation ran from configuration alone
- invent source evidence, optimizer run IDs, Monte Carlo path counts, or frontier completion
