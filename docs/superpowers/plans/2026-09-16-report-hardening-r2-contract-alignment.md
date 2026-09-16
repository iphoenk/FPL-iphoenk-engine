# Report Hardening R2 Contract Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RISE20/FALL20 executable completeness mean exact-20 plus the canonical schema-complete row contract across repo, Runtime Contract, Spec V11, and FPL Master Monitor.

**Architecture:** Keep V6 factual-only. Strengthen the report-plane validator and semantic fingerprint without implementing R3 ranking/generation logic or R6 visible-body parsing. Synchronize Library and automation authority only after the repository contract is verified.

**Tech Stack:** Python 3.12, pytest, GitHub Actions, ChatGPT Library authority files, Automations.

**Spec:** `docs/superpowers/specs/2026-09-16-report-hardening-r2-contract-alignment-design.md`

## Global Constraints
- Never use or restore V3/V4/V5 production authority.
- No hard-coded player names.
- R2 must not implement R3 selection/ranking/ETA-generation behavior.
- R2 must not claim R6 post-render visible-field validation is solved.
- Count-only 20/20 must never be sufficient for RISE20/FALL20 PASS.
- R1 golden fixture is retained and must become GREEN for the intended reason.

---

### Task 1: Lock the executable R2 contract with RED tests

**Files:**
- Create: `tests/test_report_hardening_r2_contract_alignment.py`
- Modify: `tests/test_data_platform_report_compute_contract.py`
- Reuse: `tests/test_report_hardening_r1_false_pass.py`

**Interfaces:**
- Consumes: `build_report_compute_contract(...)` and `validate_rank20(rows, label=...)`.
- Produces: failing tests for missing row schema, wrong direction/rank, and fingerprint insensitivity.

- [ ] Add a reusable full-schema rank-row fixture using synthetic IDs only.
- [ ] Add tests proving identity-only 20 rows fail.
- [ ] Add tests proving missing ETA/provenance/ownership-tag fields fail with row evidence.
- [ ] Add tests proving direction and rank integrity fail closed.
- [ ] Add a valid exact-20 full-schema PASS test.
- [ ] Add a fingerprint test where the same IDs but changed ETA/projection/urgency/provenance produce a different fingerprint.
- [ ] Run CI and verify the new tests are RED because current production validator is count/identity-only.

### Task 2: Implement the minimal report-plane row contract

**Files:**
- Modify: `src/runtime_v6/domains/report_plane/delivery_integrity.py`
- Modify: `src/runtime_v6/domains/report_plane/report_compute.py`

**Interfaces:**
- Produces: `RANK20_REQUIRED_FIELDS`, schema-aware `validate_rank20()`, and semantic rank-row fingerprinting.

- [ ] Define one canonical required-field registry and no duplicate schema list elsewhere in production code.
- [ ] Validate exact count, identity, rank, direction, mandatory keys, non-empty mandatory labels, ownership tag, and SHA-256 provenance hash.
- [ ] Return deterministic row-specific failure strings.
- [ ] Fingerprint canonical RISE/FALL row contents rather than IDs only.
- [ ] Re-run focused R1/R2/report-compute tests and then full regression.

### Task 3: Align repository documentation without extending scope

**Files:**
- Create: `docs/report-hardening/R2_AUTHORITY_CONTRACT_ALIGNMENT.md`

**Interfaces:**
- Documents exact canonical schema, R1-to-R2 transition, known R3/R6 remaining work, and verification evidence.

- [ ] Record exact branch/base/head.
- [ ] Record canonical field semantics and nullability rules.
- [ ] Explicitly state R3 generation and R6 actual-render parsing are not solved in R2.
- [ ] Record test/workflow evidence.

### Task 4: Synchronize active Library authorities

**Files:**
- Update Library: `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt`
- Update Library: `/FPL/FPL_MASTER_SPEC_V11.txt`

**Interfaces:**
- Runtime Contract owns hard fail-closed operational gate.
- Spec V11 owns report field/schema semantics.

- [ ] Materialize/read the latest exact Library versions.
- [ ] Runtime: upgrade Full/Deep, 05:30, and Final QA from count-only to count + current Spec row schema.
- [ ] Runtime: add 16 Sep 2026 17:29 false-PASS as a named blocked regression.
- [ ] Spec: define canonical row schema and ETA/provenance/ownership semantics once, then reference it from report modes.
- [ ] Upload as new Library versions without modifying the legacy archive.
- [ ] Re-read both files and verify the inserted text exists in the current versions.

### Task 5: Align the FPL Master Monitor safety kernel

**External state:**
- Update existing automation `FPL Master Monitor` only.

- [ ] Preserve the existing schedule, authority bootstrap, and single-automation invariant.
- [ ] Replace count-only safety-kernel wording with: exact20 + conformity to current Spec V11 row schema; count-only is never PASS.
- [ ] Keep detailed schema out of the automation prompt to preserve anti-drift ownership in Library.
- [ ] Read back automation state and verify enabled/schedule unchanged.

### Task 6: Final verification and R2 pull request

- [ ] Verify focused R1/R2 tests on exact head.
- [ ] Verify relevant full CI/governance on exact head.
- [ ] Compare R2 branch against R1 head and confirm no R3/R6 scope leakage.
- [ ] Open a draft stacked R2 PR based on `report-hardening-r1-baseline` so R2 diff is isolated.
- [ ] Keep it unmerged until the user advances the wave sequence or explicitly requests integration.
