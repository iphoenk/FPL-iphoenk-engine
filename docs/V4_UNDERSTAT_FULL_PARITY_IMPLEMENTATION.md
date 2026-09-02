# V4 Understat Full-Parity Tactical Intelligence

This change implements Understat as optional governed tactical enrichment inside the existing V4 native architecture.

## Ownership

- acquisition/cache/schema/freshness: `enrichment`
- normalized Understat contract: `src.intelligence.understat_tactical`
- xPts/xMins: unchanged, still owned by `prediction`
- tactical matchup / watchlist / XI / bench / formation close-calls: `optimization`
- final decision authority: unchanged, `decision_arbitration`
- reporting: composition only

No ninth runtime service is introduced.

## Safety

- Official FPL remains factual authority.
- Missing Understat evidence is UNKNOWN / INSUFFICIENT_EVIDENCE, never zero.
- PPDA never maps directly to xPts.
- Understat cannot mutate canonical xPts or xMins.
- Tactical evidence can only participate through governed close-call/context paths.
- Captaincy, chip, hit, transfer execution and optimizer search-width semantics are unchanged.
- Source failure is fail-soft because Understat is optional enrichment.

## Source/runtime

The adapter performs a bounded league-level fetch and parses the embedded JSON without JavaScript execution. It uses a cached last-known-good snapshot, bounded retries/backoff, explicit freshness, source provenance, schema validation and no per-player network loop.

## Evidence contract

`data/understat_tactical_v4.json` exposes:

- source health/freshness/provenance
- team rolling windows: last 1 / 3 / 5 / season-to-date / home / away
- explicit small-sample confidence and shrinkage
- SOURCE_OBSERVED versus DERIVED metric declarations
- player season evidence: xG/xA/xGChain/xGBuildup/shots/key passes/minutes and derived per-90/share evidence
- mapping confidence and unresolved mappings
- next-fixture tactical matchup with supporting/conflicting signals and explicit insufficient-evidence states
- full Official FPL universe mapping attempt

The governed league snapshot does not expose a reliable player per-match series, so player last-1/3/5 is truthfully marked `INSUFFICIENT_EVIDENCE` rather than fabricated.

## V3/V4 parity

The target is intelligence parity, not decision parity. V4 preserves native contracts and exposes the same conceptual Understat evidence contract required by the parity program. A cross-engine executable parity proof can only be finalized after the V3 Understat implementation branch publishes its corresponding normalized contract; V4 must not modify V3 from this branch.
