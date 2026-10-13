# FPL V12 Native Content Manifest/Chunks Design

## Goal

Make DEEP native content lossless and connector-readable while keeping the legacy `native_content.json` for compatibility. A report may claim `VERIFIED` only when producer transport, remote readback, and native UI acceptance all pass for the same occurrence.

## Design

`serving_report.md` remains the canonical byte source. The publisher derives an occurrence-bound `native_content.manifest.json` and line-bound JSON chunks under `native_content/`. Chunk payloads carry their section and part identity, byte length, source hash, and exact content. No Markdown row, profile, evidence block, or typed block may be split or omitted. The legacy full JSON artifact is retained until the new format is published and verified.

The validator has one fail-closed path for producer and remote data. It validates the legal 22-section or 23-section catalog, uniqueness and order, chunk metadata, per-file hashes, section reconstruction, canonical byte length, and canonical SHA256. Remote readback uses the same validator against files fetched from the private repository and records the remote commit and exact native fields in `delivery_receipt.json`.

The native consumer is represented by a strict acceptance contract. It consumes the manifest and every chunk, renders ordered section components including the S06 pitch, all table rows, all S16 profiles, typed decision/evidence panels, and verification indicators, and emits an acceptance receipt. Transport or Markdown/HTML rendering alone cannot elevate the status beyond `UNVERIFIED`.

## Mode-specific remote readback (13 Oct 2026)

The native manifest/chunk requirement applies only to `DEEP` with `delivery_status=READY_FULL`. Public-first `MATCH`, `PRICE`, and evidence-based `DEEP READY_DEGRADED` do not generate native manifests; their receipts retain `native_content_format=NOT_APPLICABLE` and native/UI acceptance `UNVERIFIED`. The remote validator still fail-closes on wrong occurrence identity, report mode, missing or altered canonical bundle/body/digest/execution-proof bytes, or the mode-specific latest digest mismatch. For DEEP READY_FULL, the strict complete native manifest, chunk and latest parity contract remains mandatory. Successful mode-specific readback sets `private_remote_readback=PASS` on the receipt, not native UI VERIFIED.

## Final remote receipt and latest parity (13 Oct 2026)

The terminal public proof must reference SHA256 of the **final second-commit remote receipt bytes**, not the local publisher receipt created before native remote readback. After the initial immutable remote readback and validation, the governed publisher persists the readback manifest to the occurrence and latest manifest paths and the final receipt to the occurrence. It confirms the final pushed commit, independently rereads the receipt from that immutable commit, byte-compares the occurrence/ latest manifests, and verifies the manifest SHA256 against the final receipt before permitting public proof. An intermediate receipt hash cannot be called the terminal receipt hash. This workflow makes no user-visible ChatGPT UI acceptance claim.

## Failure handling

Missing, empty, oversized, corrupted, duplicated, reordered, or incomplete chunks fail closed. A section catalog mismatch fails closed. A remote commit mismatch or latest pointer mismatch fails closed. UI acceptance is `UNVERIFIED` unless every expected section and chunk was consumed and the rendered canonical hash matches the manifest.

## Scope

Changes are limited to the native-content parity module, private publisher/receipt, integrated runner remote readback, native consumer acceptance contract, and regression tests. No scheduler, trigger, Monte Carlo contract, P1.7, or PR #809 changes are allowed.


## ChatGPT native host acceptance boundary (13 Oct 2026)

The Python `v12_native_consumer` now emits host-ready native block descriptors
(heading, paragraph, table, list item) and an S06 XI/bench pitch model extracted
from canonical **text fields**, never by claiming that source HTML/CSS rendered
natively. It also reports the exact consumed chunk-path ledger. The lossless
source and canonical hashes remain unchanged.

**No self-certification:** a Python unit test passing
`user_visible_acceptance=True`, a rendered-section list, or a 26/26 transport
readback is insufficient for `VERIFIED`. The acceptance function requires an
actual host-observed receipt for the *same* report slot and occurrence path,
with all 22 native section components, the exact 26 chunk paths in order,
canonical SHA256 and an actual visible render event identifier. The trusted host
must HMAC-sign the receipt using a dedicated verification key not available to
the producer or the model. Missing key, missing signature, invalid signature,
mismatched occurrence, or omitted/reordered chunks fail closed.

The HMAC key is a **host integration boundary**, not a GitHub secret that this
repository provisions or a fabricated fixture to insert in a report. The
synthetic unit-test key proves only validator behavior and is never operational
acceptance. No existing `delivery_receipt.json` should be rewritten on the
strength of a test fixture. Until a trusted ChatGPT host integration observes the
actual rendered content, the terminal status remains
`REMOTE_READBACK_PASS / native_ui_acceptance=UNVERIFIED`; it must not be
promoted by CI, markdown summaries, or manual receipt edits.

**Acceptance evidence for future host integration:**
- exact immutable occurrence path and private remote commit;
- 22 native sections in canonical order, with S06 native pitch and full tables;
- all 26 chunk paths consumed, in the manifest order;
- content identity and canonical hash matches, including all S16 parts;
- host-observed visible render event and signed acknowledgement;
- a governed, separate receipt write with readback (not a replacement for
  the already-final remote delivery receipt or the canonical latest pointer).
