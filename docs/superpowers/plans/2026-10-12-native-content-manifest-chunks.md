# Native Content Manifest Chunks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver lossless DEEP manifest/chunk transport and a fail-closed native UI verification gate.

**Architecture:** Keep `serving_report.md` as the canonical byte source. Extend the existing parity module with strict producer, remote, and UI contracts; have the private publisher write occurrence and latest artifacts atomically; have the integrated runner validate remote files and update the receipt only after the remote commit is confirmed.

**Tech Stack:** Python 3.12, pytest, GitHub Actions, private Git repository publication.

**Spec:** `docs/superpowers/specs/2026-10-12-native-content-manifest-chunks-design.md`

## Global Constraints

- Preserve canonical content byte-for-byte.
- Support exactly the legal 22-section DEEP catalog or the legal 23-section catalog with S16B.
- Keep legacy `native_content.json` until manifest/chunks pass.
- Never claim `VERIFIED` from READY_FULL, Markdown, HTML/CSS, or transport alone.
- Do not change scheduler authority, create a second trigger, alter MC500K/P1.7, or touch PR #809.

## Review Focus

- UTF-8 byte boundaries and a single oversized Markdown line: test producer rejection without truncation.
- Duplicate or reordered part metadata: test fail-closed reconstruction.
- 58 mini-league rows and 15 S16 profiles: test full content survives chunking.
- Remote commit/readback mismatch: test receipt remains unverified.
- Native UI partial consumption: test no VERIFIED until every section and chunk is consumed.

### Task 1: Harden parity and native acceptance contracts

**Files:**
- Modify: `src/engines/v12_native_content_parity.py`
- Test: `tests/test_native_content_parity.py`

**Interfaces:**
- `build_manifest_chunks(artifact, max_chunk_bytes=...) -> (manifest, files)`
- `validate_manifest_chunks(manifest, files, canonical_body=...) -> None`
- `build_native_ui_acceptance(manifest, rendered_section_ids, rendered_content, user_visible_acceptance) -> dict`

- [ ] Add failing tests for 22 and 23 sections, byte length, duplicate/missing/reordered/truncated chunks, per-chunk hash, 58 rows, 15 profiles, and UI acceptance requiring all gates.
- [ ] Implement strict manifest schema fields, actual chunk count, per-file byte lengths, canonical byte length, section uniqueness/order, and safe line-bound chunking.
- [ ] Implement native acceptance fields including `native_ui_matches_manifest`, `native_ui_all_chunks_consumed`, and `verification_status`.
- [ ] Run `pytest tests/test_native_content_parity.py -q`.
- [ ] Commit `feat: harden lossless native content parity contracts`.

### Task 2: Bind publisher output and receipt fields

**Files:**
- Modify: `src/engines/v12_private_publisher.py`
- Test: `tests/test_private_publisher.py`

**Interfaces:**
- `publish_private_output(...) -> dict` writes the occurrence manifest/chunks, legacy artifact, and receipt.

- [ ] Add failing tests for occurrence and latest chunk parity, required receipt fields, and no VERIFIED from transport-only state.
- [ ] Publish manifest/chunks atomically alongside the legacy artifact and preserve occurrence binding.
- [ ] Populate the requested `MANIFEST_CHUNKS_V1` receipt fields with actual count, hashes, round-trip, truncation, and UI status.
- [ ] Run publisher regression tests.
- [ ] Commit `feat: bind native manifest chunks to private receipt`.

### Task 3: Make remote readback a complete gate

**Files:**
- Modify: `.github/workflows/v12-integrated-report-runner.yml`
- Test: `tests/test_native_content_remote_readback.py`

**Interfaces:**
- Workflow readback validates remote manifest/chunks against remote `serving_report.md` and records the same remote commit in the receipt.

- [ ] Add tests for remote reconstruction, commit binding, latest/occurrence equality, and failed readback.
- [ ] Fetch manifest and every chunk from the remote commit, validate all hashes and canonical bytes, then update receipt only on success.
- [ ] Keep remote readback status separate from native UI acceptance.
- [ ] Run workflow contract tests and YAML/static checks.
- [ ] Commit `feat: fail closed on native remote readback mismatch`.

### Task 4: Verify end-to-end and release

**Files:**
- Modify: relevant documentation and regression tests only if verification exposes a contract gap.

- [ ] Run the focused native suite and the current-main CI-equivalent suite, recording the two pre-existing visible-rendered failures separately.
- [ ] Create a PR from the feature branch without touching PR #809.
- [ ] Wait for required checks, merge, deploy, and verify production SHA equals the merge commit.
- [ ] Run exactly one controlled DEEP via issue #431 with a fresh valid slot.
- [ ] Verify producer transport, private delivery, remote readback, canonical round-trip, latest binding, native UI acceptance, and visible 22/22 or 23/23 sections for the same occurrence.
- [ ] Report only `TRANSPORT_PASS`, `REMOTE_READBACK_PASS`, `NATIVE_UI_PASS`, or `VERIFIED` according to the gates.
