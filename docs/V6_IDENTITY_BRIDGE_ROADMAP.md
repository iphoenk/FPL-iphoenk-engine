# V6 Deterministic Identity Bridge Roadmap

## Scope

This roadmap is V6-only. It governs cross-source player identity linkage for the fresh-data platform and does not grant prediction, optimizer, transfer, captaincy, chip, xPts, xMins, Monte Carlo, tactical, or decision authority.

Official FPL element ID remains the canonical player key. Provider links may be published only when a deterministic relationship can be verified from stable provider evidence. Fuzzy player-name matching is forbidden.

## Current implementation

The V6 identity implementation contains deterministic bridge logic for:

- `official_price_predictor` via the shared Official FPL element namespace;
- `vaastav_fpl` via exact FPL element ID plus exact player code;
- `opta_the_analyst` via `Official FPL bootstrap.elements.code`, which is the shared Opta legacy numeric namespace / The Analyst `sc-` namespace. Duplicate or missing canonical codes fail closed;
- verified provider player crosswalk rows anchored on the Official FPL `code`, with one-to-one source-native IDs, explicit evidence and no name fallback;
- verified FotMob team crosswalks, which remain separate from player identity.

A successful source acquisition is never proof of player identity. A provider is joinable only for the individual player rows whose link status is `EXACT` or `VERIFIED_MANUAL` in `data/v6/evidence/player_identity_map.json`.

For providers such as FotMob, StatMuse and Understat, the preferred external evidence route is a stamped provider-ID bridge register keyed from the same Opta numeric anchor, for example Reep release bridges. Imported rows must be reduced to a small reviewed crosswalk and stored with release/evidence provenance before runtime joins are enabled. Runtime must not download a large identity register merely to guess names.

FFScout currently has no accepted stable player-native namespace in V6. It therefore remains fail-closed and unjoinable at player level until a deterministic provider ID contract is evidenced. This is intentional, not an identity-health bug.

Runtime truth is published in `data/v6/evidence/player_identity_map.json`; this document is the engineering roadmap, not a substitute for runtime evidence.

## Acceptance contract for a new bridge

A provider bridge may be promoted only when all of the following are true:

1. The provider exposes a stable player identifier or an equivalent deterministic key.
2. The mapping is supported by verifiable evidence, not name similarity alone.
3. The bridge is anchored to the current Official FPL player through an exact key, preferably `bootstrap.elements.code` when the external register uses the Opta numeric namespace.
4. Source-native IDs and canonical anchors are one-to-one within the promoted mapping set.
5. Ambiguous, duplicate or conflicting rows fail closed and remain unresolved.
6. Mapping logic is isolated by provider and does not create a second canonical player registry.
7. Tests cover positive mapping, mismatch rejection, missing identifiers, duplicate identifiers and conflicting identifiers.
8. `player_identity_map.json` reports strategy, mapped count, unmapped count and coverage ratio truthfully.
9. No bridge may overwrite Official FPL-native identity fields.
10. Partial verified coverage is allowed; unverified remainder stays `UNMAPPED`.

## Cross-source analytics gate

Cross-source player analytics may consume an external record only when all of these conditions hold:

- the source record has a stable `source_native_id`;
- the identity map contains an `EXACT` or `VERIFIED_MANUAL` link from that native ID to one Official FPL element;
- the link provenance states the bridge method and evidence;
- no conflict or duplicate guard is active for that key;
- the source dataset itself is current enough for the intended analysis.

`join_allowed=true` is therefore an identity permission, not a statement that the source has a complete normalized player dataset or that its football evidence is fresh.

## Priority order

Prioritize providers where player-level joins materially unlock useful evidence and a deterministic identifier is realistically obtainable. Do not add provider-specific mapping code merely to raise a coverage percentage.

The preferred implementation sequence is:

- identify provider-native stable IDs and evidence route;
- prove the canonical anchor without names;
- add one isolated deterministic resolver or reviewed crosswalk;
- add regression tests;
- verify runtime coverage and unresolved cases;
- only then expose the bridge as verified in the published identity map.

## Non-goals

V6 will not use fuzzy name matching, probabilistic identity scoring, hidden manual aliases, date-of-birth/name heuristics, or cross-provider majority voting to manufacture player links. Partial verified coverage is preferable to broad but uncertain matching.
