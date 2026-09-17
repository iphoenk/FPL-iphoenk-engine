# R6 Actual Visible Body QA

## Purpose

R6 prevents a report from passing post-render QA when renderer metadata claims success but the text actually shown to the user is missing, incomplete, placeholder-only, truncated, or structurally inconsistent with the approved pre-render handoff.

R6 is downstream of R4 structural section validation and R5 provenance/anti-fabrication. It does not acquire V6 data, replace R4/R5, perform delivery retries, or introduce legacy V3/V4/V5 fallback.

## Authority

- `src/runtime_v6/domains/report_plane/visible_body_contract.py` is the single parser/validator authority for actual visible-body content.
- `src/runtime_v6/domains/report_plane/report_qa.py` owns pre-render and post-render orchestration.
- Renderer-supplied metadata remains a secondary consistency check only. It cannot override failures found in the visible body.
- Canonical visible presentation comes from the active FPL Master Runtime Contract and Spec V11 catalog; R6 accepts canonical numbered headings such as `1. ...`, `14B. ...`, `18. ...` and the explicit legacy `SECTION nn` form for compatibility.
- RISE20/FALL20 semantic validation delegates to the existing R2/J1 `validate_rank20()` authority after visible split tables are reconstructed. R6 does not maintain a second ownership/identity/timestamp/hash rule set.

## Fail-closed visible checks

The visible body must prove:

- exact mandatory section presence, uniqueness, and order, including `S14B`;
- non-empty material content for required sections;
- OUR15=15 with visible stable identities;
- XI=11 and BENCH=4 forming the visible OUR15 partition;
- Watchlist20=20 with visible GK5/DEF5/MID5/FWD5 and `NON_OWNED` status;
- RISE20=20 and FALL20=20 using the single `RANK20_REQUIRED_FIELDS` authority from R2/J1; count-only 20/20 cannot pass;
- split mobile RISE/FALL tables may be used, but every rank must reconstruct all 17 canonical J1 fields and then pass the same R2/J1 semantic validator used by compute integrity, including stable identity, rank sequence, ownership tag, direction, provenance hash, and timezone-aware `observed_at`;
- ALL15 tactical visible row count=15 and identity set consistent with visible OUR15;
- visible FACT / MODEL / INFERENCE classification when the corresponding pre-render namespaces are active; exact internal keys remain cryptographically bound in the pre-render token and renderer metadata rather than being forced into user-facing prose;
- explicit complete mini-league manager coverage/denominator evidence;
- the expected canonical weather contract state, including `WEATHER — DIRECT CHATGPT`, `WEATHER SOURCE: DEGRADED`, `WEATHER: NOT IN SCOPE — PRICE-ONLY CHECKPOINT`, or current Match weather state as applicable;
- absence of progress-only placeholders and explicit truncation markers.

The parser also emits a SHA-256 digest of the actual body and parsed visible evidence for QA traceability.

## Render-token hardening

R6 extends the pre-render token to bind `expected_inference_keys` in addition to section manifest, counts, FACT keys, MODEL keys, weather state, mini-league denominator completeness, and compute fingerprint. Tampering with any bound pre-render expectation invalidates the token.

## State progression

A successful post-render QA result still has `delivery_ready=false`. R6 can only advance to `BUILD_DELIVERY_PROOF`; Wave 7 remains responsible for delivery recovery/proof.

## TDD proof

R6 began with golden failing fixtures where all renderer metadata was deliberately correct while the actual body was defective. The baseline failed only because `rendered_body` was not yet accepted by post-render QA, proving the gap before implementation.

A later canonical-authority review added two hardening proofs. First, exact-count RISE20/FALL20 is insufficient when a visible J1 field is omitted. Second, a row with all 17 visible fields is still invalid if R2/J1 semantic rules fail, such as duplicate `element_id`, invalid `ownership_tag`, or malformed `observed_at`. The final R6 suite therefore proves actual-body presence, visible row-schema completeness, and semantic reuse of the single R2/J1 authority before merge.
