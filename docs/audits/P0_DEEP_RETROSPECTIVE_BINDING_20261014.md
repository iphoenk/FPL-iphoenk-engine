# Active DEEP retrospective source bridge: P0 recovery

Change timestamp: 2026-10-14T23:13:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:13:00+07:00

## Failure diagnosis

The S02 renderer consumed `full_season_history.retrospective_context`, but the exact-occurrence history summary supplied by the active `report_materializer` held coverage metadata only. The lossless original V6 `official_detail.json.gz` contains the match-level `players` evidence and was not being bound into the retrospective source context on this serving path. Unit tests of the standalone `build_retrospective_context` did not prove it ran in the actual materializer. The 14 October 21:30 WIB private DEEP report showed Understat joins=0 and FotMob matches=0 even as later V6 had 424 verified Understat identities and 380 verified FotMob fixture identities. Later records cannot retroactively qualify for that earlier 21:30 cutoff.

## Code changes

The active `report_materializer.run` now calls a read-only `_bound_retrospective_context` ONLY when the exact full-master original history sidecar has already passed occurrence validation. It independently decompresses the lossless original history archive and fail-closes unless archive + sidecar generated timestamp, logical report slot, contract and prefetch run identity all agree. Official element IDs, actual team IDs and position IDs come from the occurrence-bound Original Official FPL historical archive; an optional canonical name/fixture catalog is admitted only when its effective_at predates the report slot. Existing source builder independently enforces Understat/FotMob GREEN/NORMALIZED, original source effective_at cutoff, exact native-to-official IDs, GW scope, fixture team/round consistency, and duplicate rejection.

DEEP carries a compact advisory summary, relevant target players and source-consumption ledger; 667 full-player fixture rows remain solely in original V6 rather than inflating the user-visible report. Palmer and Rogers remain scoped by their separately verified official team IDs. The text `CHELSEA PLAYER PROCESS` becomes `FOCUS PLAYER PROCESS`, with each player's team ID displayed, so Rogers is not represented as a Chelsea player.

## Regression and acceptance

Two new governed tests verify same-occurrence bridge consumption and distinct Palmer/Rogers teams, and explicit rejection of post-cutoff Understat and mismatched prefetch run. Mandatory 54-file suite rises from reviewed 1408 to 1410 node IDs. Do not promote real DEEP joins, historical predeadline as-of, future GW7 settlement, calibration, Wave 3 natural slots, private auth/PRICE or ChatGPT UI until independent production receipts/readback prove each gate. No changes to PR #809, scheduler, V6 facts, `V12_PLAYER_MINUTES`, numerical P(start)/xMins/xPts, MC500K, Stage3 or immutable GW7 forecast.
