# V3 Understat Tactical Intelligence

Implementation contract: `UNDERSTAT_TACTICAL_INTELLIGENCE_V1`.

## Architecture

- Understat extends the existing V3 `tactical_context` capability; it does not create a second tactical business authority or a new execution domain.
- Official FPL remains authoritative for FPL identity, club/position eligibility, price/ownership, fixtures/deadlines, submitted squad/XI/bench/captain/vice/chip and live scoring facts.
- Understat is optional football/tactical enrichment and fails soft on source unavailability.
- Source-layer health uses an artifact-only probe. Network acquisition remains owned by the tactical-context capability.

## Prediction and decision safety

- No direct Understat or PPDA coefficient is added to xPts.
- No Understat mutation of xMins/start probability.
- Understat may only break already-close legal XI/formation, bench and watchlist choices.
- Missing evidence is neutral, not zero/negative.
- Captaincy semantics are unchanged by Understat. XI alternatives that would force an Understat-only captain/vice change are not selected by the Understat close-call overlay.
- Transfer-package tactical evidence is advisory only and has zero authority to authorize a transfer or hit.

## Performance

- No per-player network requests.
- One governed league snapshot is cached and reused.
- The `fast_decision` profile performs cache-only Understat consumption; network refresh is explicitly deferred to protect the unchanged 3-second FAST SLO.

## Truthful limitations

- Player match-by-match Understat rolling windows are not fabricated when the governed source snapshot only supplies player season aggregates. They remain `INSUFFICIENT_EVIDENCE`.
- Opponent/game-state/red-card adjustments remain `INSUFFICIENT_EVIDENCE` when source evidence is insufficient.
- PPDA is contextual evidence only and can never independently create a positive xPts adjustment.
