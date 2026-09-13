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
- FFScout public Team News player references via exact Premier League media code to Official FPL `code`. This is public `PLAYER + FEED` scope only; Members Area data is not acquired;
- verified FotMob team crosswalks, which remain separate from player identity.

A successful source acquisition is never proof of player identity. A provider is joinable only for the individual player rows whose link status is `EXACT` or `VERIFIED_MANUAL` in `data/v6/evidence/player_identity_map.json`.

Runtime identity truth is published in `data/v6/evidence/player_identity_map.json`. Wave A additionally publishes `data/v6/evidence/player_identity_coverage.json` so canonical coverage and current observed join coverage are never conflated.

## Wave A coverage semantics

Two different coverage questions must be reported separately:

1. **Canonical coverage**: verified provider identities divided by all current Official FPL players.
2. **Observed join coverage**: verified joins divided by the unique provider-native player records actually observed by the current V6 acquisition surface.

Observed join coverage is not automatically complete provider-universe coverage. For example, a leader table, a limited query result, a public Team News page, or a current-season stats endpoint can observe only a subset of all entities the provider knows about.

An unobserved Official FPL player must therefore not be classified as `NO_PROVIDER_ENTITY` unless V6 has complete provider-universe evidence. Until then, absence is `NOT_PROVEN`. A player that is actually observed from a provider but has no deterministic crosswalk is a factual `PROVIDER_ENTITY_EXISTS_BUT_UNMAPPED` gap and remains fail-closed.

The current completeness labels are deliberately explicit:

- Opta/The Analyst: `CANONICAL_SHARED_NAMESPACE_COMPLETE`;
- Understat: `CURRENT_SEASON_STATS_OBSERVATION`;
- FotMob: `PARTIAL_LEAGUE_STATS_OBSERVATION`;
- StatMuse: `PARTIAL_QUERY_RESULT`;
- FFScout public: `PARTIAL_PUBLIC_PAGE_REFERENCE_OBSERVATION`.

A provider may therefore have partial canonical coverage while its observed join coverage is 100%. That is acceptable only when every currently observed provider-native player row is deterministically joined with zero identity conflicts. It is not permission to claim that the provider universe itself is complete.

## Wave A hardening continuation

Wave A does not stop at publishing percentages. The coverage artifact is an integrity control and must reconcile what the identity map declares with the links that actually exist.

The hardening rules are:

- every declared `mapped_player_count` is reconciled to the actual number of `EXACT` or `VERIFIED_MANUAL` links in the identity map;
- a joinable link without a provider-native ID is a hard integrity failure;
- one provider-native ID mapping to more than one Official FPL player is a hard identity conflict;
- more than one provider-native ID resolving to the same Official FPL player in one observed provider surface is also treated as a one-to-one identity collision and fails closed;
- configured crosswalk conflicts and duplicate Official FPL canonical codes remain hard failures;
- observed unmapped rows remain non-fabricated gaps and do not by themselves block publication;
- canonical coverage below 657/657 is not automatically a system failure when the provider does not expose enough deterministic evidence. The system must keep retrying or enriching exact evidence where available, but it must not manufacture the remainder;
- FFScout public identity is now included in the same coverage-truth model as Opta, Understat, FotMob and StatMuse;
- a normal acquisition must publish a valid coverage artifact before publication. A report-prefetch may temporarily preserve one legacy pre-Wave-A runtime snapshot so report delivery is not broken during migration; after the next normal acquisition, the artifact is validated on every publish.

The practical target remains maximum deterministic canonical coverage, up to 657/657 where provider evidence supports it. Partial provider coverage is transparent and non-blocking only when there are zero hard identity conflicts or corrupt bridges.

## Reep v1 evidence posture

Wave A pins Reep v1 release `20260907T201034Z` as current build-time evidence metadata in `config/v6/identity_evidence_sources.json`. Runtime acquisition does not depend on Reep network availability.

The pinned release proves an important provider-role distinction:

- Understat is present in the canonical `bridges.csv.gz` player namespace;
- Opta numeric and StatMuse PL identifiers are present in `overlay_xids.csv.gz`, whose own schema explicitly describes those rows as relayed discovery identifiers and **never a bridge or corroboration evidence**;
- FotMob was not observed in the current v1 provider surfaces used by Wave A.

Reep v1 IDs are not interchangeable with the frozen Reep v0 IDs. V6 therefore does not silently replace the existing verified v0 crosswalk with v1 overlay data. The pinned Reep v0 exact-code crosswalk remains active for Understat, FotMob and StatMuse until Wave B can prove a stronger deterministic replacement. Reep v1 overlay rows may be used to investigate gaps, but they cannot create runtime `EXACT` or `VERIFIED_MANUAL` links by themselves.

## Acceptance contract for a new bridge

A provider bridge may be promoted only when all of the following are true:

1. The provider exposes a stable player identifier or an equivalent deterministic key.
2. The mapping is supported by verifiable evidence, not name similarity alone.
3. The bridge is anchored to the current Official FPL player through an exact key, preferably `bootstrap.elements.code` when the external register uses the Opta numeric namespace.
4. Source-native IDs and canonical anchors are one-to-one within the promoted mapping set.
5. Ambiguous, duplicate or conflicting rows fail closed and remain unresolved.
6. Mapping logic is isolated by provider and does not create a second canonical player registry.
7. Tests cover positive mapping, mismatch rejection, missing identifiers, duplicate identifiers and conflicting identifiers.
8. Runtime evidence reports mapped, observed, unresolved, conflict and both coverage ratios truthfully.
9. No bridge may overwrite Official FPL-native identity fields.
10. Partial verified coverage is allowed; unverified remainder stays `UNMAPPED`.

## Cross-source data join gate

A downstream consumer may join an external player record only when all of these conditions hold:

- the source record has a stable `source_native_id`;
- the identity map contains an `EXACT` or `VERIFIED_MANUAL` link from that native ID to one Official FPL element;
- the link provenance states the bridge method and evidence;
- no conflict or duplicate identity guard is active for that key;
- the source dataset itself is current enough for the consumer's intended use.

`join_allowed=true` is an identity permission only. It is not a statement that the source has a complete normalized player dataset, and it gives V6 no prediction or decision authority.

## Wave B hand-off

Wave B consumes the Wave A gap report. Its target is zero observed unresolved identities, not an artificial `657/657` score for providers that may not expose all 657 Official FPL players. It may add stronger deterministic bridges or reviewed exception crosswalks with explicit provenance. It must not use runtime fuzzy matching, names, DOB heuristics, hidden aliases, or cross-provider majority voting as identity authority.

## Non-goals

V6 will not use fuzzy name matching, probabilistic identity scoring, hidden manual aliases, date-of-birth/name heuristics, or cross-provider majority voting to manufacture player links. Partial verified coverage is preferable to broad but uncertain matching.
