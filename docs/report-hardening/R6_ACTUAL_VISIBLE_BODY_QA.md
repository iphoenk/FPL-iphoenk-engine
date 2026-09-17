# R6 Actual Visible Body QA

## Purpose

R6 prevents a report from passing post-render QA when renderer metadata claims success but the text actually shown to the user is missing, incomplete, placeholder-only, truncated, or structurally inconsistent with the approved pre-render handoff.

R6 is downstream of R4 structural section validation and R5 provenance/anti-fabrication. It does not acquire V6 data, replace R4/R5, perform delivery retries, or introduce legacy V3/V4/V5 fallback.

## Authority

- `src/runtime_v6/domains/report_plane/visible_body_contract.py` is the single parser/validator authority for actual visible-body content.
- `src/runtime_v6/domains/report_plane/report_qa.py` owns pre-render and post-render orchestration.
- Renderer-supplied metadata remains a secondary consistency check only. It cannot override failures found in the visible body.

## Fail-closed visible checks

The visible body must prove:

- exact mandatory section presence, uniqueness, and order, including `S14B`;
- non-empty material content for required sections;
- exact visible counts for OUR15=15, XI=11, BENCH=4, WATCHLIST20=20, RISE20=20, FALL20=20;
- ALL15 tactical visible row count=15;
- exact FACT, MODEL, and INFERENCE key visibility from the pre-render handoff;
- complete mini-league denominator marker;
- the expected weather contract state;
- absence of progress-only placeholders and explicit truncation markers.

The parser also emits a SHA-256 digest of the body and parsed visible evidence for QA traceability.

## Render-token hardening

R6 extends the pre-render token to bind `expected_inference_keys` in addition to section manifest, counts, FACT keys, MODEL keys, weather state, mini-league denominator completeness, and compute fingerprint. Tampering with any bound pre-render expectation invalidates the token.

## State progression

A successful post-render QA result still has `delivery_ready=false`. R6 can only advance to `BUILD_DELIVERY_PROOF`; Wave 7 remains responsible for delivery recovery/proof.

## TDD proof

R6 began with golden failing fixtures where all renderer metadata was deliberately correct while the actual body was defective. The baseline failed only because `rendered_body` was not yet accepted by post-render QA, proving the gap before implementation. The final R6 suite must keep those fixtures green and the full repository regression suite green before merge.
