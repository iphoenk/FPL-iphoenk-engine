# R2 Authority / Contract Alignment

## Scope
R2 closes the authority drift exposed by the 16 Sep 2026 17:29 false-PASS without implementing R3 generation logic or R6 visible-body parsing.

R2 keeps V6 factual-only. The report plane remains downstream ChatGPT/report-contract territory.

## Authority alignment
Active authorities after R2:

1. Library `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt`
   - operational and fail-closed delivery authority;
   - synchronized to Library version 6 during R2 closeout.
2. Library `/FPL/FPL_MASTER_SPEC_V11.txt`
   - methodology/report-schema authority;
   - synchronized to Library version 2 during R2 closeout.
3. `FPL Master Monitor`
   - retains only the minimal anti-drift safety kernel;
   - keeps the existing hourly `:30` Asia/Jakarta schedule and enabled state;
   - references current Spec V11 J1 instead of duplicating the 17-field schema.
4. Repository executable contract
   - `src/runtime_v6/domains/report_plane/delivery_integrity.py` is the single production schema registry/validator owner;
   - `src/runtime_v6/domains/report_plane/report_compute.py` consumes that canonical contract for semantic fingerprinting.

## Canonical RISE20 / FALL20 row contract
A valid row contains these keys:

`rank`, `element_id`, `player_name`, `current_price`, `ownership_percent`, `ownership_tag`, `direction`, `current_progress_percent`, `projection_offset_0_percent`, `predicted_change_cycle`, `predicted_change_at`, `eta_human`, `model_urgency`, `confidence`, `source`, `observed_at`, `raw_payload_hash`.

Executable authority is `RANK20_REQUIRED_FIELDS` in `delivery_integrity.py`; this document is descriptive and must not become an alternate registry.

Required behavior:

- exact 20 rows remains mandatory;
- rank is 1..20 in order;
- identity is present and unique;
- direction matches RISE20/FALL20;
- ownership tag is explicit;
- timing fields may not silently disappear;
- provenance is explicit and a COMPLETE row requires a SHA-256 payload hash;
- count-only 20/20 is never sufficient for PASS;
- compute fingerprinting includes material row semantics, not only player identity.

## Regression closure
The R1 golden incident is retained: an exact-20 RISE/FALL payload containing only identities must fail because mandatory timing/schema/provenance information is missing.

R2 additionally covers:

- missing ETA/provenance field evidence;
- rank and direction mismatch;
- missing ownership tag;
- valid schema-complete RISE20 and FALL20;
- fingerprint change when projection/timing/urgency/provenance changes with identical player IDs.

Legacy tests that previously encoded count-only rank rows were migrated to one shared test-only schema fixture rather than weakening the production validator.

## Verification evidence
Code verification head before this documentation-only closeout commit:

`f691b8948e25883b4b04c9a652ccf4729f0c876f`

On that exact code head GitHub reported all relevant PR workflows successful:

- Repository naming policy
- FPL V6 CI contracts
- Repository governance
- V3 CI, including the full unit/regression suite

Library read-back confirms Runtime Contract now rejects count-only 20/20 in Full/Deep, 05:30 Price and Final QA, and records the 16 Sep 2026 17:29 false-PASS as a named blocked regression. Spec V11 J1 is the sole Library definition of the 17-field RISE/FALL row schema.

## Explicit non-goals / remaining waves
R2 does **not** solve:

- R3 deterministic full-universe selection, sorting, tie-breakers, ETA generation, enrichment or rank-row production;
- R6 actual rendered-body field parser / visible-row semantic inspection.

Those remain separate waves. R2 only makes the contract coherent and fail-closed before those later capabilities are added.
