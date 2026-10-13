# FPL PRICE Public-First and Private Publish Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the canonical PRICE occurrence executable from public Official FPL facts without private authentication, while preserving a separately verified FULL path and fail-closed private publication.

**Architecture:** Introduce explicit source-domain availability in the prefetch manifest, then let PRICE resolve public facts and personal identity independently. Authenticated finance is an optional private enrichment for PRICE; when absent, the runner emits all 12 sections with unavailable finance fields and no executable transfer economics. Publisher and occurrence verification bind the report class, exact slot, hashes, and immutable receipt without promoting degraded output to full.

**Tech Stack:** Python 3.12, pytest, GitHub Actions YAML, Git-backed private publication, SHA256 manifests.

**Spec:** User request `FPL MASTER V12 — P0 PRICE PUBLIC-FIRST & PRIVATE PUBLISH RECOVERY` dated 2026-10-14.

## Global Constraints

- Preserve one ChatGPT scheduler authority and do not create cron, duplicate workflow, trigger, or alternate authority.
- Do not change PR #809, P1.7, Stage3 temporal integrity, canonical MC500K, S16B lifecycle, or the security boundary.
- Do not use saved personal snapshots as current authenticated team or current financial authority.
- FULL requires public facts, authenticated personal facts, analytics QA, private readback, and matching hashes.
- PUBLIC_FIRST_DEGRADED may publish only with public facts and explicit unavailable personal finance; it cannot become READY_FULL.
- Natural scheduler acceptance must remain separate from controlled verification and must not be fabricated.

## Review Focus

- PRICE with `personal=False` must still produce a public-first report: test `test_price_prefetch_declares_public_domains_without_personal_request`.
- Authenticated current-team evidence must be the only finance authority: test `test_stale_or_missing_auth_cannot_authorize_finance`.
- Public-first degraded output must preserve all 12 sections and hide executable transfer economics: test `test_price_public_first_degraded_is_complete_but_non_executable`.
- Publisher must reject fake FULL and accept only explicit degraded classification: test `test_private_publisher_rejects_unclassified_degraded_price`.
- Exact-slot and immutable receipt binding must survive a moving branch head: test `test_wave3_proof_binds_exact_run_artifact_not_branch_head`.

---

### Task 1: Establish failing contract tests

**Files:**
- Test: `tests/test_price_public_first_contract.py`
- Test: `tests/test_private_publish_price_contract.py`
- Test: `tests/test_wave3_immutable_proof_contract.py`

- [ ] Write tests for explicit `PUBLIC_OFFICIAL`, `PUBLIC_LEAGUE`, and `PRIVATE_PERSONAL` availability, authenticated versus stale identity, 12 PRICE sections, unavailable finance, no executable routes, publisher classification, and exact immutable proof binding.
- [ ] Run the focused tests and confirm they fail for the missing contract behavior.

### Task 2: Repair prefetch source-domain contract

**Files:**
- Modify: `src/runtime_v6/domains/report_plane/prefetch_contract.py`
- Modify: `src/runtime_v6/domains/report_plane/report_prefetch.py`
- Test: `tests/test_price_public_first_contract.py`

- [ ] Emit source-domain availability and explicit personal state for PRICE without converting `NOT_REQUESTED` to auth availability.
- [ ] Keep public Official and public league facts usable when private auth is unavailable; preserve timestamps, provenance, and degradation reason.
- [ ] Add the minimum regression coverage for public unavailable versus personal available and the reverse.

### Task 3: Repair PRICE runner modes

**Files:**
- Modify: `src/engines/v12_price_delivery.py`
- Modify: `src/engines/v12_integrated_report_runner.py` only at PRICE routing boundaries.
- Test: `tests/test_price_public_first_contract.py`

- [ ] Resolve public facts and personal evidence independently.
- [ ] Emit `FULL` only with current authenticated finance evidence; otherwise emit `PUBLIC_FIRST_DEGRADED` with all 12 sections, source timestamps, logical slot, provenance, and no executable transfer economics.
- [ ] Do not run MC or invent financial values when the required private input is absent.

### Task 4: Repair private publisher and terminality classification

**Files:**
- Modify: `src/engines/v12_private_publisher.py`
- Modify: `src/engines/v12_occurrence_terminality.py`
- Modify: relevant private-publish workflow boundary in `.github/workflows/v6-natural-data-ingestion.yml`.
- Test: `tests/test_private_publish_price_contract.py`

- [ ] Accept `READY_FULL` and explicit `READY_DEGRADED_PUBLIC_FIRST` only when their QA contracts pass.
- [ ] Bind destination, manifest, SHA256, receipt, exact slot, idempotency, and remote readback; never overwrite FULL with degraded or advance latest prematurely.
- [ ] Remove current-personal fallback semantics from the PRICE execution path while retaining historical reference metadata with timestamp.

### Task 5: Repair immutable natural-proof verification

**Files:**
- Modify: `.github/workflows/v6-wave3-proof.yml`
- Modify: verifier module identified by the existing Wave-3 workflow audit.
- Test: `tests/test_wave3_immutable_proof_contract.py`

- [ ] Bind proof to exact run ID, immutable artifact digest, source commit, logical slot, and publication receipt.
- [ ] Distinguish legitimate branch movement from missing or inconsistent evidence without weakening integrity gates.

### Task 6: Verify, integrate, and deploy

- [ ] Run focused, full unit, integration, contract, security, and regression suites.
- [ ] Run CI, create/review PR, merge only with required checks, and verify current-main deployment.
- [ ] Run one controlled PRICE through the existing official path and collect prefetch, runner, QA, private receipt, manifest/hash, and remote-readback evidence.
- [ ] Wait for the next natural PRICE occurrence and report natural acceptance independently from controlled and native user-visible acceptance.

