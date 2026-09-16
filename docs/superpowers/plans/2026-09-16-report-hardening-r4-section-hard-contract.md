# R4 Section-Level Hard Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make report-compute fail closed when any R4 mandatory report section is structurally incomplete, even when a caller declares that section PASS.

**Architecture:** Add one focused `section_contract.py` module as the single registry and validation authority for R4 section payloads. Reuse existing R2/R3 validators for Watchlist20 and RISE/FALL instead of duplicating them. Wire the aggregate section contract into `report_compute` so compute readiness depends on content-valid mandatory section payloads, while leaving R5 provenance/anti-fabrication and R6 rendered-body parsing out of scope.

**Tech Stack:** Python 3.12, pytest, existing runtime_v6 report-plane modules.

**Spec:** `/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt`, `/FPL/FPL_MASTER_SPEC_V11.txt`, and `docs/report-hardening/R4_SECTION_LEVEL_HARD_CONTRACT.md`.

## Global Constraints

- V6 remains factual data-plane only; downstream report analytics/validation live in ChatGPT/report plane.
- Never use V3/V4/V5 as fallback.
- Reuse `validate_watchlist20()` and `validate_rank20()` as canonical count/schema validators.
- R4 validates section payload completeness before rendering. It does not implement R5 source-proof/anti-fabrication or R6 actual rendered-body parsing.
- No hardcoded player names.
- Missing is not zero; unavailable is not false.
- `PARTIAL` is allowed only where the section-specific contract explicitly permits truthful degradation; it must never masquerade as `PASS`.

---

### Task 1: Lock R4 behavior with failing tests

**Files:**
- Create: `tests/test_report_hardening_r4_section_contract.py`

**Interfaces:**
- Consumes: existing `validate_watchlist20`, `validate_rank20`.
- Produces expected API: `validate_report_sections(payload: Mapping[str, Any]) -> dict[str, Any]` and named validators exposed from `section_contract.py`.

- [ ] Write tests proving a syntactically present section cannot PASS when required fields/counts are missing.
- [ ] Cover OUR15 exact 15 + 2/5/5/3 + identity uniqueness; XI exactly 11 legal + bench exactly 4 complement; Watchlist20; RISE20; FALL20.
- [ ] Cover Weather minimum fields and explicit degraded state; ICON+ 14B required analytical fields; ALL15 Tactical exactly 15 owned IDs and every canonical tactical field; Optimizer route schema and legality; Transfer Stage state/route/trigger/reversal requirements; Price Risk owned/candidate coverage and affordability impact fields.
- [ ] Add aggregate test proving one broken section makes the section contract FAIL and compute readiness false.
- [ ] Run focused test and confirm expected RED because `section_contract.py` does not exist.

### Task 2: Implement the single section-contract registry

**Files:**
- Create: `src/runtime_v6/domains/report_plane/section_contract.py`
- Test: `tests/test_report_hardening_r4_section_contract.py`

**Interfaces:**
- Produces `SECTION_CONTRACT_REGISTRY`, named section validators, and `validate_report_sections()`.
- Each validator returns `{status, failures, ...}` with deterministic failure codes.

- [ ] Define one registry for canonical required fields/counts/status enums.
- [ ] Implement shared helpers for identity, required-key, non-empty, exact-count, and enum checks.
- [ ] Implement the eleven requested section validators without player-name hardcodes.
- [ ] Reuse existing Watchlist/Rank20 validators rather than cloning their rules.
- [ ] Implement truthful degraded Weather/ICON+/Optimizer handling without allowing incomplete content to claim PASS.
- [ ] Run focused R4 tests to GREEN.

### Task 3: Make R4 unavoidable in report compute

**Files:**
- Modify: `src/runtime_v6/domains/report_plane/report_compute.py`
- Test: `tests/test_report_hardening_r4_section_contract.py`

**Interfaces:**
- Extend `build_report_compute_contract()` and canonical `build_report_compute_contract_from_universe()` with `section_payloads`.
- Add `SECTION_CONTRACT` to checks/fingerprint and require PASS for `compute_ready=True`.

- [ ] Add a RED integration test showing current report-compute can PASS while Weather/ICON+/ALL15 Tactical/Optimizer/Transfer Stage/Price Risk are structurally broken.
- [ ] Wire `validate_report_sections()` into report compute.
- [ ] Bind section payload semantics into compute fingerprint so material section changes invalidate the fingerprint.
- [ ] Preserve low-level compatibility only where explicitly used by tests, but canonical construction must not bypass R4.
- [ ] Run full unit/regression suite to GREEN.

### Task 4: Document scope and verify architecture

**Files:**
- Create: `docs/report-hardening/R4_SECTION_LEVEL_HARD_CONTRACT.md`

**Interfaces:**
- Documents section contracts, degradation semantics, boundaries, test evidence, and canonical ownership.

- [ ] Record exact section schemas and failure policy.
- [ ] Explicitly state R5/R6 boundaries.
- [ ] Verify no duplicate registries, no player hardcodes, no legacy fallback, and one canonical report-compute integration path.
- [ ] Run exact-head CI, mark PR ready, merge only if all required checks pass.
- [ ] Run post-merge `main` proof and require success before calling R4 DONE.
