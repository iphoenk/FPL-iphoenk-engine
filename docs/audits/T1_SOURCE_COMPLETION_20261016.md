# Stage 1 V6 original source readback

Natural acquisition run 38794783116 on 2026-10-16 02:33 WIB provided 60 distinct original FotMob match details, 30 ESPN summary rosters, 120 retrospective coach/formation team-fixture observations, and 1320 independently official starter observations. Public core and publish integrity PASS.

Only 784 FotMob starter observations have provider-to-Official FPL certified IDs. The remaining 536 require independent crosswalk admission. Historical GW1–GW6 predeadline source-as-of and GW7 settlement remain unverified. This evidence does not change V12_PLAYER_MINUTES, source authority, Stage3 or GW7 frozen predictions.

## Exact-multisignal retrospective reconciliation (no canonical promotion)

Rechecked the same V6 retained original matchDetails and Official history:
327 distinct FotMob native IDs across all 1,320 GW1–GW6 starter observations.
Existing independently certified bridge: 193 native player IDs / 784
starter observations. The remaining 134 FotMob native player IDs /
536 starter observations admit **unique retrospective review candidates**
when verified by: exact fixture starter-presence signature, constrained
name matching (exact full display or exact normalized name tokens,
not approximate string similarity), approximate source age against Official
birth dates, no reverse collisions, and zero contradictions against 784
independently verified source mappings. These 536 must remain candidate-only,
not official identity links, before an independent provider-ID crosswalk or
separately approved trusted admission proof exists.

Alternative identity source research: public Reep v0 CSV was frozen on
21 June 2026. Reep v1 public register exposes newer cross-provider bridges
on stamp `20261005T180536Z`, including published separate `bridges.csv.gz`
and checksums, at https://reep.football/data/. This is a promising source
for exact FotMob native ID -> Opta numeric (Official FPL `code`) bridges,
but its raw CSV was not retrieved in this constrained tool environment.
No Reep v1 matches are falsely claimed. v0 and v1 Reep internal IDs must
never be interchanged without an explicit bridge.

Production end-to-end Stage 1 source completeness is proven. Full
MODEL_RESOLUTION remains UNVERIFIED because independent predeadline
GW1–GW6 source archives, per-player accepted identity, and
prospective GW7 calibration are different acceptance gates.

Proof: https://github.com/iphoenk/FPL-iphoenk-engine/actions/runs/38794783116
Audit instance: FPL_Stage1_Identity_Candidate_Reconciliation_20261016.json
Numeric P(start) effect: NONE
GW7 immutable modification: NONE
Scheduler additions: NONE
Change date: 2026-10-16
Documentation sync: UPDATED
Documentation date: 2026-10-16

## Identity bridge independent readback — 16 October 2026

The earlier 536 unjoined source-native starter observations are now resolved
by 134 **new exact provider-ID** bridges in the Reep v1
release `20261005T180536Z`, with direct, namespace-scoped chain:

`fotmob/person -> Reep v1 ID -> opta/person_numeric == Official FPL bootstrap.elements.code`.

A second controlled PR-run `38812432637` inspected ALL originally observed
FotMob source native player IDs across 60 historical match details and 82
league-stat player records. The resulting count is 332 distinct natives:
327 starter natives plus five league-only natives. All 332/332 joined exactly
to Official FPL; no ambiguous/multiple provider mappings, no mismatches against
193 previously certified starter mappings. Of the five additional league-only
natives, two were already in v0 crosswalk; three new IDs are promoted.
Therefore exactly 137 **new** v1 rows are added to 352 existing configured
FotMob rows -> 489 configured source-native player links.

Evidence: https://github.com/iphoenk/FPL-iphoenk-engine/actions/runs/38812432637
First 327-starter ID audit: https://github.com/iphoenk/FPL-iphoenk-engine/actions/runs/38811691738
Source immutable V6 Git SHA: `dada6d7962ea25576e3e12bc0f501fd065f9f064`
Published Reep v1 gzip SHA256:
`ccfe36b94612890102d89159b82eb92f22245151b4b7ebbf2859e38f069d7731`.

This source/native identity evidence is prospective model-advisory only until
the original predeadline historical feature snapshots and calibrated numeric
P(start)/role/manager/availability predictions pass their own strict gates.
No historic-as-of or GW7 future settlement claim is made. No scheduler added.
No frozen GW7 or P1.7 / Stage3 / MC500K / PR #809 mutation.

Change timestamp: 2026-10-16T04:31:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-16T04:31:00+07:00

## Original-source historical XI identity acceptance: 16 Oct 2026

The first natural V6 snapshot after merged PR #1112 (GitHub publication run `38814078563`) contains 60/60 uniquely Official-bound original FotMob native matchDetails, 120/120 tactical sides and **1,320/1,320 provider starters already annotated with certified Official FPL IDs**, with zero source-unmapped starter IDs. Comparison against the separately published Official FPL GW1–GW6 partitions finds **zero lineup differences**, 327 unique observed native starter IDs, and 60/60 full-length SHA256 source snapshot digests.

`scripts/v6_stage1_observed_xi_identity_gate.py` is a read-only fail-closed acceptance gate for exactly this retrospective observation scope. It requires all Official six GW partitions finalized and 60 fixture IDs with 120 coach/formation sides, verifies each of 1,320 starters and dual-source identity consistency, and rejects duplicates, missing source/ID/SHA, mismatching historical lineup or stale source authority. No historical result is allowed to infer past predeadline feature availability.

Stage1 `OBSERVED_HISTORICAL_PLAYER_IDENTITY=PASS` is deliberately separate from `FOTMOB_SOURCE_WIDE_IDENTITY=AMBER`, because the FotMob observed league stats are 82 native players versus all 667 Official FPL players. The provider has not proven whether each of the 178 unbridged Official players lacks provider presence. Therefore global absence is NOT asserted, and no existing provider health label is overwritten.

Historical predeadline training-feature finalization: NOT ESTABLISHED. Semantic tactical player roles and calibrated manager/availability P(start) effects: NOT ESTABLISHED. Prospective GW7 calibration: PENDING real final matches. No mutation to Stage3, frozen GW7 or scheduler.

Change timestamp: 2026-10-16T05:07:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-16T05:07:00+07:00

## Stage 1 exact-667 Official scanner production hardening (16 Oct 2026)

The original naturally acquired V6 historical source proof remains **60/60 FotMob matchDetails**, **30/30 ESPN match rosters**, **120/120 verified coach/formation team sides**, and **1,320/1,320 independently verified FotMob-to-Official FPL starter observations**, without any invented predeadline training or model-calibration admission.

The earlier controlled DEEP occurrence `DEEP|2026-10-16T10:20:00+07:00` includes the visible Stage C scanner line **Official=667, eligible=667, scanned=667, coverage=COMPLETE** in private original `reports/2026-27/gw_7/20261016_102000_plus_0700/report_body.md`. That line is useful controlled runtime evidence, not an independently reconstructed natural scanner receipt.

Follow-up hardening fixes an integrity gap in `build_stagec_from_canonical_inputs`: the Stage B source-membership audit must require the **season-wide fixed 667-player Official FPL authority**, not silently set its expected count to the possibly incomplete bootstrap size. An otherwise internally consistent 666/666 or 668/668 snapshot is now **FAIL**, never `COMPLETE`. Nine fail-closed regression nodes cover exact 667, truncated or overcomplete Official bootstrap, mismatched scanner membership and provider-provenance separation.

**Two independent coverage scopes must never be conflated.** The canonical Official FPL scanner has 667/667 membership evidence and does not depend on FotMob identity presence. The historically verified FotMob source mapping is 489/667 configured player links, while 178 other Official elements have unproven source presence; this is **provider-wide PARTIAL/UNVERIFIED**, not 178 missing Official scanner players. When no verified provider bridge list was supplied to a specific scan, provider coverage now reports **NOT_EVALUATED** with null counts instead of a fabricated 0/667. There is no new bridge, backfilled missing row, or false provider-full claim.

**Stage 1 source/observed-identity/Official scanner contract:** fully captured by above records, pending postmerge exact-667 readback of hardened code. **Stage 2 model-context/calibration contract:** coach-to-player tactical role, pre-match injury/availability, predeadline fold parameter witnesses and actual future GW7 outcomes remain independent and unverified; none is represented as Stage 1 acquisition failure. Historical GW2–GW5 predeadline reconstruction was explicitly skipped, and its admission gate remains `NOT_ESTABLISHED`.

No new scheduler, cron, numeric P(start)/xMins changes, frozen GW7 forecast overwrite, Stage3, MC500K, or PR #809 edits.

Change timestamp: `2026-10-16T13:03:00+07:00`
Documentation sync: UPDATED
Documentation timestamp: `2026-10-16T13:03:00+07:00`
