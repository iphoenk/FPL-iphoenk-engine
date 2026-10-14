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
