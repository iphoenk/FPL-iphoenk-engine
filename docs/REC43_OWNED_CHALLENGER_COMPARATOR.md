# REC-43 Generic OWNED vs Challenger Comparator

Status: `CANDIDATE` / `ADVISORY_ONLY`

## Purpose
Continuously test whether a governed WATCHLIST candidate or an emerging performance challenger has become sufficiently superior to a structurally relevant OWNED player over a realistic multi-GW horizon to justify further transfer review.

## Architecture
This capability is intentionally implemented inside the existing `watchlist` bounded context. It is not a new microservice and does not own any football projection formula.

Canonical outputs reused:
- player xPts and uncertainty: `projections.json`
- xMins/start/DNP: projection-owned xMins distribution
- current tactical matchup: projection attachment from tactical-context artifacts
- team/fixture strength: prediction-owned fixture projection
- legal package / robust gain: `package_optimizer.json`
- owned sell value and ITB: `team.json`
- governed external candidate set: `dss_watchlist.json`
- price state: existing market/price services (no price formula in comparator)
- observed current-match process: `stats/playermatchstats_current.json`
- PL recent match history: `official_detail.json`

## Challenger lanes
1. `GOVERNED_WATCHLIST`: candidates already admitted by the authoritative DSS watchlist.
2. `EMERGING_CHALLENGER`: non-owned, non-watchlist players triggered by material recent-performance/process signals. A trigger does not equal BUY.

Emerging candidates must also pass minimum eligibility, position, price, xMins, start-probability, DNP, data-quality and 3-5 GW relevance screening.

## Comparison contract
Each pair exposes:
- 1/2/3/5 GW projected outcome from canonical per-GW xPts rows
- fixture-by-fixture H/A/opponent/xPts/uncertainty
- canonical xMins and start probability
- current-GW tactical matchup; future tactical rows remain `UNVERIFIED` unless the canonical tactical engine materializes them
- PL previous-match context when present
- cup/Europe/international load as `PENDING_REPORT_TIME` until verified
- role sustainability
- performance signal
- raw multi-GW gains
- affordability, club-limit legality and canonical package context
- confidence and signal-to-noise
- decision reasons, risks and reversal triggers
- external-model consensus placeholder for report-time `ALIGN` / `DIVERGE` / `REVIEW_DIVERGENCE` / `NEUTRAL`

## Transfer/chip context
The comparator reuses `team.projection_baseline` to detect a verified planning Wildcard or Free Hit.
- Wildcard: ordinary FT and hit costs are not applied.
- Free Hit: permanent-transfer actionability is capped for review.
- Normal transfer state: FT/hit cost is left pending unless authoritative transfer state is available; no cost is fabricated.

## Decision governance
Initial allowed outputs are advisory comparison states. The comparator cannot overwrite canonical:
- transfer recommendation
- Starting XI
- captain / vice captain
- watchlist membership
- chip decision

A strong one-match return is discovery evidence only. Missing critical evidence caps actionability rather than being guessed.

## Validation
Regression coverage includes the 25 required scenario classes from the generic specification plus dynamic acceptance with:
- at least one OWNED player
- at least one governed WATCHLIST challenger
- at least one emerging challenger when synthetic evidence supplies a valid trigger
- all 1/2/3/5 GW fields
- no named player-pair hardcoding
- report overlay preserving canonical decisions
- REC/Official-first/artifact/publication/ownership wiring.

## Production activation
Do not change REC-43 to `DONE_PROD` until:
1. branch code is merged to the canonical production line;
2. full V3 CI passes;
3. a fresh runtime publication includes `owned_challenger_comparator.json`;
4. report payloads expose `owned_vs_challenger`;
5. the production artifact is inspected and accepted.
