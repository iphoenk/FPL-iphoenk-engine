# V6 Deterministic Identity Bridge Roadmap

## Scope

This roadmap is V6-only. It governs cross-source player identity linkage for the fresh-data platform and does not grant prediction, optimizer, transfer, captaincy, chip, xPts, xMins, Monte Carlo, tactical, or decision authority.

Official FPL element ID remains the canonical player key. Provider links may be published only when a deterministic relationship can be verified from stable provider evidence. Fuzzy player-name matching is forbidden.

## Current implementation

The current V6 identity implementation contains deterministic bridge logic for:

- `official_price_predictor` via the shared Official FPL element namespace;
- `vaastav_fpl` via exact FPL element ID plus exact player code.

Other active providers remain explicitly `UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE` until a deterministic contract is implemented and tested. Source activation or successful acquisition must never be interpreted as proof that player-level identity linkage exists.

Runtime truth is published in `data/v6/evidence/player_identity_map.json`; this document is the engineering roadmap, not a substitute for runtime evidence.

## Acceptance contract for a new bridge

A provider bridge may be promoted only when all of the following are true:

1. The provider exposes a stable player identifier or an equivalent deterministic key.
2. The mapping is supported by verifiable evidence, not name similarity alone.
3. Ambiguous or conflicting rows fail closed and remain unresolved.
4. Mapping logic is isolated by provider and does not create a second canonical player registry.
5. Tests cover positive mapping, mismatch rejection, missing identifiers, and conflicting identifiers.
6. `player_identity_map.json` reports strategy, mapped count, unmapped count, and coverage ratio truthfully.
7. No bridge may overwrite Official FPL-native identity fields.

## Priority order

Prioritize providers where player-level joins materially unlock useful evidence and a deterministic identifier is realistically obtainable. Do not add provider-specific mapping code merely to raise a coverage percentage.

The preferred implementation sequence is:

- identify provider-native stable IDs and evidence route;
- add one isolated deterministic resolver;
- add regression tests;
- verify runtime coverage and unresolved cases;
- only then expose the bridge as verified in the published identity map.

## Non-goals

V6 will not use fuzzy name matching, probabilistic identity scoring, hidden manual aliases, or cross-provider majority voting to manufacture player links. Partial verified coverage is preferable to broad but uncertain matching.
