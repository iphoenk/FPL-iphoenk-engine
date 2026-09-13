# V6 Wave A — Core Structured Data Expansion

## Scope

Wave A is V6-only and data-only. It must not ingest or publish model, optimizer, tactical, editorial, transfer, captain or chip decisions as V6 authority.

## Implemented in this change

1. Non-data sources are removed from the active scheduled V6 set and retained only as reference metadata for FPL Master Wave B/C usage.
2. A fail-closed structured-source candidate catalog is added for the user-supplied source universe.
3. Candidate promotion requires public/no-auth access, stable retrieval, factual field allowlists, deterministic identity, provenance/freshness/health and no fuzzy/name production joins.
4. Mixed sources remain reference-only until a field-level extractor proves that model/editorial fields cannot leak into V6.
5. CI guards verify that active V6 source categories remain data-only and that unvalidated candidates are not silently activated.

## Runtime effect

Active scheduled sources are reduced from 22 to 14 by moving model/editorial/market-reference sources out of V6 runtime acquisition. Official FPL and Official FPL-derived market telemetry remain required platform sources under the existing authority contract. Existing structured providers such as Understat, Opta/The Analyst, StatMuse and FotMob remain active.

## Structured candidate states

- Existing structured: Opta/The Analyst, StatMuse, FotMob.
- Pilot candidates: Trendline factual stats, 11v11 factual match/player history, Squawka stats.
- Pilot pending endpoint validation: Soccerbase.
- Reference-only pending machine contract: xGStat.
- Mixed/reference-only pending field extractor: FPLToolkit factual subset, Futmetrix factual subset, FPLAnaly factual subset, FPLAnalyticsDashboard factual subset.
- Existing disabled pending compliant access: SofaScore, FBref.
- Exact-domain/product validation required: PlayerStats, Statz, DataFC, xGLab, CardStats.

## Promotion gate

A candidate may move into scheduled V6 acquisition only when all applicable checks pass:

- public/no-auth/no-private-secret access;
- stable and bounded retrieval contract;
- factual field allowlist;
- deterministic provider-native identity path to canonical Official FPL identity for player-level data;
- no fuzzy or name-only production join;
- provenance, freshness, coverage and health publication;
- source failure isolation;
- no model/prediction/editorial/optimizer semantics in the active artifact;
- regression tests and generated source contract remain green.

## Boundary

Model-native projections, expected minutes, P(start), rankings, optimizers and market predictions belong to FPL Master Wave B. Tactical/editorial/news interpretation belongs to FPL Master Wave C. V6 only supplies verified factual inputs and provenance.
