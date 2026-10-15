# P0 coach / formation / role evidence, 15 October 2026

## Scope and invariant

This is the FIRST STAGE of source-native ingestion and retrospective observability,
**not** a completed model improvement or a green model-calibration claim.

- V6 remains the sole factual data authority.
- `V12_PLAYER_MINUTES` remains the only P(start)/xMins mathematical owner.
- The 667-player frozen GW7 prospective forecast is immutable.
- No scheduler, PR #809, Stage3, MC500K, eight legal formations, or P1.7 changes.

## Verified match-details ingestion contract

`src/runtime_v6/domains/acquisition/fotmob_tactics.py` parses FotMob
`matchDetails` content only when the **same V6 source occurrence** has
explicitly collected a declared `match_details_<native_id>` request.

Admission requires native match ID, league ID 47, both FotMob team IDs,
verified V6 fixture and team crosswalks, valid observed formation, and
player-native-to-Official FPL IDs already verified in the V6 identity map.
No fuzzy names/club/kit-number promotions. An unmapped starter remains
unmapped, never implicitly attributed to an Official FPL player.

`source_native._fotmob` preserves the observations and the response SHA
in `record_groups.match_tactics`. Retrospective V12 joins them only when
the source is GREEN/NORMALIZED, source effective_at precedes the exact
report observation cutoff, the source SHA belongs to the source occurrence,
and the Official fixture/GW/teams were independently verified.

These observations capture reported coach identity, observed formation,
and the **provider position ID** of verified starting players. FotMob
position IDs are NOT true tactical role classifications. A coach name does
not establish a manager-specific starting probability. No observed role
label, formation fit score, coach fit score, or numeric P(start) is invented.

## Remaining blockers (do not mark PASS yet)

1. **Coverage acquisition:** The existing FotMob V6 registry polls the
   league/fixture endpoint only. It does NOT yet schedule native matchDetails
   acquisition across the complete GW1-GW6 historical fixture set or future
   fixtures. An explicit bounded, rate-governed match-details acquisition
   plan is needed; this patch does not create a new scheduler.
2. **Crosswalk coverage:** Native FotMob player IDs require independently
   verified Official FPL identities, and team/fixture conflicts must fail
   closed. Count genuine mapped starters, not provider mentions.
3. **Source-as-of:** Post-match retrieved lineups are RETROSPECTIVE ONLY.
   Their collection time must never be backdated to historic FPL deadlines.
   Manager changes require match-level timelines, not a static 2026 coach list.
4. **Target role:** Observed starting slot/position and coach's tactical
   assignment must be distinguishable. Build time-indexed competition for
   the same tactical slot, expected next-match formation distribution, and
   positional substitutions. Do not confuse FPL MID/DEF with a tactical role.
5. **Quantitative calibration:** Keep the new features in shadow until
   prospective predeadline snapshots and completed GW outcomes support
   walk-forward by position (Brier, log loss, xMins MAE, DNP, cameo),
   including team/manager-change stress tests and noninferiority versus
   the current canonical baseline. Use hierarchical shrinkage and zero
   model weight when context is unavailable or unverified.
6. **Operational acceptance:** Mandatory tests, postmerge CI, controlled
   V6 ingest, exact occurrence public/private readback and SHA256,
   then genuine natural report acceptance are separate receipts.
   PR GREEN alone is not MODEL_RESOLUTION FULL.

## Immediate code acceptance

Regression cases verify (a) provider fixture/team crosswalk and native
player identity, (b) mismatched source fixture fail closed,
(c) V6 matchDetails ingestion path, (d) same-source SHA/readback admission,
and (e) advisory-only, no fabricated P(start).

Until independent complete data and outcome calibration exist, retain
`LIMITED_RESOLUTION` and explicit context blockers.

Change timestamp: `2026-10-15T05:56:22+07:00`
Documentation sync: UPDATED
Documentation timestamp: `2026-10-15T05:56:22+07:00`


## Stage T1 follow-up: verified player-fixture context ledger

The retrospective context builder now produces V12_VERIFIED_PLAYER_FIXTURE_CONTEXT_LEDGER_V1
from original lossless Official FPL GW1-GW6 player fixture records, conditional on
the same verified Official fixture catalog, club/GW identity, Official finality,
and source time at the exact report observation cutoff. Each actual fixture row
has element_id, fixture_id, gw, team_id, coach_id, formation, observed_role,
started, minutes, availability, source_id, observed_at, finalized_at, confidence,
admission_status, rejection_reason, provider_position_id, selection_class and
temporal admission flags. Missing original finalization timestamp means
finalized_at=null, never a fabricated date.

- Official starts/minutes come only from the original Official fixture row.
  Missing starts or invalid minutes cannot prove a start. Minutes alone are
  not proof of starting.
- No fixture row for an Official DNP/BLANK GW becomes a separate UNAVAILABLE
  non-fixture row; no fixture or bench status is invented. Club/GW identity
  conflict, duplicate, unfinished fixture, unverified source time and invalid
  Official selection metrics fail closed.
- Verified FotMob coach/formation are ADVISORY. A verified 64-hex source digest,
  matched fixture/team and player-club identity are required. Provider position
  IDs are NOT tactical roles. Missing coach native ID, tactical role, injury
  availability and finalization timestamp remain null/UNKNOWN.
- Three or more duplicated tactical provider team/fixture observations cannot
  re-admit an earlier conflict. The first duplicate permanently blacklists
  that team/fixture key for the occurrence.
- Full ledger rows plus coverage counters by Official FPL position and club
  are available from the builder. Mobile DEEP retains compact coverage
  counters and only focus-player rows, not thousands of rows inside the
  22-section report. This is not a second V6 factual authority or a new
  private publication.
- Existing mandatory regression test nodes are extended, not replaced.
  Canonical P(start), xMins, MC500K, original GW7 forecast and scheduler
  remain unchanged.

**T1 blockers:** Governed full-match matchDetails collection is missing from
the existing V6 source registry; verified fixture-level coach IDs and tactical
role semantics remain incomplete; position competition/rotation and
predeadline injury/availability are not calibrated; historical GW1-GW6
source-as-of remains NOT_ATTESTED. Actual club/position coverage from a
fresh controlled production occurrence and remote receipt are not yet
established. Until then CHELSEA_CONTEXT=PARTIAL, not PASS.


## T1 retrieval continuation: existing V6 FotMob bounded matchDetails

On the original V6 FotMob source poll, `fotmob_backfill.collect_fotmob()`
reuses the **single** declared league request and performs up to eight
supplemental `/api/data/matchDetails?matchId=<native>` HTTP GET requests.
Only GW1-GW6 provider-finalized, noncancelled fixtures are candidates.
Chelsea fixtures (FotMob team 8455) are first; all teams follow.
A daily budget of 80 reserved HTTP attempts accounts for two retries
per request. Responses are separately SHA256-bound and immutable in the
V6 source-native snapshot, with their original observed timestamp.
Failed, blocked, or truncated requests are marked PARTIAL; the public
Official FPL source is not blocked by optional FotMob access failures.

`coverage.fotmob_match_details` separates retrieval completion from
**independent crosswalk/formation/coach/role admission**. A complete
download is not a tactical admission PASS. Full player fixture ledger,
verified role, available-by-deadline injuries and rotation features remain
unproven. No historical as-of timestamps are manufactured.
No change to scheduler, P1.7, Stage3, MC500K, V12_PLAYER_MINUTES,
original frozen GW7, or PR #809. The first legitimate postmerge
V6 occurrence and native DEEP production readback still need verification.

Change timestamp: `2026-10-15T06:24:03+07:00`
Documentation sync: UPDATED
Documentation timestamp: `2026-10-15T06:24:03+07:00`

## T1 follow-up: verified pitch-layout and explicit matchday absence shadow

Actual first postmerge FotMob backfill (PR #1093, V6 controlled run
38655450691, main SHA 2587a01f0ae0731d2075f763dbe0d2ce1d4a9eb0)
successfully persisted 8/60 GW1-GW6 matchDetails, including all six Chelsea
fixtures, 53/66 verified Chelsea starter-native-to-Official FPL mappings
and 6/6 verified retrospective manager/formation observations. The current
crosswalk leaves 13 Chelsea starter observations unmapped; it must not
promote names, shirt numbers or provider positions into player identity.

The matchDetails payload also contains provider `horizontalLayout`
coordinates for each starter, a matchday `subs` list and sometimes an
explicit `unavailable` list with an injury/suspension type. This T1 patch
preserves only validated 0..1 pitch coordinates, already independently
verified player IDs, mutually exclusive starter/bench/unavailable states
and provider-reported absence reasons. A raw provider positionId or
geometric coordinate is not a calibrated true tactical role.

Retrospective V12 now emits an advisory, SHA-bound team selection shadow
with per-player observed starts/slots, provider bench and unavailability
notes, and same-coach/formation/positionId candidates across observed
fixtures. This is a descriptive indicator of observed slot reuse,
NOT causal proof of competition, rotation probability, manager fit,
future injury status, or a predeadline input. Any external absence record
created after a historical GW must never enter an earlier forecast.

The existing 54-file/1419-node required V12 test manifest is unchanged;
the existing mandatory tactical-history node now checks source-native
selection conflict and postdeadline refusal. Future calibration remains
a separate gate, not authorized by these observations. The one V6 factual
authority, one V12_PLAYER_MINUTES numeric owner, frozen GW7, PR #809,
MC500K, P1.7 and Stage3 remain untouched.

Change timestamp: 2026-10-15T06:47:16+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T06:47:16+07:00


## T1 full-league coverage admission (20 clubs)

**P0 T1 20-club evidence scope (15 Oct 2026):** Retrospective tactical coverage now reports all 20 Official FPL clubs over GW1-GW6 (120 finalized team-fixture observations expected from 60 finalized league matches), not only the Chelsea focus view. Separate exact verified coach/formation observations, native manager IDs, starter identity shortfalls, matchday bench/unavailable, per-fixture manager/formation timelines and observed same-slot rivalry counts. Every club has its own missing fixture IDs and full/partial/unavailable flag. All claims remain post-match ADVISORY only, with semantic tactical role and historical predeadline availability unverified. Original rate cap (8 matches/cycle and 80 reserved attempts/day), V6 factual authority, canonical V12_PLAYER_MINUTES owner, forecast GW7, MC500K, Stage3, P1.7, single scheduler and PR #809 unchanged. Change timestamp: `2026-10-15T07:30:00+07:00`. Documentation sync: UPDATED.

Evidence scope: separately count 60 league fixtures vs 120 club/fixture sides, and never treat 16 retrieved matches as 16/120 team sides. A post-match manager or observed pitch coordinate does not establish a historical predeadline role, player readiness, coach-fit, expected minutes or P(start). The 20-club ledger is a compact report inclusion, while focus-team per-player detail stays bounded for mobile reports. Required existing tactical test node validates a 20-team, 60-match synthetic denominator including 120 side occurrences and missing identities without inventing evidence.

Remaining operational gates: finish rate-bounded historical match details via existing V6 occurrence, verify native DEEP source binding and private delivery, and accept a real natural occurrence separately. No retrospective evidence substitutes for forward role/availability calibration.

Change timestamp: `2026-10-15T07:30:00+07:00`
Documentation sync: UPDATED
Documentation timestamp: `2026-10-15T07:30:00+07:00`


## T1 unmatched native starter review provenance, 15 Oct 2026

Persist source-native FotMob starter IDs which fail deterministic Official FPL mapping, in the verified occurrence-bound V12 per-match history and all-20-club review summaries. No name, kit number, position, or pitch layout is used to infer a canonical player. Native ID candidates are never admitted to P(start)/xMins, historical predeadline availability, semantic tactical roles or the immutable GW7 forecast. Distinct candidate IDs and repeated observations must not be confused with distinct FPL players. Existing mandatory tactical history regression checks preserve fail-closed behavior.

At the 07:44 WIB controlled V6 cycle the immutable public provider had 40/60 matchDetails, 80 team-sides and 533 mapped starter observations out of 880 slots. FotMob's reserved request budget was 80/80 for the Jakarta day and prohibited the remaining 20 acquisitions in that day. Preserve the cap of 8 per occurrence and 80 reserved attempts/day; complete future retrieval through original governed V6 occurrences only. Stage1 model and natural report acceptance remain NOT PASS until independently validated.

Change timestamp: 2026-10-15T09:36:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T09:36:00+07:00


## T1 alternative independent Official starting-XI completeness

The remaining 20 FotMob matchDetails cannot be fabricated while the original 80/80 reserved-attempt daily limit is exhausted. Official FPL fixture-level `starts`/minutes is a separate authoritative source already collected inside V6 and does **not** consume FotMob HTTP quota. `V12_OFFICIAL_INDEPENDENT_STARTER_COVERAGE_V1` now computes per finalized GW1–GW6 fixture and per club whether 11 distinct starters are established by original `OBSERVED_VERIFIED` Official player-fixture rows. Missing starts, duplicates, unfinalized fixtures, invalid player identity and source cutoff remain PARTIAL/UNVERIFIED; do not invent substitution or bench identities.

This is an independent additional **selection** gate only. It never upgrades the FotMob matchDetails 40/60 tactical observation count, manager/formation role calibration, historical predeadline availability or MODEL_RESOLUTION status. The 20 missing FotMob games and 117 native ID crosswalk candidates remain explicit, and all numeric P(start)/xMins, MC500K, Stage3, P1.7, one scheduler, PR #809, and frozen GW7 remain unchanged. The new field is retrospective advisory and carries no prediction influence. A controlled V12 run must read back the exact new field before production delivery claims.

Change timestamp: 2026-10-15T10:05:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T10:05:00+07:00


## Verified current15 observational binding versus calibrated model signals (15 October 2026)

The source-native, immutable private GW7 prospective capture for 2026-10-15T10:14:00+07:00 records 667/667 verified Official FPL status observations and 424/667 advisory tactical-role profiles. Its separate S02 15-player audit displayed 0/15 because this current source readiness was not independently bound to the user-report diagnostic. Source observational completeness must not be misreported as numeric calibration.

The read-only fail-closed V12_CURRENT15_BOUND_SOURCE_SHADOW_V1 bridge binds only exact-occurrence V6 Official bootstrap status, same-team player identity and existing advisory role profile to current15 audit rows; an absent/mismatched source produces UNAVAILABLE. It separately counts source-SHA-verified manager appearances in the GW1–GW6 *retrospective* timeline, without claiming an active future manager or causal fit. All three counts are reported independently of role/manager calibrated start signals. The latter remain 0 if no timestamp-correct, position-wise out-of-sample validated features exist.

Canonical V12_PLAYER_MINUTES P(start)/xMins, 500k MC, frozen GW7, P1.7, Stage3, single scheduler, and PR #809 remain unchanged. Do not declare FULL_RESOLUTION until both quantitative evidence and as-of noninferiority gates truly PASS. External historical FotMob coverage is still 40/60 under 80/80 daily reservation; this bridge does not bypass it.

Change timestamp: 2026-10-15T10:33:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T10:33:00+07:00

## Alternate provider acquisition: ESPN (15 October 2026)

Native FotMob matchDetails remains only 40/60 successful for GW1–GW6, original 80/80 reserved request attempts consumed on 15 Oct. Do not bypass FotMob request cap, change cache origins or label another provider's records FOTMOB.

Use the **existing V6 ESPN poll** to retrieve independent completed ESPN scoreboards for source season calendar dates 12–14 Sep, 18–20 Sep, 10–12 Oct 2026, and native ESPN match summaries in later governed occurrences. The adapter enforces 48 reserved HTTP retry attempts/day and six requests/occurrence, SHA-256 native payloads, exact source date/event status, source identity and cache reuse. ESPN native fixture/event identifiers and summary data are **not** automatically identified as Official FPL fixtures, players, managerial effects or source-as-of historical probabilities. Only controlled identity mapping and separate verified role calibration may promote factual context. If ESPN summary endpoints are blocked or absent, report PARTIAL and retain the original source independently.

Source exposure and intrinsic limits: 20 missing FotMob matchDetails cannot be counted as rescued FotMob matchDetails by an ESPN scoreboard. The source may give alternative independent match evidence without changing FotMob 40/60. This archive is not yet a fully mapped coach/role replacement nor a green P(start) gate. Keep all one-scheduler, V6 factual, V12_PLAYER_MINUTES sole numeric owner, MC500K, immutable forecast and Stage3 fail-closed contracts unchanged.

Change timestamp: 2026-10-15T13:07:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T13:07:00+07:00


## T1 manager/role longitudinal all-club phase, 15 Oct 2026

All twenty clubs now receive an auditable GW1–GW6 sequence of *observed* coach native ID, observed formation, actual known mapped Official FPL starter identity and opaque provider position slot. The pipeline counts observed changes between consecutive **covered** matches and preserves the original source SHA. It does not guess missing fixtures, active target GW7 coach or role semantics. Duplicated fixture/team, invalid SHA and mismatched player team fail closed.

The full 667-player longitudinal panel remains inside the governed retrospective builder. Native DEEP transports only source coverage and the 15-current-squad exact-ID panel, with the unverified tactical role and manager-effect probabilities explicit. No new P(start) signals, no parameter retuning, no forecast GW7 overwrite, no historical predeadline as-of claim. A previous controlled V12 run 38677939541 failed after a private push collision despite partial receipt delivery, and must not be called successful. Resolve private writer race separately, then require CI and source-bound remote readback before real production acceptance.

Change timestamp: 2026-10-15T11:08:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T11:08:00+07:00
