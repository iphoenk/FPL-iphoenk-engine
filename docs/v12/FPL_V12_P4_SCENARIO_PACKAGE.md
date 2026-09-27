# FPL V12 P4 Scenario Package

> Status: PREPARATION / NOT PRODUCTION MERGED  
> Change timestamp: 2026-09-27T17:58:00+07:00  
> Production base at preparation: `051d5b2fd6732f18784a78d934a4cd3ca65ac25b`

P4 is a private counterfactual package over the existing Canonical V12 engine. It is not a second scorer, optimizer, minutes model, captain model, or scheduler.

## Canonical counterfactual path

A scenario override is introduced only at P1.1 availability:

`explicit private scenario -> P1.1 availability/minutes -> existing P1.3 posterior -> existing P1.2A/P1.2B -> existing P1.7 -> existing P1.4 -> existing P1.8 -> existing S19 reconciliation`.

Post-hoc edits to xPts, XI, captain, route, or final action are forbidden.

Normal production P1.1 remains Official-FPL authoritative. Scenario availability requires explicit internal authorization and fails closed if a caller tries to inject an override outside the governed scenario path.

## Required package

For every current private base:

- CURRENT ACTUAL BASE;
- exactly 15 OUR15 unavailable scenarios;
- material captain-doubt scenarios when requested;
- material vice-captain-doubt scenarios when requested.

Every scenario carries:

- scenario_id;
- base_fingerprint;
- override_type and private override input;
- S06;
- S08;
- S09;
- S14;
- S19;
- delta versus base;
- deterministic output_fingerprint;
- route_survival;
- reversal_probability;
- expected_regret;
- stability_state.

Until Decision Surface Stability is implemented, the four Stability fields are exactly `NOT_YET_EVALUATED`. No metric is fabricated.

## Invalidation

A package is current only when:

`current_base_fingerprint == package.current_base_fingerprint`.

A changed base invalidates all dependent scenarios and requires rebuild.

## Privacy and cache boundary

Scenario inputs and outputs are PRIVATE_DECISION / PRIVATE_PERSONAL where applicable. They must never be persisted as plaintext public artifacts, issue comments, public runtime data, logs, or public Actions cache keys.

The public-safe Stage-2 cache must not be silently reused for a private scenario override unless a later dependency-matrix implementation proves a safe selective-reuse contract. Until then, scenario evaluation must use a scenario-aware ephemeral path.

## Acceptance still required

This preparation is not P4 GREEN until production integration proves:

1. current base and 15/15 unavailable scenarios complete;
2. all scenarios bind to the same current base;
3. canonical engine ownership unchanged;
4. deterministic repeated package;
5. private-only publication;
6. base-change invalidation and rebuild;
7. `/scenario player` resolves from the current package without running a full DEEP computation.
