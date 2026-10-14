# P0 P(start) individualization

Status: implementation candidate, 2026-10-13 UTC. Documentation timestamp: 2026-10-13T21:10:00+07:00.

## Change

`V12_PLAYER_MINUTES` remains the only mathematical owner. Verified
`V6_NORMALIZED_PLAYER_MATCH_ROWS` now supplies a player-conditioned selection
posterior when available. The posterior uses exact official element identity,
match-level starter outcomes, a conservative neutral Beta prior, and a recent
three-match window. Provisional, pending, unavailable, and ambiguous rows are
excluded. No coach-fit or tactical-fit claim is converted into a probability.

The projection builder uses the verified match-level starts and minutes for
P1.1 when present. Official aggregate fields remain the fallback when the
match-level evidence is absent. This prevents five identical aggregate inputs
from being mistaken for individual evidence.

## Published evidence

Each P1.1 output includes `selection_evidence`, its source, observed-match
count, start and recent-start rates, minutes when starting, and an explicit
missing-evidence reason. S02 acceptance separates evidence binding, historical
coverage, individual evidence, model resolution, calibration, temporal
integrity, and production verification.

## Safety boundaries

- No player override is hardcoded.
- No second P(start) owner is created.
- FPL injury flags remain observations, not probabilities.
- Coach and formation evidence remains advisory unless calibrated.
- Provisional GW6 observations cannot become FINAL through this change.
- Stage2 cache fingerprints already include the player-match evidence and the
  model/config dependency hashes, so evidence or model changes invalidate the
  derived cache.

## Validation required before promotion

The existing golden and contract suites must pass. A walk-forward backtest
must compare starter Brier score, log loss, calibration, xMins error, DNP and
cameo calibration by position and team. Six gameweeks are evidence coverage,
not sufficient sample size for claiming high calibration confidence.

## GW1–GW6 player selection: resolution and universe calibration acceptance

**Canonical mathematical owner remains V12_PLAYER_MINUTES.** The resolution
audit now compares provenance-backed player selection inputs, reports shared
rounded P(start) with identical/different evidence fingerprints, and explicitly
separates historical individual evidence from missing calibrated role, manager,
prior and availability signals. Probability diversity alone never promotes a
model. Report S02 shows these diagnostics without changing xMins or xPts.

The Stage1 V6 normalized official match fixture rows now feed an expanding-GW
paired backtest of the *existing* baseline and individual posterior model,
using GW strictly earlier than the target for training. Diagnostics include
starter Brier/log loss, xMins MAE, DNP/cameo Brier, reliability bins and per
GK/DEF/MID/FWD and team metrics. Rows with invalid identity, minutes,
duplicate fixture or provisional state are rejected. No synthetic player
override, parameter retuning or second model is introduced.

A **retrospective split is not archived predeadline proof**. Production
calibration is `RETROSPECTIVE_DIAGNOSTIC_ONLY` unless historical predeadline
source finalization timestamps and deadline identities are available and
passing, position sample coverage is adequate and individualized model is
noninferior on all specified paired metrics. Without those facts:
`CALIBRATION` and `MODEL_RESOLUTION` must not claim FULL/PASS, even if the
calculation or entire 667-player dataset completed successfully.

Explicit tolerances, fixed in the diagnostic (not optimized on holdout):
overall Brier delta <= +0.01, log loss <= +0.02, xMins MAE <= +1.0, DNP/cameo Brier delta each <= +0.02. For every GK/DEF/MID/FWD position, Brier delta <= +0.03, log loss <= +0.02, xMins MAE <= +1.0, DNP/cameo Brier delta each <= +0.02.
Diagnostic eligibility requires >=200 paired fixtures and >=25 per position,
plus >=95% player-universe coverage, predeadline lineage and zero temporal/partition errors. Report
`NONINFERIORITY` separately from `SOURCE_AS_OF`.

This is an evidence and promotion-gating change, not an asserted accuracy
improvement. Future genuine predeadline archives are needed for formal
calibration promotion.

Change timestamp: 2026-10-14T05:45:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T05:45:00+07:00

## Official GW deadline and source-as-of ingress (14 Oct 2026)

The live V12 analytics foundation now forwards Official FPL historical `events[].deadline_time` for completed GWs and only an explicitly recorded normalized match-row `finalized_at` to the existing P(start) walk-forward validator. Current-cycle `source_checked_at`, normalized dataset `effective_at`, and report timestamps must **never** be substituted for historical finalization. The current V6 Official FPL source-native rows supply current-cycle `source_checked_at`, but do not yet publish independently archived per-match finalization evidence. Consequently existing GW1–GW6 production remains `RETROSPECTIVE_DIAGNOSTIC_ONLY`, despite noninferiority, until genuine immutable predeadline sources are available. Full-model resolution also requires verified contextual inputs (role, manager, availability); no inferred values or artificial PASS labels are allowed.

Two required regression tests prove (1) valid prior archived finality and original deadlines reach the lineage gate without bypassing minimum sample/position requirements, and (2) a current-cycle check timestamp alone cannot pass the lineage gate. Governance reviewed required-suite node baseline becomes 1,396. No new scheduler or mathematical owner is introduced.

Change timestamp: 2026-10-14T09:42:32+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T09:42:32+07:00

## 14 October P0 archive audit and strict original-object admission

A separate read-only GW1–GW6 audit is at
`docs/audits/P0_PSTART_HISTORICAL_ASOF_AUDIT_20261014.md`.
The reachable `runtime-data-v6` HEAD on the audited checkpoint has zero
parents, while the sampled older GitHub Actions runs expose no retained
artifacts. None of the inspected material constitutes a verified original
historical predeadline snapshot for the five evaluated folds.

`walk_forward_pstart_validate()` now reports baseline and individualized
starter Brier, log loss, xMins MAE, DNP and cameo Brier **by position and
club**, as well as overall. All five metrics must be noninferior **in each
position**, not just starter Brier. It separately publishes
`historical_asof_status=HISTORICAL_AS_OF_UNAVAILABLE` and
`missing_original_archival_witnesses` rather than promoting timestamp-only
rows. A `finalized_at` and an official GW deadline *alone* are never proof of
an original immutable source object. An externally verified
`verified_source_archive` witness must reference the original Git commit,
its timestamp, source identity, snapshot identity, source SHA256 and exact
remote readback. The model foundation forwards such a witness only if it
already exists in normalized V6; it **does not create or attest one**.

**Critical outstanding work:** the independent original Git-object
verifier and immutable prospective GW7 freeze have not yet been deployed.
A JSON field claiming `remote_readback_verified=true` cannot prove
GitHub remote state on its own: only the trusted V6 verifier, anchored to
an actual immutable readback and receipt, may issue it. Until then production
`CALIBRATION` remains retrospective-only, regardless of code CI or
`READY_FULL`. Role, coach, availability and position-specific probability
adjustments remain advisory unless calibrated; existing V12_PLAYER_MINUTES
mathematics, Stage3, eight formations and MC500K are unchanged.

Change timestamp: 2026-10-14T10:00:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T10:00:00+07:00

## 14 October, additional read-only archive inventory and P(start) resolution integrity

The verified public V6 Actions run inventory includes natural/hourly acquisition runs on 12 September (`34725699713`, `34722950239`, `34720145902`), 19 September (`35476739571`), and 25 September (`36198244096`, `36156578313`). GitHub returns no retained artifacts for these inspected runs, or for earlier sampled runs `33452812166` and `35670033021`. This finding is scoped to inspected run artifacts. It neither proves absence of all historical objects nor creates original source-finalization timestamps. All affected GW1–GW6 folds remain `HISTORICAL_AS_OF_UNAVAILABLE` until genuine original Git-object lineage and deadline proof are admitted.

Model-resolution audit fixes three acceptance defects without changing canonical probabilities: all four context signals (prior, role, manager and normalized availability) must be present rather than any one; numeric signal vectors must be uniquely named, finite, range-valid and exactly match declared signals; explicit `model_probability_agrees=True` is required for full acceptance. Different verified inputs that round to identical P(start) are reported for review but no longer automatically count as an inference failure. Calibration `PASS` remains a separate hard prerequisite for `FULL_RESOLUTION`. The test suite exercises both valid rounded ties and incomplete/duplicate/unverified context.

No retrospective outcome is relabelled as predeadline, no role/manager/availability weight is tuned without calibration, and no new data authority or scheduler is introduced.

Change timestamp: 2026-10-14T15:23:39+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T15:23:39+07:00

## P0 role, manager and availability context observability (14 October 2026)

A quantified `normalized_availability_start_signal` is *conditional*: the canonical player-minutes owner introduces it for supported uncertainty categories, not for every player. Normal official status `a` is an observed FPL flag, never a 100% medical clearance or numerical start prediction. Consequently, the resolution auditor accepts a directly bound canonical S02 normal-status observation as an explanation for why no extra numeric availability feature was applied, while rejecting an unverified source, a doubtful status or unbound context. This does not waive the separate contextual role, manager, prior and calibration requirements.

Every S02 OUR15 row now includes read-only `pstart_context_evidence`: the official-status observation; active versus non-applied uncertainty signal; advisory observed role profile with source if present; and explicit `NO_VERIFIED_MANAGER_TIMELINE` if no suitable manager-conditioned source is available. Neither one known coach name nor one observed lineup proves a calibrated manager-effect probability. Fields are descriptive/diagnostic only. Model owner remains `V12_PLAYER_MINUTES` and its weights/output are unchanged.

Current source audit: V6 RotoWire normalized feed contains 220 predicted-lineup rows and 103 availability rows, but official player identity joins are not established in the inspected samples; the verified crosswalk catalog has no RotoWire mapping. An external predicted lineup is not an original official observed starting XI and cannot establish a historical role, manager, or medical fact. Extend the identity catalog only with an independently verified provider-native-to-official-player bridge, then preserve source effective_at and original as-of lineage before considering any numeric candidate. The 667-player GW7 prospective forecast is already immutable and should not be retrofitted with additional signals.

Calibration promotion remains blocked until independently verified predeadline evidence and out-of-sample settled P(start), DNP, cameo, xMins and per-position non-inferiority are available. Do not label this context-diagnostics improvement `FULL_RESOLUTION` on the current underlying data.

Change timestamp: 2026-10-14T15:59:22+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T15:59:22+07:00

## Prospective context-feature freeze (14 October 2026)

The existing V12_PSTART_PROSPECTIVE_PREDEADLINE_V1 producer now captures, in each new future occurrence before the Official FPL deadline, the canonical projection's role/manager/availability observability alongside the 667-player paired baseline/individualized probabilities. Each feature receipt is bound to the same immutable Official FPL source Git readback, and the complete row array remains SHA256 protected by the original forecast_rows_sha256 scheme. A field labelled original Git verified applies only to the canonical Official FPL source; external tactical role and manager timelines are explicitly UNVERIFIED and **never** admitted as numerical probabilities. The deterministic summary separately reports official status and advisory role counts. This is shadow observation, not a calibrated third model.

Existing immutable GW7 private forecast objects and receipts remain unchanged. Only new predeadline occurrences may carry the added context receipt. No scheduler, source authority, P1.7, Stage3 or correlated MC500K changes. MODEL_RESOLUTION remains LIMITED until verifiable original predeadline manager/role lineages and future settled position-wise non-inferiority exist.

Change timestamp: 2026-10-14T16:36:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T16:36:00+07:00


## 14 October 2026: RotoWire identity discovery, quantified and fail closed

Actual original V6 normalized RotoWire source snapshot as of 2026-10-14T09:33:52Z:
- 220 lineup observations, 102 availability observations, 312 unique native player IDs.
- 11 of 12 source fixture labels match a unique official fixture pairing and UTC kickoff; one UNKNOWN fixture has no accepted join.
- 273/312 identities have a **candidate** based on exact source name and club (260 canonical full-name+club, 13 Official FPL web-name+club), with an independently matched fixture candidate.
- The remaining 39 require provider-native ID/bio review; all 312 remain **UNMAPPED** as canonical V6 joins. Candidate strength is not proof of ID ownership.

Machine-readable immutable snapshot is in:
- docs/audits/P0_ROTOWIRE_IDENTITY_CANDIDATES_20261014.json
- docs/audits/P0_ROTOWIRE_IDENTITY_CANDIDATES_20261014.csv

Rebuild the read-only candidate review against normalized runtime-data-v6 artifacts:

    python scripts/v6_rotowire_identity_review.py \
      --rotowire data/v6/normalized/sources/rotowire.json \
      --canonical-players data/v6/normalized/canonical_players.json \
      --canonical-teams data/v6/normalized/canonical_teams.json \
      --canonical-fixtures data/v6/normalized/canonical_fixtures.json \
      --output /tmp/rotowire_identity_review.json

The report intentionally does **not** update config/v6/verified_crosswalks.json, V6 player_identity_map.json, canonical xMins/xPts or V12_PLAYER_MINUTES. Name + club + kickoff is candidate discovery, NOT a verified crosswalk from a RotoWire native ID to an Official FPL code. A new independent provider-native bridge with identity provenance, review evidence and conflict checks is required for VERIFIED_MANUAL promotion. RotoWire predicted lineups remain external model signals and injury labels remain secondary advisory claims even after verified identity. Do not use this snapshot as historical GW1-GW6 predeadline evidence.

The prior 220/103 figures were from an earlier inspected sample: this specific current snapshot has 102 availability rows. Release of the full contextual P(start) improvement still requires verified role/manager/availability as-of lineage and measured out-of-sample calibration by GK/DEF/MID/FWD. CODE GREEN alone is not MODEL_RESOLUTION FULL.

Documentation sync: UPDATED (14 October 2026).


## 14 October: Official-only teammate selection consistency

P1.1 target-player `V6_NORMALIZED_PLAYER_MATCH_ROWS` selection evidence was already
used in canonical `V12_PLAYER_MINUTES`, but the teammate-start probabilities
passed to directional linkups were previously recomputed from an aggregate
fallback without the same verified individual match-level evidence. The
`historical_projection` owner now caches one player-conditioned selection
receipt per Official FPL element and reuses it when projecting both the target
and each teammate. Confirmed starts and observed minutes are passed to the
same canonical player-minutes owner; absent rows retain its existing fallback.

This is an **input-consistency correction**, not calibration proof, verified
RotoWire mapping, new prediction owner, or an assertion of better out-of-sample
accuracy. No external lineup is admitted into numeric P(start), no predeadline
evidence is fabricated, and the immutable GW7 frozen forecast is unchanged.
Position-specific walk-forward noninferiority and postmerge run receipts are
separate acceptance gates. Stage3, eight formations, MC500K, scheduler
authority, V6 facts and PR #809 are untouched.

Change timestamp: 2026-10-14T20:05:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T20:05:00+07:00
