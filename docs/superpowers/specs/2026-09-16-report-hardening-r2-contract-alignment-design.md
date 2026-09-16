# Report Hardening R2 Contract Alignment Design

## Goal
Synchronize the active Runtime Contract, Spec V11, FPL Master Monitor safety kernel, and repository report contract so RISE20/FALL20 completeness means **20 schema-complete rows**, never count-only 20.

## Authority boundary
- Library `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt` remains operational/fail-closed authority.
- Library `/FPL/FPL_MASTER_SPEC_V11.txt` remains report/methodology authority.
- FPL Master Monitor retains only a minimal anti-drift safety kernel and must not duplicate the full mutable schema.
- Repository code is the executable enforcement of the same contract.
- V6 stays factual data-plane only. No selection/ranking/ETA generation redesign belongs to R2.

## Canonical RISE20/FALL20 row schema
Every row must contain these keys:

1. `rank`
2. `element_id`
3. `player_name`
4. `current_price`
5. `ownership_percent`
6. `ownership_tag`
7. `direction`
8. `current_progress_percent`
9. `projection_offset_0_percent`
10. `predicted_change_cycle`
11. `predicted_change_at`
12. `eta_human`
13. `model_urgency`
14. `confidence`
15. `source`
16. `observed_at`
17. `raw_payload_hash`

Semantics:
- `rank` must be 1..20 and unique.
- `element_id` must be present and unique.
- `player_name` must be non-empty.
- `direction` must match the list: `RISE` for RISE20 and `FALL` for FALL20.
- `ownership_tag` must be explicit, at minimum `OWNED` or `NON_OWNED`.
- `current_price` and `ownership_percent` are factual current values when available; their keys must remain present even if a governed degraded state makes the value unavailable.
- `current_progress_percent` and `projection_offset_0_percent` remain model/predictor fields; explicit null is allowed only when the upstream evidence state is legitimately incomplete/calibrating and the report is degraded rather than falsely complete.
- Timing must never disappear. `predicted_change_cycle`, `predicted_change_at`, and `eta_human` keys are mandatory. `predicted_change_at` may be null for `NONE`/uncertain timing, but `eta_human` must remain a non-empty truthful label such as `NO RELIABLE ETA` / `ETA belum valid` rather than an invented clock time.
- `model_urgency` and `confidence` must be explicit.
- Snapshot provenance is represented by `source`, `observed_at`, and `raw_payload_hash`; all keys are mandatory. `raw_payload_hash` must be a SHA-256 hex digest when the row is claimed COMPLETE.

## Executable contract
`validate_rank20()` becomes fail-closed on row schema in addition to exact count and identity. It returns row-specific failures for missing/invalid schema. `build_report_compute_contract()` therefore cannot become PASS when 20 structurally incomplete rows are supplied.

The compute fingerprint must include canonical RISE/FALL row contract content, not IDs only. Changing ETA/projection/urgency/provenance with the same player identities must change the fingerprint.

R2 does not implement deterministic full-universe selection, sorting/tie-breakers, top-20 generation, ETA derivation, projected values, urgency derivation, ownership-tag enrichment, or provenance preservation. Those generation concerns remain R3. R2 only defines and enforces what a valid row must contain.

## Render boundary
R2 does not add the full actual-visible-body parser. That remains R6. Pre-render compute must nevertheless fail closed when rank rows are schema-incomplete. Post-render count-only logic remains a known R6 target and must not be presented as solved by R2.

## Regression requirements
- The R1 17:29 golden fixture must turn GREEN because its 20+20 rows lack required ETA/schema fields and are rejected.
- Exactly 20 identity-only rows must fail.
- One missing required key must fail with row/field evidence.
- Wrong direction must fail.
- Duplicate/missing rank must fail.
- A fully populated 20-row fixture must pass.
- Fingerprint changes when material row contract fields change.

## Cross-authority synchronization
Runtime Contract must explicitly state count + row-schema hard gate in Full/Deep, 05:30, and final rendered-body QA, and name the 16 Sep 17:29 false-PASS regression.

Spec V11 must define the same canonical row fields and timing/provenance semantics.

FPL Master Monitor safety kernel must say count-only 20/20 is never sufficient and every RISE/FALL row must conform to current Spec V11 row schema, without copying the whole mutable schema into the task prompt.
