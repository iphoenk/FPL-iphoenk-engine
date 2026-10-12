# FPL V12 Native Content Manifest/Chunks Design

## Goal

Make DEEP native content lossless and connector-readable while keeping the legacy `native_content.json` for compatibility. A report may claim `VERIFIED` only when producer transport, remote readback, and native UI acceptance all pass for the same occurrence.

## Design

`serving_report.md` remains the canonical byte source. The publisher derives an occurrence-bound `native_content.manifest.json` and line-bound JSON chunks under `native_content/`. Chunk payloads carry their section and part identity, byte length, source hash, and exact content. No Markdown row, profile, evidence block, or typed block may be split or omitted. The legacy full JSON artifact is retained until the new format is published and verified.

The validator has one fail-closed path for producer and remote data. It validates the legal 22-section or 23-section catalog, uniqueness and order, chunk metadata, per-file hashes, section reconstruction, canonical byte length, and canonical SHA256. Remote readback uses the same validator against files fetched from the private repository and records the remote commit and exact native fields in `delivery_receipt.json`.

The native consumer is represented by a strict acceptance contract. It consumes the manifest and every chunk, renders ordered section components including the S06 pitch, all table rows, all S16 profiles, typed decision/evidence panels, and verification indicators, and emits an acceptance receipt. Transport or Markdown/HTML rendering alone cannot elevate the status beyond `UNVERIFIED`.

## Mode-specific remote readback (13 Oct 2026)

The native manifest/chunk requirement applies only to `DEEP` with `delivery_status=READY_FULL`. Public-first `MATCH`, `PRICE`, and evidence-based `DEEP READY_DEGRADED` do not generate native manifests; their receipts retain `native_content_format=NOT_APPLICABLE` and native/UI acceptance `UNVERIFIED`. The remote validator still fail-closes on wrong occurrence identity, report mode, missing or altered canonical bundle/body/digest/execution-proof bytes, or the mode-specific latest digest mismatch. For DEEP READY_FULL, the strict complete native manifest, chunk and latest parity contract remains mandatory. Successful mode-specific readback sets `private_remote_readback=PASS` on the receipt, not native UI VERIFIED.

## Failure handling

Missing, empty, oversized, corrupted, duplicated, reordered, or incomplete chunks fail closed. A section catalog mismatch fails closed. A remote commit mismatch or latest pointer mismatch fails closed. UI acceptance is `UNVERIFIED` unless every expected section and chunk was consumed and the rendered canonical hash matches the manifest.

## Scope

Changes are limited to the native-content parity module, private publisher/receipt, integrated runner remote readback, native consumer acceptance contract, and regression tests. No scheduler, trigger, Monte Carlo contract, P1.7, or PR #809 changes are allowed.
