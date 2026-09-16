# R1 — Baseline & Root-Cause Proof

Status: **RED by design**

R1 is evidence-only. It does not change production behavior.

## Baseline

- Repository: `iphoenk/FPL-iphoenk-engine`
- Base branch: `main`
- Exact base commit: `1d3df97adb085ac9e84ead0ab2cf26a0f6b0958c`
- Incident timestamp: `2026-09-16T17:29:51+07:00`
- Golden fixture: `tests/fixtures/report_false_pass_2026-09-16T172951+0700.json`
- RED regression test: `tests/test_report_hardening_r1_false_pass.py`

The exact rendered player body from the incident is not available in the retained archive. The fixture therefore preserves the observed status contradiction and the structural RISE20/FALL20 failure shape, while using explicitly anonymized test-only player identities and prices. It must not be treated as a historical player-data snapshot.

## Observed contradiction locked by the fixture

The retained incident evidence says all of these were true at the same time:

- `DATA_PUBLICATION_FRESH=TRUE`
- `VISIBLE_EMITTED=TRUE`
- `REPORT_CONTRACT_PASS=FALSE`
- `REPORT_CONTRACT_STATUS=FAIL`
- `REPORT_INCOMPLETE_SECTIONS=RISE20,FALL20`
- final surfaced run status was `PASS`

That is the false-PASS condition R1 protects against.

## Reproduction boundary

R1 intentionally uses only one row-level requirement for the RED proof: `eta` must exist on each RISE20/FALL20 row. The complete canonical row schema is deferred to R2, so R1 does not prematurely hardcode the final contract.

The fixture contains exactly 20 RISE rows and exactly 20 FALL rows, each with unique identity, but no `eta`.

## Root-cause proof

### 1. `validate_rank20()` is count/identity-only

Current production validation accepts a RISE20/FALL20 set when:

1. row count is exactly 20;
2. every row has a player identity;
3. identities are unique.

It does not validate ETA or any other required row-level report field.

### 2. `build_report_compute_contract()` trusts that weak result

`build_report_compute_contract()` calls `validate_rank20()` for both RISE20 and FALL20. If those validators return PASS, the rank sections contribute no compute failure.

Therefore 20 structurally incomplete rows can make the report compute contract PASS.

### 3. Existing positive regression coverage encodes the same weak assumption

The existing `tests/test_data_platform_report_compute_contract.py` helper `_rank20()` creates rows containing only `element_id`. The existing valid-compute test expects both RISE20 and FALL20 to PASS.

This is not only a missing test. The current test baseline actively defines count-plus-identity as sufficient.

### 4. Render QA is also count-oriented for RISE/FALL

The current report QA handoff validates expected totals for RISE20/FALL20, while post-render checks compare rendered counts. The row schema itself is not part of the handoff contract.

This explains how a visibly incomplete 20-row section can satisfy numerical completeness checks.

## Golden RED expectation

Run:

```bash
pytest -q tests/test_report_hardening_r1_false_pass.py
```

Expected R1 state before any production fix:

- fixture-fidelity test: **PASS**;
- production regression test: **FAIL**;
- failure message must show that production returned compute `PASS` for 20 RISE/FALL rows that have no ETA.

A GREEN result for the second test before an intentional production change would invalidate this R1 baseline and must be investigated.

## R1 exit criteria

R1 is complete only when:

- the incident contradiction is frozen in a fixture;
- the test executes the real production compute contract;
- the test is RED for the expected semantic reason;
- no production implementation file is changed;
- no R2+ contract/schema fix is smuggled into this wave.

Do not merge this RED branch as a production fix. R2/R3 should make the golden test GREEN by changing the contract and deterministic engine deliberately.
