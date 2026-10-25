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
SOURCE (READ-ONLY). Do not write to GitHub: no issue edit, no comment, no workflow dispatch, no rerun.
1. Read latest/verified.json from iphoenk/fpl-reports-private (main).
2. Require schema == "FPL_VERIFIED_POINTER_V1". Use modes.DEEP (use modes.PRICE only for the PRICE slot).
3. Require entry.remote_readback == "PASS" and entry.receipt_verified == true.
4. Read the body at the immutable path entry.body_path (never latest/report.md: it can belong to another occurrence).
   Compute SHA-256 of the exact bytes; it MUST equal entry.canonical_body_sha256.
5. If any step fails, or the file is absent: print "READ-ONLY DEGRADED | NOT CANONICAL V12: no verified report
   available (<reason>)". Never fall back to unverified latest/* files and never invent values.
6. Always print: source occurrence_id, original report_slot (WIB), entry.generated_at, verified_at_utc,
   delivery lateness (verified_at_utc - report_slot), age (now - verified_at_utc), entry.origin
   (RECOVERY must be labelled "RECOVERY delivery"), terminality (READY_DEGRADED shown as DEGRADED), entry.sequence.
   Timing: the ChatGPT task runs at HH:30, the repository clock at HH:35 WIB, so a report published after
   the task's HH:30 run appears at the next hourly run; show original slot and delivery time, never relabel
   an older occurrence as current.
7. If occurrence_id and sequence equal the last ones you presented in this conversation, say
   "No new verified report since <occurrence_id>" instead of repeating the report.
Then render the verified canonical body under EXACTLY five top-level sections, in this order, and no other
top-level heading: 1 OVERVIEW & ACTION, 2 OUR15 & XI, 3 ANALYTICS, 4 MINI-LEAGUE & COMPETITIVE, 5 FINAL DECISION & QA.
Place the canonical sections verbatim (see section 4 mapping); never recompute, reword or invent a value.
Keep the compact mobile-first layout, the green pitch, C/VC labels on the player names and the horizontal four-player
bench (S06 block) whenever the host renders it. In the degraded case still print the five headings, each with
"NOT AVAILABLE", under the line "READ-ONLY DEGRADED | NOT CANONICAL V12".
```

Why this is sufficient: `latest/*` can describe an occurrence whose verification failed (DEEP 2026-10-23T21:30,
Stage3 INTEGRITY_FAIL); `verified.json` is written only after terminality, bindings, hashes, manifest readback and the
#431 receipt pass. `sequence` makes "new vs already presented" decidable without a ChatGPT-side write.

Owner decision needed: README still describes the task as updating the #431 title and posting `/fpl-master-tick`. The
V12-R architecture requires a read-only consumer. If the live prompt still does that, those steps must be removed by the
owner; this proposal deliberately does not guess the prompt's current text.

## 3. Cross-CPU proof revalidation before 2026-11-08

The frozen proof (`config/performance/v12_runtime_cross_cpu_proof.json`) now points to run 40183897457 (artifact 12594569816, 90-day retention, expires 2027-01-23); the previous run 40148055764 expired on 2026-11-08. Without weakening any gate:

1. On or before 2026-11-03, list recent successful `pull_request` runs of `Repository governance` and their
   `v12-runtime-cross-cpu-acceptance-<run>` artifacts that are not expired.
2. Accept a candidate only if its JSON has `status` PASS, `proof_mode` DIRECT_CURRENT_HEAD_MULTI_CPU, at least 2
   physical CPU models, `output_sha256` equal to the registry value, a head that is an ancestor of `main`, and the run is
   `pull_request` + success. (A run that only proved VERIFIED_TRANSITIVE is not acceptable.)
3. Re-register through a focused PR changing only the registry JSON, README sync and PR metadata; the gate script is not touched.
4. Durable option (needs approval): raise `retention-days` of the acceptance upload from 14 to 90. It does not change any check;
   it only lengthens the evidence lifetime.


## 3. Separate evidence levels (never merge them)

| Level | Meaning | Evidence | Status 2026-10-25 |
| --- | --- | --- | --- |
| PRIVATE_PUBLISHED | exact occurrence passes private readback and terminality | audit VERIFIED_PUBLISHED | none since 2026-10-24 |
| POINTER_VERIFIED | `latest/verified.json` holds the occurrence, ADVANCED event in the orchestrator step | step summary and file | not yet produced (file 404) |
| CHATGPT_READABLE | the task can read the pointer and the body path and the SHA-256 matches | ChatGPT run transcript supplied by the owner | UNVERIFIED |
| CHATGPT_RENDERED | the verified body is shown in the five-section layout | ChatGPT output supplied by the owner | UNVERIFIED |
| NATURAL_CHATGPT_OBSERVED | all above for a naturally scheduled occurrence (`origin` SCHEDULED_OR_FALLBACK) and an unmodified hourly task run | independent observation x3 | 0/3 |

A RECOVERY-origin or manual occurrence can reach the first four levels but never the fifth.


## 4. Mandatory presentation contract (five sections)

Authority: `config/intelligence/v12_five_section_presentation_v1.json`, implemented and tested in
`src/engines/v12_five_section_presentation.py` (presentation only, no calculation).

| Top-level section | Canonical sections (verbatim, canonical order) |
| --- | --- |
| 1 OVERVIEW & ACTION | S01, S03, S04, S05, S09, S10, S18 |
| 2 OUR15 & XI | S02, S06, S06B, S07, S08 |
| 3 ANALYTICS | S11, S12, S13, S14, S14B, S16, S16B (when due) |
| 4 MINI-LEAGUE & COMPETITIVE | S15B |
| 5 FINAL DECISION & QA | S15, S17, S19 |

Producer side (fail closed): `ops/verified_pointer.py` builds the five-section view of the DEEP body and validates it
before any pointer write: exactly five sections in order; every canonical section present once and verbatim; XI of 11
without duplicates; bench of 4 disjoint from the XI; XI consistent between S06 and S19; planning GW equal to the history
path GW; logical slot equal to the occurrence slot; C and VC distinct, inside the XI and identical across S08, S18 and S19;
a DEGRADED report state stays explicit; the S06 pitch block is not dropped. Any failure raises
`PRESENTATION_CONTRACT_FAILED` and `latest/verified.json` is not advanced, so the report is never presented as canonical.
Entries carry `presentation_contract: FIVE_SECTION_V1_PASS`. The consumer must also refuse an entry without it.
Not changed: report production, the publisher, `latest/*`, the ChatGPT task, the scheduler, #431 and recovery activation.
