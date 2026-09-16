# R3 RISE20 / FALL20 Deterministic Engine

## Scope
R3 implements deterministic downstream construction of canonical RISE20 and FALL20 rows on top of the merged R2 row contract. V6 remains factual-only. R3 does not implement R4 section-level hard-contract expansion, R5 anti-fabrication enforcement, R6 actual rendered-body parsing, or R7 report-delivery recovery.

## Authority
- Library `/FPL/FPL_MASTER_SPEC_V11.txt` J1 remains the single canonical 17-field row schema.
- Library Spec V11 J2 defines the R3 deterministic selection semantics.
- `src/runtime_v6/domains/report_plane/delivery_integrity.py` remains the executable row-schema validator owner from R2.
- `src/runtime_v6/domains/report_plane/rank20_engine.py` owns R3 selection, ordering, ownership tagging, ETA rendering, and snapshot binding.

## Deterministic selection
For a COMPLETE normalized predictor snapshot:

- denominator is the current full Official FPL universe;
- every universe `element_id` must have exactly one predictor row;
- `RISE20` selects the 20 highest `projection_offset_0_percent`, descending;
- `FALL20` selects the 20 lowest `projection_offset_0_percent`, ascending;
- equal projection values use stable `element_id` ascending as the final tie-breaker;
- input order cannot change output;
- current progress, ownership, Team-Needs status, latest points, and user-mentioned names do not silently alter Top20 ordering.

## Enrichment contract
Each selected row is materialized into the R2 J1 schema:

- Official identity/name/current price/current ownership come from the current universe row;
- `ownership_tag` is derived from current authoritative OUR15 IDs;
- predictor progress/projection/cycle/urgency/confidence remain MODEL inputs;
- R3 does not invent urgency or confidence thresholds absent from authority/config;
- non-empty upstream `eta_human` is preserved;
- when ETA text is absent but `predicted_change_at` is valid, the model timestamp is rendered in Asia/Jakarta;
- when timing is unknown, `NO RELIABLE ETA` is emitted rather than an invented clock time;
- all 40 rows bind to one `source` + timezone-aware `observed_at` + SHA-256 `raw_payload_hash` snapshot lineage.

## Fail-closed conditions
R3 refuses a COMPLETE result on:

- universe or predictor missing/duplicate stable IDs;
- predictor coverage smaller than the current universe;
- predictor rows outside the current universe;
- missing/non-finite projection or progress values;
- missing cycle/urgency/confidence labels;
- invalid model timestamps;
- invalid snapshot metadata;
- mixed predictor snapshot provenance;
- universe smaller than the exact 40-row disjoint Top20/Bottom20 requirement;
- any generated row that fails the R2 `validate_rank20()` contract.

Partial/degraded source recovery belongs to the later report recovery/degradation layer and must not be simulated by silently shrinking the denominator inside R3.

## TDD proof
R3 was developed test-first:

1. commit `42b1e4ca3bb205155f1e40232256cf9ce6ba4b16` added acceptance tests before the engine existed;
2. the full unit/regression suite failed in the expected RED state;
3. commit `5c5c7445d9e53c154e3f21f70b227293439cee64` added the minimal engine;
4. the same full unit/regression suite passed on the implementation head.

The tests use synthetic players only and prove full-universe scanning, exact top/bottom 20, stable tie-breaking, input-order invariance, ownership tagging, truthful ETA behavior, single-snapshot provenance, and fail-closed coverage/identity handling.
