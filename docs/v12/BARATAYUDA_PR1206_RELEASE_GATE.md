# BARATAYUDA release gate for PR #1206

Status: BLOCKED. This is a work contract, NOT an independent QA sign-off.

## Semar acceptance
- No automatic exact-slot retry after any prior attempt, including failure/cancel/timeout.
- V6 dispatch/terminal failure does not suppress due V12 attempt, while V6 failure remains visible.
- Unknown run state or malformed GitHub response fails closed.
- READY_FULL and natural delivery require independent evidence.

## Bima implementation
- Draft PR #1206 contains fallback guard and V6 failure continuity.
- OPEN: V6 terminal watch still precedes V12 dispatch and can consume 30-minute job timeout.
- OPEN: gh run list --limit 100 is not an exhaustive historical idempotency check.

## Nakula configuration
- Preserve existing ChatGPT task ID, GitHub cron, recovery flags, external-clock activation.
- Verify continue-on-error step outcomes, audit always() behavior, timeouts.

## Sadewa data
- Investigate SOURCE_EVIDENCE_INCOMPLETE against actual private receipts.
- Distinguish 20-club coverage, 7 categories and 5 counterpart domains.
- Never fabricate PASS when providers are unavailable.

## Hanoman security
- Review GH_TOKEN permissions, private repository access, issue-comment disclosures.
- Do not add secrets or disclose tokens.

## Antasena negative tests
- V6 dispatch fails before run ID; terminal failure; empty run ID.
- Run-list permission failure, malformed JSON, failed/cancelled prior attempt.
- Concurrent triggers, stale run beyond list limit, timeout.
- No false success when report dispatch fails.

## Arjuna presentation
- Preserve truthful READY_DEGRADED, all report sections, squad and provenance.

## Gatotkaca CI
- Run pytest tests/test_external_clock_gate.py tests/test_p0b_missed_slot_reconciliation.py.
- Validate YAML and GitHub Actions checks. No production deployment.

## Yudistira independent QA: PENDING
- Require independent reviewer, test logs, private readback receipt, digest and Stage3.
- Require 3 genuine natural ChatGPT deliveries; manual dispatch is not proof.
- This document and its author are NOT QA approval.

## Kresna final approval: PENDING
- Owner approval only after Yudistira PASS. Keep PR draft.

Known blockers: source evidence incomplete (16 latest observed failures), natural delivery 0/3, missed GitHub ticks, inactive independent clock, V6 wait ordering, non-exhaustive run-list guard.
