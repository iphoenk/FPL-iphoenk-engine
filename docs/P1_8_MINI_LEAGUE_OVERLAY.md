# P1.8 V12-native Mini-League Decision Overlay

## Baseline and boundary

P1.8 starts from exact GREEN baseline:

`c0fe860bd19b13490f70fcfe2c75f3ee93d41a85`

P1.8 is the final downstream decision overlay. It does not mutate P1.1,
P1.3, P1.6, P1.7, P1.2, or P1.4 mathematics.

The mandatory ordering is:

`football baseline -> freeze/fingerprint -> factual league context -> bounded overlay`.

## Current factual surfaces

V6 remains factual-only and unchanged.

Current official factual surfaces already available in the repository are:

- full paginated standings from
  `src/runtime_v6/domains/report_plane/league_prefetch.py`;
- normalized submitted picks by manager, including exact element ID, submitted
  squad position, scoring multiplier, designated captain, designated vice and
  active chip;
- explicit `expected_manager_count`,
  `submitted_picks_available_count`, missing-manager count, coverage percent
  and complete/partial state;
- current rank/points rows from Official FPL standings;
- historical current-cohort atomic facts under
  `data/v6/mini_leagues/<league_id>/history/`.

P1.8 consumes those facts downstream. It does not import V6 runtime modules and
does not publish analytics into V6.

## Denominator discipline

Every player exposure is represented as a count and denominator.

For the rival scope P1.8 publishes:

- ownership count / rival denominator;
- starter count / rival denominator;
- bench count / rival denominator;
- captain count / rival denominator;
- vice count / rival denominator.

Coverage is exactly one of:

- `FULL`;
- `PARTIAL`;
- `UNAVAILABLE`.

Scope is separately labelled as:

- `FULL_LEAGUE`;
- `TOP_N_RELEVANT_RIVALS`;
- `SELECTED_RIVALS`;
- `PARTIAL_FETCH`.

A partial fetch never becomes full merely because the collected subset has no
internal missing rows.

## EO semantics

Ownership is never called EO.

Exact submitted effective exposure uses Official scoring multipliers. A normal
starter contributes 1, a normal captain 2, Triple Captain can contribute 3,
and a submitted bench player contributes the factual multiplier exposed by
Official FPL.

`eo_pct` is emitted only when full pick coverage exists and multiplier
semantics are complete for the denominator. Otherwise ownership, starter,
captain, vice and collected-scope effective exposure remain separate.

## Football baseline

The P1.2 selected route is copied and fingerprinted before league evidence is
allowed to influence route preference.

The frozen football baseline contains:

- route ID and HOLD/change classification;
- players in/out;
- XI, bench goalkeeper, bench order;
- captain and vice;
- GW+1 / 3GW / 5GW football utilities;
- P1.7 robustness and regret;
- genuine P1.4 route distribution when executed;
- P1.2 and P1.4 evidence fingerprints.

P1.8 never edits these fields.

## Risk posture

Allowed posture is:

- `PROTECT`;
- `BALANCED`;
- `CHASE`.

Default is BALANCED.

An explicit current-decision preference may set posture. Automatic posture can
change only from current factual points plus remaining horizon, not from user
identity or historical profiling.

Late-horizon PROTECT requires a material lead. Late-horizon CHASE requires a
material points deficit. Rank by itself is insufficient.

## Close-decision gate

The versioned close gate checks the football gap separately at GW+1, 3GW and
5GW, plus expected-regret gap and paired P1.4 probability when available.

A route outside the close gate receives zero switching utility. Therefore a
low-owned weak football option or high-owned weak football option cannot be
promoted merely because of league exposure.

## Leverage utility

The downstream leverage utility is explicit and bounded. It uses:

- defensive coverage;
- captain coverage;
- differential exposure;
- genuine P1.4 upside/downside;
- same-world relative MC edge when available;
- risk posture;
- a football-quality/close-call gate.

The maximum overlay adjustment is bounded by configuration and is stored
separately from football utility:

- `football_baseline_utility`;
- `mini_league_overlay_utility`;
- `final_relative_decision_utility`.

## P1.4 integration

P1.8 has no independent simulation engine.

When selected rival submitted lineups are complete, P1.8 can construct exact
current-GW rival route definitions and call the existing
`run_correlated_monte_carlo()` P1.4 owner once with OUR routes and rival
routes in the same CRN football worlds.

This supports current-GW paired metrics such as expected relative points and
P(gain points on the selected leader/rival). It does not claim future final
rank probabilities.

Canonical P1.4 path requirements remain unchanged.

## Captain and vice

Captain exposure is separate from starter exposure. P1.8 exposes the exact
rival captain numerator/denominator and a relative captain coverage or
differential index.

Vice exposure is separate and is never silently added to captain EO.

Chip effects enter only when Official submitted-picks facts expose them.

## Decision Delta

Every output identifies:

- football baseline route;
- mini-league-adjusted route;
- whether a switch occurred;
- exact overlay state;
- exact reason.

States are:

- `BASELINE_PRESERVED`;
- `BASELINE_STRENGTHENED`;
- `CLOSE_CALL_SWITCH`;
- `RISK_POSTURE_SWITCH`;
- `NO_ACTIONABLE_LEAGUE_EDGE`.

PARTIAL or UNAVAILABLE league evidence cannot switch the baseline.

## Reversal triggers

Any switch carries explicit reversal triggers covering:

- a football gap leaving the close gate;
- new availability/injury evidence;
- denominator/coverage changes;
- rival captain exposure changes;
- price/affordability changes;
- disappearance of the P1.4 relative-tail edge;
- a football-baseline model fingerprint change.

## Evidence, freeze and settlement

P1.8 binds existing MODEL_EVIDENCE_BINDING with:

- input snapshot ID;
- mini-league snapshot ID;
- coverage state;
- denominator fingerprint;
- football baseline fingerprint;
- P1.4 output fingerprint where available;
- model/feature/parameter/calibration versions;
- run and output fingerprints.

The football baseline and adjusted overlay decision are frozen as two distinct
pre-deadline records.

Settlement preserves them separately and reports realized relative points,
overlay relative gain/loss and overlay regret. Realized variance does not
retroactively prove decision quality.

Calibration is diagnostic only. It may summarize switch frequency, football
utility sacrificed, realized relative gain/regret and posture-specific
performance. It cannot create a permanent one-GW leverage rule or auto-mutate
methodology weights.

## Consumer integration

`lineup_governance` accepts a P1.8 attachment only when:

- P1.2 is the native package owner;
- the P1.8 football baseline matches the P1.2 selected route;
- the adjusted route is one of the existing legal P1.2 routes;
- any actual switch has FULL league evidence.

The original P1.2 baseline remains published separately.

The DEEP `S15B` consumer is deliberately comprehensive rather than compact.
It must preserve denominator discipline visibly and publish, when supportable:

- rank battle around the user's current position;
- OUR15 exposure against all collected rivals as `count / denominator (%)` for
  ownership, starter, bench, captain and vice;
- EO as effective-multiplier sum / denominator (%) only when multiplier evidence
  is complete for the scope;
- the configured immediate rivals above the user, including points gap,
  current-OUR15 overlap, OUR-only players, rival-only players, captain and vice;
- OUR15 exposure against that direct-rival scope using the same raw-count
  denominator contract;
- material non-owned rival threats from the direct-rival scope;
- captain leverage candidates with football xPts/P(haul), all-rival exposure,
  direct-rival exposure and a bounded rank-utility interpretation;
- a visible `CHASE / BALANCED / DEFEND` implication for XI, captaincy and
  transfer behavior while preserving the football baseline first.

The rival-pick source is explicitly labelled by its disclosed gameweek. A
previous-GW submitted-picks snapshot is a behavioral/structural baseline only
and must never be presented as a prediction of still-private planning-GW picks.

The DEEP human-facing manifest requires these S15B structures, so a renderer
that collapses the section back to percentage-only summary cannot pass.

`report_enrichment` may still publish a compact machine-facing summary for
non-DEEP consumers, but it does not weaken the S15B visible DEEP contract.

No new scheduler or authority is introduced.

## S15B full league player ownership (16 Oct 2026)

The existing canonical `league_full_composition` computes exposure across all unique Official FPL element identities on the submitted 58-manager league scope; this is distinct from the OUR15 and the dynamic Competitive Window. In addition to the eight locked original tables, DEEP S15B renders a ninth `ALL LEAGUE PLAYER OWNERSHIP` table with Player, Pos, Owned, Ownership, Starter, Bench, Captain, Vice, EO. Players are ordered by descending owned count; positions are GK, DEF, MID and FWD for native filtering. Every population ratio uses 58 as the denominator, including our own team, and EO may exceed 100% due to multipliers. The submitted picks represent the prior-GW behavioural baseline, **not** future private selections. The canonical report's visible lock and QA enforce one row per unique player and the position mapping; no forecasting, optimizer, scheduler or Stage3 decision authority is added. Source audit at 2026-10-16 21:30 WIB found 58/58 squads and 158 unique identities; a private additive appendix exists without rewriting immutable occurrence receipts.


## Public factual S15B recovery (1 Nov 2026)

Documentation sync: 2026-11-01T23:19:00+07:00. Draft PR #1208 only; not merged, deployed or naturally accepted.

S15B factual acquisition is independent from owner-private OIDC and the V12 verified pointer.
The additive build_independent_s15b_snapshot V6 adapter reuses fetch_all_standings,
standings_artifact and acquire_manager_picks without modifying their
default data semantics. The strict S15B mode rejects duplicate/invalid
participant rows; an incomplete page or picks response is PARTIAL/UNAVAILABLE,
never 58/58 by assumption. Official FPL remains the only factual authority.

The standalone ad-hoc five-section public report is invoked by:

    python -m src.engines.v12_five_section_presentation --source auto --league-id 9477 --entry-id 3462711

It selects the latest disclosed GW using Official FPL event deadline UTC timestamps,
or rejects an explicit hidden GW. The public_only client bypasses environment
credential discovery, including rotating OIDC. It makes only public Official FPL
bootstrap/standings/submitted-picks GETs. A failed direct Official fetch can try
the allowlisted fpl-iphoenk.vercel.app/api read-only proxy. The dashboard proxy
alone is not independent source proof: its standings are marked PARTIAL
provenance and league-wide EO is suppressed until independent Official evidence
is available. Never confuse prior-GW submitted picks with future GW selections.

build_degraded_fallback(public_s15b_snapshot=...) may show a public-only
mini-league section inside the existing five-section ChatGPT view without
claiming V12 canonical status or changing any owner-private decision. Other
four sections remain NOT AVAILABLE when the canonical body is unverified.
The CLI is an executable ad-hoc consumer, not a new scheduled pipeline; the
ChatGPT scheduled task already has a separate Official-first S15B instruction.
CI/governance verification and natural scheduled delivery remain independent
acceptance requirements. No changes to P1.7, MC500K, Stage3, GW7,
private receipts, GitHub operational clock or ChatGPT schedule.
