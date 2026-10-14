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
