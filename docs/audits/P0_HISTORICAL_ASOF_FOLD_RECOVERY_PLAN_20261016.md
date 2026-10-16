# P0 Historical As-of: fold-level admission plan (16 Oct 2026)

## Authority and initial state
Base main: `15b07067d4d069469c686ac79f071d4bf7217c12`.
V6 remains factual owner; V12_PLAYER_MINUTES remains numerical owner.
The existing `scripts/v12_gw6_original_archive_asof.py` is the trusted starting verifier, not a substitute for all-fold verification.

## Confirmed evidence
- Original run 35727337207, immutable commit `55763bbe237c9a673e55325f79b6f81d1afc7d27`, source and normalized original Git blob SHA256 readback: PASS.
- Original GW1-GW5 completed inputs: 50 fixtures, 3,191 verified normalized rows, target GW6 input-as-of PASS.
- GW2-GW5 historical original predeadline feature and model-parameter lineage: NOT ESTABLISHED.
- Original predeadline GW6 model prediction: NOT ESTABLISHED.
- GW7 frozen forecast must not be modified.

## Acceptance tasks
1. Enumerate original V6 Git commit IDs from retained original Actions logs and original trees for each target GW2-GW6. Record run, immutable commit, Git timestamp, original source identity, blob SHA256, and exact official deadline. Never use a branch's current pointer as archival proof.
2. For each fold, independently read the original Git blobs and compare complete SHA256 to original catalog. Verify original per-player training rows against the original event_live, finalized prior fixtures, fixture/team identity, original effective/capture timestamps, and source snapshot IDs.
3. Admit only prior-GW training rows finalized and available before that target GW deadline; reject post-match context and any reconstructed historical timestamp. A source snapshot alone does not prove the historical model/version or prediction was frozen.
4. Write a fold-level fail-closed ledger with separate `source_integrity`, `prior_training_rows_asof`, `model_parameters_asof`, `prediction_frozen_asof`, `leakage`, `admission` and rejection reason. A missing witness must produce NOT_ESTABLISHED, not PASS.
5. Extend existing historical validator and tests, including corrupted Git blob, mismatched digest, timestamp after deadline, unfinalized GW, fixture mismatch, duplicate player-fixture, fabricated source witness, and missing model version.
6. Execute mandatory tests and governance CI, merge only after PASS, verify postmerge controlled V6 readback, and separately verify genuine natural occurrence. Do not equate READY_FULL with historical-as-of admission.

## Exit contract
- `GW6_TRAINING_INPUT_ASOF=PASS` may remain as already evidenced.
- `HISTORICAL_GW1_GW6_ASOF=PASS` only if every required fold has independent source, row, parameter and cutoff witnesses. Otherwise PARTIAL/NOT_ESTABLISHED with exact missing folds.
- No changes to immutable GW7, PR #809, scheduler, P1.7, Stage3, MC500K, or existing owner mathematics.

This checkpoint documents an evidence-backed work item, **not** an assertion that the missing folds have passed.
