# V3 Understat Tactical Intelligence

Implementation contract: `UNDERSTAT_TACTICAL_INTELLIGENCE_V1`.

## Architecture

- Understat extends the existing V3 `tactical_context` capability; it does not create a second tactical business authority or a new execution domain.
- Official FPL remains authoritative for FPL identity, club/position eligibility, price/ownership, fixtures/deadlines, submitted squad/XI/bench/captain/vice/chip and live scoring facts.
- Full-universe mapping is derived from the already-owned `official_snapshot.bootstrap` rather than adding a dependency on `market_state`/`universe.json`.
- Understat is optional football/tactical enrichment and fails soft on source unavailability.
- Source-layer health uses an artifact-only probe. Network acquisition remains owned by the tactical-context capability.
- Understat runs inside the existing bounded tactical-context process after canonical tactical artifacts are materialized; it does not add a second runtime process/batch owner.

## Prediction and decision safety

- No direct Understat or PPDA coefficient is added to xPts.
- No Understat mutation of xMins/start probability.
- Understat enriches canonical tactical routes/team context consumed by the existing close-call governance primitive; it does not create a new lineup/watchlist/report decision path.
- Tactical evidence may only resolve choices already inside the existing configured close-call windows; legality and base scores remain canonical V3 outputs.
- Missing evidence is neutral, not zero/negative.
- Captaincy scoring, eligibility, DNP guards and authority are unchanged. Any tactical C/VC tie-break remains the pre-existing V3 close-call behavior; Understat does not introduce a separate captaincy formula or authority.
- Transfer/challenger tactical evidence remains advisory and has zero independent authority to authorize a transfer or hit.

## Performance

- No per-player network requests.
- One governed league snapshot is cached and reused.
- The `fast_decision` profile performs cache-only Understat consumption; network refresh is explicitly deferred to protect the unchanged 3-second FAST SLO.
- Candidate CI proof on 2026-09-02: FULL runtime 14.04s against 45s target; three fresh-process FAST consistency runs 2.664s / 2.582s / 2.580s, all below the 3s hard ceiling; unified interactive serving median 25.6ms and max 167.2ms against the 1s hard ceiling.

## QA/QC proof

- 681 unit/regression tests passed in V3 CI #855.
- Architecture contract, no-duplicate ownership, capability telemetry, FAST-lane contract, operational LKG hydration, composite FULL+FAST release acceptance, material equivalence and candidate Definition-of-Done all passed.
- Framework acceptance remained GREEN with Gate0 16/16, DSS core 50/50, DSS extensions 16/16 and enhancements 8/8.
- Production publication/source-commit proof is intentionally deferred until after merge and a real V3 Runtime publication.

## Truthful limitations

- Player match-by-match Understat rolling windows are not fabricated when the governed source snapshot only supplies player season aggregates. They remain `INSUFFICIENT_EVIDENCE`.
- Opponent/game-state/red-card adjustments remain `INSUFFICIENT_EVIDENCE` when source evidence is insufficient.
- PPDA is contextual evidence only and can never independently create a positive xPts adjustment.
