# R3 RISE20 / FALL20 Deterministic Engine

## Scope
R3 implements deterministic downstream construction of canonical RISE20 and FALL20 rows on top of the merged R2 row contract. V6 remains factual-only. R3 does not implement R4 section-level hard-contract expansion, R5 anti-fabrication enforcement, R6 actual rendered-body parsing, or R7 report-delivery recovery.

## Authority
- Library `/FPL/FPL_MASTER_SPEC_V11.txt` J1 remains the single canonical 17-field row schema.
- Library Spec V11 J2 defines the R3 deterministic selection semantics.
- `src/runtime_v6/domains/report_plane/delivery_integrity.py` remains the executable row-schema validator owner from R2.
- `src/runtime_v6/domains/report_plane/rank20_engine.py` owns R3 selection, ordering, ownership tagging, ETA rendering, and snapshot binding.
- `src/runtime_v6/domains/report_plane/report_compute.py::build_report_compute_contract_from_universe()` is the canonical R3 construction entrypoint. It invokes the full-universe engine before the existing compute validator. `build_report_compute_contract()` remains a low-level validation primitive for already-materialized compatibility callers and tests, not the preferred new-construction path.

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
3. commit `5c5c7445d9e53c154e3f21f70b227293439cee64` added the minimal engine and made the engine acceptance suite GREEN;
4. commit `6ddf5b48f1e54fbbf3f2a529ac16a7358bd1c330` added a second RED test proving `report_compute` still lacked the canonical engine-backed entrypoint;
5. commit `1de94a166c55553aaa93891128e3157d047eab6c` added that canonical entrypoint and returned the full unit/regression suite to GREEN;
6. subsequent cleanup removes unused registry-like constants and simplifies ETA input handling without changing selection semantics.

The tests use synthetic players only and prove full-universe scanning, exact top/bottom 20, stable tie-breaking, input-order invariance, ownership tagging, truthful ETA behavior, single-snapshot provenance, fail-closed coverage/identity handling, and canonical report-compute integration without hardcoded player names.

## V12 source-health semantics — 2026-09-21T05:45:00+07:00

A healthy predictor result does not require a threshold crossing. `NO_CROSSING_WITHIN_GOVERNED_HORIZON` is a valid terminal result when the current predictor snapshot is healthy, exact-20 selection is supportable, official cycle clocks are derivable, and the governed horizon is valid. In that state, expected-change-cycle fields remain truthfully unavailable because no crossing is predicted; the section remains COMPLETE rather than being marked DEGRADED merely for the absence of a crossing.

DEGRADED is reserved for actual evidence defects such as stale/missing/invalid predictor data, insufficient offset-0 coverage, schema or identity failure, unavailable evidence timestamps/cycle clocks, or `DATE_UNAVAILABLE`. Official FPL factual prices remain independently authoritative and do not inherit degradation from an unrelated predictor/model/plumbing scope.

This amendment changes report-health classification only. It does not change the predictor mathematics, threshold, projection horizon, selection ordering, V6 acquisition, or factual-source ownership.
## AD_HOC mode-equivalent visible rendering — 2026-09-21T07:50:33+07:00

Interactive requests for a Canonical report mode are not presentation-only shortcuts. Requests such as `DEEP sekarang`, `PRICE sekarang`, or a scheduled-format report using current evidence must use the existing AD_HOC report identity and traverse the same pre-render and actual visible-body post-render QA as the equivalent scheduled mode. Scheduler proof is N/A for AD_HOC; visible-content correctness is not.

The R6 visible-body parser remains authoritative for what the user actually sees. RISE20/FALL20 therefore cannot be accepted merely because 20 identities were computed: the rendered rows must expose the governed Rank20 schema, including cycle/ETA fields such as `predicted_change_cycle`, `predicted_change_at`, and `eta_human`. If a supported field disappears during interactive/manual rendering, post-render QA must fail and the same AD_HOC request must be re-rendered rather than delivered as COMPLETE.

This guard changes routing/render conformance only. It does not alter V6, price predictor mathematics, the ±100 model threshold, 0/1/2 projection horizon, daily official price-change cadence, or RISE20/FALL20 ordering.

