# P1.6 V12 Tactical / Role Canonical Scorer

Original P1.6 baseline: `36526c2b0fd4d6de7491ee8d9e3eeb0654778643`\n\nContextual suppressor/resilience refinement baseline: `d5d3f55bcfacd8164ae7d552ce45f5af84cea5c1`

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


## Contextual suppressor/resilience refinement

This bounded refinement extends the already-GREEN P1.6 owner. It does not
create P1.7 and does not change the global 20/25/30/25 weights.

The Canonical principle is:

> Fixture difficulty is a suppressor, not an overriding veto. Strong, secure,
> multi-channel attacking roles must retain measurable upside against difficult
> opponents, particularly when supported by favorable home and tactical context.

This principle does not make home automatically positive, does not make
multi-channel players automatically superior, and does not remove opponent
strength.

### Canonical player-fixture feature contract

Every contextual player-fixture evaluation exposes:

- `home_attack_context`
- `attacking_involvement_score`
- `role_security_score`
- `scoring_channel_vector`
- `scoring_channel_diversity`
- `tactical_role_fit`
- `fixture_suppression_raw`
- `role_resilience`
- `fixture_suppression_effective`
- `canonical_tactical_role_score`

All contextual fields are deterministic and bounded where numeric. The model,
feature and parameter versions are published with the output.

### Home context and double-count prevention

Home context is not a flat home bonus.

For a home fixture it uses only venue-specific deltas:

1. own home attack relative to own neutral home/away attack;
2. opponent away defence relative to opponent neutral home/away defence;
3. league home goal environment relative to neutral home/away baseline.

Each positive ratio is mapped to `ratio / (1 + ratio)` and available signals
are averaged. Away receives a neutral contextual value of 0.5.

Generic opponent strength is explicitly excluded from this feature. It is
handled separately by fixture suppression and remains part of the wider
FIXTURE/SECURITY component. P1.3's existing home-aware expected-goal
adjustment is not changed.

The contextual output publishes `application_count=1`.

### Attacking involvement

Attacking involvement is interaction/resilience evidence only. It does not add
a second expected-points contribution.

Available metrics use bounded `x/(x+reference)` normalization:

- P1.3 posterior xG rate vs governed goal-rate prior;
- P1.3 posterior xA rate vs governed assist-rate prior;
- position-aware shots/90 threshold;
- position-aware box-touch threshold;
- position-aware chances-created threshold.

The observed mean is shrunk toward 0.5 using:

`evidence_minutes / (evidence_minutes + P1.3 rate_shrinkage_minutes)`.

xGI is not added again when xG and xA are already present.

### Role security

Role security consumes, but does not own, P1.1:

- P(start);
- xMins / 90;
- starter minutes if starting / 90;
- current starts / team matches where available.

The result is the arithmetic mean of available bounded signals. Missing
competition/minute-interference evidence remains explicit.

### Scoring-channel vector and diversity

The vector contains:

- GOAL
- ASSIST
- SET_PIECE
- PENALTY
- DEFENSIVE_CONTRIBUTION
- CLEAN_SHEET
- BONUS

Channel values represent evidence strength, not binary presence.

Partially dependent channels are grouped before diversity is calculated:

- ATTACK_OPEN_PLAY = GOAL + ASSIST
- DEAD_BALL = SET_PIECE + PENALTY
- DEFENSIVE = DEFENSIVE_CONTRIBUTION + CLEAN_SHEET
- BONUS = BONUS

Group strength is the strongest available channel in that group. Diversity is
normalized Shannon entropy across positive group strengths, multiplied by the
strongest group and evidence completeness. This prevents a linear "more
channels = automatic bonus" rule.

### Tactical fit

Tactical fit uses the existing governed role-route versus opponent-context
evidence. The numeric input is the observed role-matched edge/risk balance,
shrunk toward 0.5 by evidence confidence.

Narrative tactical text is not numeric authority. A tactical row bound to a
different opponent is rejected as unavailable.

### Raw fixture suppression

Raw fixture suppression uses venue-neutral opponent strength so the home
context is not counted again.

For an opponent index above neutral:

`difficulty = max(0, 1 - 1/index)`.

Opponent defensive difficulty is weighted by the player's attacking-channel
exposure. Opponent attacking difficulty is weighted by defensive-channel
exposure.

The result is bounded [0,1]. An easy opponent creates zero suppression, not an
automatic tactical bonus.

### Role resilience and effective suppression

Available resilience inputs are:

- home attack context;
- attacking involvement;
- role security;
- scoring-channel diversity;
- tactical fit.

Missing optional evidence is omitted from the available mean, while evidence
completeness shrinks the result toward 0.5:

`role_resilience = 0.5 + completeness * (mean_available - 0.5)`.

Then:

`resilience_adjustment = 1 / (1 + role_resilience)`

`fixture_suppression_effective = fixture_suppression_raw * resilience_adjustment`

Because role resilience is bounded [0,1], effective positive suppression
remains positive and can never exceed the raw suppression. Under this initial
structural parameterization, resilience can relieve at most half the raw
suppression. It cannot turn a difficult opponent into a bonus.

The pre-suppression player-role quality is:

`sqrt(evidence_role_score_0_1 * role_resilience)`

and the contextual component is:

`canonical_tactical_role_score = 100 * pre_suppression_role_quality * (1 - fixture_suppression_effective)`.

### Player quality versus action cost

The contextual scorer accepts no transfer-action inputs.

It does not consume hit points, free-transfer state, FT shadow value, bank,
price, affordability, package constraints or exit costs. Those remain
downstream of player quality in Canonical V12.

### Calibration binding

Parameter set:

`P1_6_CONTEXTUAL_BOUNDED_STRUCTURAL_V1`

Parameter version:

`p1.6-contextual-role-v2`

Calibration authority:

`P1.5_CALIBRATION_DECISION_LEDGER`

Calibration provenance:

`control/fpl_master_v12/FPL_MASTER_STATE_V12.json#model_evidence.records`

At introduction, the settled P1.5 sample count is zero. Therefore calibration
confidence is LOW and no outcome-fitted coefficients are introduced.

Any later parameter change requires settled pre-deadline evidence. Named-player
or one-match tuning is forbidden.

## Bounded validation and historical-evidence status

The deterministic validation matrix covers all of these generic scenarios:

- difficult fixture + strong role;
- difficult fixture + weak role;
- easy fixture + strong role;
- easy fixture + weak role;
- home + strong role;
- away + strong role;
- multi-channel role;
- single-channel role.

It tests structural monotonicity and invariants only. It does not use a named
player, club pairing or the result of the current match.

The hypotheses under test are:

- H1: difficult fixtures may be over-suppressing strong roles;
- H2: easy fixtures may be over-valuing weak roles;
- H3: meaningful multi-channel roles may be under-valued;
- H4: home contextual interaction may be under-valued or double-counted;
- H5: fixture difficulty may be too dominant relative to role evidence.

The current P1.5 model-evidence ledger contains no settled pre-deadline records.
Therefore historical support for H1-H5 is currently **UNPROVEN**, not accepted
or rejected from outcome data. The structural counterfactual matrix is a
regression guard, not a substitute for historical calibration.

This is intentional anti-hindsight behavior. A single match result cannot
validate or tune the method.
