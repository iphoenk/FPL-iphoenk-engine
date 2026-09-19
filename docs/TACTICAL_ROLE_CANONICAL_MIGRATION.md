# P1.6 V12 Tactical / Role Canonical Scorer

Baseline: `36526c2b0fd4d6de7491ee8d9e3eeb0654778643`

This file is migration and test evidence. It is not methodology authority.
`control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt` remains the authority.

## Donor inventory

Audited donors are `src/models/tactical_matchup.py`,
`src/models/tactical_role_context.py`,
`src/engines/tactical_decision_consumption.py`,
`src/models/observed_tactical_context.py`,
`src/models/official_role_evidence.py`, and the governed Understat tactical
enrichment. The old close-call overlay remains a migration/regression oracle
and is not copied wholesale into the Canonical 25% scorer.

The legacy tactical role classifier derives several labels from current xG,
xA, shots, box touches and chance creation. Those signals remain useful as
provenance, but their primary canonical owner is CURRENT UNDERLYING and they
receive zero tactical contribution.

## Exact evidence inventory

| Feature | Current evidence | P1.6 treatment |
| --- | --- | --- |
| Actual positional deployment | UNAVAILABLE at canonical player projection level | Explicit UNAVAILABLE |
| Nominal FPL position vs actual football role | INFERRED by legacy current-rate profile | CURRENT_UNDERLYING_EXCLUDED |
| Central / wide / half-space deployment | UNAVAILABLE player-level canonical evidence | Explicit UNAVAILABLE |
| Attacking freedom | UNAVAILABLE distinct evidence | Explicit UNAVAILABLE |
| Defensive burden | UNAVAILABLE distinct evidence | Explicit UNAVAILABLE |
| Box occupation | INFERRED donor from box touches/shots | CURRENT_UNDERLYING_EXCLUDED |
| Progression route | INFERRED donor from attacking event routes | Excluded until distinct deployment evidence exists |
| Overlap / underlap | UNAVAILABLE | Explicit UNAVAILABLE |
| Set-piece hierarchy | OBSERVED Official FPL role ranks when present | TACTICAL_DISTINCT |
| Penalty hierarchy | OBSERVED Official FPL penalty rank when present | TACTICAL_DISTINCT |
| Substitution pattern | Upstream event rows exist, but no governed canonical projection feature | Explicit UNAVAILABLE until bound |
| Starter-role stability | P1.1 already consumes starting/minutes evidence | P1_1_SHARED_EXCLUDED unless distinct coach-usage evidence is supplied |
| Coach selection consistency | UNAVAILABLE distinct canonical feature | Explicit UNAVAILABLE |
| System / formation fit | FPL-position shape is only a proxy, not true formation | No fit invented |
| Pressing compatibility | UNAVAILABLE player-level | Explicit UNAVAILABLE |
| Transition attacking role | UNAVAILABLE player-level | Explicit UNAVAILABLE |
| Transition defensive burden | UNAVAILABLE player-level | Explicit UNAVAILABLE |
| Opponent wide vulnerability | Route-level evidence may exist | Context-only until player wide role is evidenced |
| Opponent half-space vulnerability | UNAVAILABLE directly | Explicit UNAVAILABLE |
| Opponent central-channel vulnerability | Generic box/chance concession is insufficient | Explicit UNAVAILABLE unless channel-specific |
| Opponent transition weakness | Route-level proxy may exist | Context-only until player transition role is evidenced |
| Opponent set-piece weakness | Route-level evidence may exist | Scoreable only with player set-piece role |
| Opponent pressing behavior | PPDA/style proxy may exist | Context-only until player pressing compatibility is evidenced |
| Opponent defensive line | Optional donor field, not reliably present | No benefit without compatible role |
| Rest/congestion interaction | No distinct canonical role evidence in current projection | Explicit UNAVAILABLE |

OBSERVED outranks INFERRED. UNAVAILABLE never becomes neutral factual evidence.
Missing evidence shrinks the normalized component toward the prior center,
reduces confidence, and raises uncertainty.

## Evidence-state contract

Every feature publishes feature_name, evidence_state, source, observed_at,
confidence, direct_or_inferred, materiality, double_count_classification and
supporting_evidence_reference. OBSERVED requires DIRECT evidence. INFERRED
requires an explicit inference label. UNAVAILABLE requires zero
confidence/materiality, no source/reference, and UNKNOWN value/direction.

Equal-authority conflicts are deterministic: the feature becomes MIXED,
confidence is reduced, and the feature is excluded from scoring.

## Anti-double-count matrix

CURRENT UNDERLYING owns current xG, xA, shots, chance creation and current
attacking rates. FIXTURE/SECURITY owns generic opponent/team difficulty.
PROVEN/HISTORICAL owns historical player ability. P1.1 owns starting/minutes
probabilities. P1.3 owns goal, assist, clean-sheet, DefCon and save event
distributions.

P1.6 scores only distinct role/deployment/hierarchy/system evidence and
role-matched opponent-channel interactions. Any overlapping donor signal is
retained only as diagnostics with zero tactical contribution.

## Normalization

All 25 catalog features have a uniform basis weight for P1.6. No feature
weight is learned or auto-retuned in this stage. OBSERVED has authority factor
1.0 and INFERRED 0.65.

`tactical_role_score = 50 + 50 * directional_signal * scoreable_feature_coverage`

The score is bounded to 0..100. Missing evidence cannot become a negative
factual score; it moves the score toward the 50 prior center. Confidence is
based on scoreable coverage, evidence authority/quality and conflict. Published
uncertainty rises when confidence falls.

## Canonical composition

The owner publishes `canonical_component.weight = 0.25`. The existing
canonical composer remains:

`0.20 PROVEN/HISTORICAL + 0.25 TACTICAL/ROLE + 0.30 CURRENT UNDERLYING + 0.25 FIXTURE/SECURITY`.

Confidence does not reallocate the 25%.

## Migration comparison

Official set-piece and penalty ranks are EXACT_EQUIVALENT_EVIDENCE. Moving the
old advisory context into a normalized component is
INTENTIONAL_CANONICAL_MAPPING. Excluding current attacking-rate tactical labels
is ANTI_DOUBLE_COUNT_IMPROVEMENT. Explicit missingness is
EVIDENCE_DISCIPLINE_IMPROVEMENT.

An unexpected regression is any P1.1/P1.3 numeric mutation, canonical weight
drift, fabricated unavailable evidence, or new V6/future-stage dependency.
Those conditions are hard-tested and block ownership.

## Consumer boundary

`src/engines/prediction_service.py` is the production prediction consumer
switched in P1.6. It attaches the native component after Official role evidence
and tactical-matchup evidence are available, then verifies the decision-bearing
xPts signature is unchanged.

`src/engines/canonical_decision_methodology.py` already owns exact
20/25/30/25 composition and accepts a numeric TACTICAL_ROLE component, so it is
not rewritten.

Legacy tactical matchup and close-call consumption remain migration/regression
oracles. Package optimization, Monte Carlo and mini-league overlay are outside
this stage and are not started.
