# P0 Wave 3 original Git runtime pin, 14 October 2026

## Evidence and root cause

Genuine natural 21:00 WIB run `38581998577` published original root commit `f9a8af9612eee5154b9f29d7cfc0ec8b917306c9`, as recorded in its successful source publish job `115914272353`. Its Wave 3 observer `38581998485` failed with `runtime branch no longer points to the source run generation`, because the `runtime-data-v6` branch tip is a mutable CAS output and can be advanced by unrelated legitimate publications. Natural 22:00 WIB observer `38590677403` succeeded, but reset the consecutive acceptance window to one; 12/12 remained false. This is original GitHub Actions evidence, not a new natural occurrence.

## New source-of-truth admission

Read successful original source publisher job log using the original publish job ID, require unique SHA of the actually published Git root commit, match its explicit `PUBLISHED_RUNTIME_SHA`, retrieve the original immutable Git commit by SHA, and compare the exact bytes of `data/v6/health/candidate_freeze.lock` and `data/v6/health/publish_integrity.json` against the matching source workflow artifact. Verify original source run ID and attempt, the dedicated publisher commit message, true frozen state and publish_integrity PASS. Never check the moving branch tip for a historical source run.

## Hard boundaries

No controlled/manual run becomes natural, no inferred or backdated slot is accepted, original job, repository, event, source head SHA, logical occurrence, chaos acceptance and 12/12 proof remain mandatory. Original logs or Git object absent/ambiguous -> fail closed. This is code repair, NOT 12/12 production acceptance. Genuine future natural occurrences must prove the fix.

Four review tests exercise original SHA parsing, ambiguity rejection, positive original Git-object byte equality, and fail-closed mismatched identities/content.

Change timestamp: 2026-10-14T23:09:39+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:09:39+07:00
