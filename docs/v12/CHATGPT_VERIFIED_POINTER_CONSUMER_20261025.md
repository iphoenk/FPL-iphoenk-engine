# ChatGPT read-only consumption of `latest/verified.json`

Status: proposal for the task owner. Nothing here edits the ChatGPT task; the task ID
(`6ad360c909008191ae4368b3da743676`), its HH:30 Asia/Jakarta schedule and issue #431 are untouched.

## 1. Retrieval capability: UNVERIFIED (not BLOCKED, not SUPPORTED)

Evidence available from GitHub only:

- No `latest/verified.json` exists yet (HTTP 404 on 2026-10-25); it is created by the first orchestrator run after PR #1179.
- Issue #431 shows no ChatGPT-authored comment since 2026-10-17 (every comment from 2026-10-22 onward is `github-actions[bot]`), so GitHub carries no evidence that the task executed or read the private repository after that date.
- `native_content.manifest.json` still records `native_ui_acceptance: UNVERIFIED`.
- Whether the task's connector can read `iphoenk/fpl-reports-private` (and files up to ~170 KB for `latest/report.md`; `native_content.json` is ~25 MB) is only observable inside ChatGPT.

Owner check (one minute, read-only): run the task once manually in the existing conversation with a prompt that only reads `latest/verified.json` and `latest/report.md` and reports their SHA-256. A hash equal to `modes.DEEP.canonical_body_sha256` proves retrieval; an access error is the exact BLOCKED finding and the smallest supported alternative then is a connector/app grant for that single private repository (read-only), not a public mirror.

## 2. Minimal prompt change (additive; keep everything else, including the five-section layout)

Add to the task prompt, ahead of report rendering:

```
SOURCE (READ-ONLY). Do not write to GitHub: no issue edit, no comment, no workflow dispatch.
1. Read latest/verified.json from iphoenk/fpl-reports-private (main).
2. Require schema == "FPL_VERIFIED_POINTER_V1". Use modes.DEEP (use modes.PRICE only for the 05:30 WIB price slot).
3. Require entry.remote_readback == "PASS" and entry.receipt_verified == true.
4. For DEEP read latest/report.md; for PRICE read <entry.history_path>/report_body.md.
   Compute SHA-256 of the exact bytes; it MUST equal entry.canonical_body_sha256.
5. If any step fails, or the file is absent: print "READ-ONLY DEGRADED: no verified report available (<reason>)".
   Never fall back to unverified latest/* files and never invent values.
6. Always print: source occurrence_id, report_slot, verified_at_utc, age (now - verified_at_utc),
   terminality (READY_DEGRADED must be shown as DEGRADED) and entry.sequence.
7. If occurrence_id and sequence equal the last ones you presented in this conversation, say
   "No new verified report since <occurrence_id>" instead of repeating the report.
Then render the verified canonical body in the existing five-section format.
```

Why this is sufficient: `latest/*` can describe an occurrence whose verification failed (DEEP 2026-10-23T21:30,
Stage3 INTEGRITY_FAIL); `verified.json` is written only after terminality, bindings, hashes, manifest readback and the
#431 receipt pass. `sequence` makes "new vs already presented" decidable without a ChatGPT-side write.

Owner decision needed: README still describes the task as updating the #431 title and posting `/fpl-master-tick`. The
V12-R architecture requires a read-only consumer. If the live prompt still does that, those steps must be removed by the
owner; this proposal deliberately does not guess the prompt's current text.

## 3. Cross-CPU proof revalidation before 2026-11-08

The frozen proof (`config/performance/v12_runtime_cross_cpu_proof.json`) points to run 40148055764; its artifact expires
2026-11-08. Without weakening any gate:

1. On or before 2026-11-03, list recent successful `pull_request` runs of `Repository governance` and their
   `v12-runtime-cross-cpu-acceptance-<run>` artifacts that are not expired.
2. Accept a candidate only if its JSON has `status` PASS, `proof_mode` DIRECT_CURRENT_HEAD_MULTI_CPU, at least 2
   physical CPU models, `output_sha256` equal to the registry value, a head that is an ancestor of `main`, and the run is
   `pull_request` + success. (A run that only proved VERIFIED_TRANSITIVE is not acceptable.)
3. Re-register through a focused PR changing only the registry JSON, README sync and PR metadata; the gate script is not touched.
4. Durable option (needs approval): raise `retention-days` of the acceptance upload from 14 to 90. It does not change any check;
   it only lengthens the evidence lifetime.
