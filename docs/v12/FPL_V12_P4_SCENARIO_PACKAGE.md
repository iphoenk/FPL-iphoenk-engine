# FPL V12 P4 Canonical Scenario Package

Status: production candidate from exact main ab3ebc64d1234cc251448e3c571f018d2177cffb.

P4 is a private precomputation layer over the existing Canonical V12 evaluator, never a second model, optimizer, scheduler, or scorer. Public code defines contracts and tests; manager-specific packages remain private.

The bounded package contains BASE_CURRENT15, exactly 15 UNAVAILABLE(player_id) scenarios, and CAPTAIN_UNAVAILABLE / VICE_UNAVAILABLE when material. Every non-base scenario enters through the canonical P1.1 availability path. Post-hoc xPts, XI, captain, route, or S19 mutation is forbidden.

Reuse is fail-closed. The base fingerprint binds model version, OUR15 identity, fixture/GW identity, projection lineage, cache/schema version, MC authority, and owner/private context. Any mismatch is MISS_RECOMPUTE. No approximate or cross-owner reuse is allowed.

Acceptance requires exact decision-surface equality against direct canonical computation, deterministic fingerprints, stale/wrong-base rejection, private-only persistence, and no public personal plaintext.

Production rebuild acceleration is cache-reuse only, not analytical approximation. The P4 workflow may restore the integrated runner's deterministic public-safe Stage-2 cache plus encrypted AEAD P1.7 and MC caches using the same semantic key families. A cache miss remains canonical recomputation. Restored private files must be authenticated `*.aead.json` envelopes and the 256-bit decrypt-key contract is validated before evaluation. P4 does not persist a separate cache family.

Counterfactual execution is bounded to at most two isolated spawned worker processes. Each worker calls the same canonical `run_deep` evaluator with the same occurrence-bound factual/private inputs, a unique output directory, and a scenario-local cache namespace. Every override must still PASS the canonical P4 acknowledgement and Stage-2-bypass guard. Results are keyed by canonical override JSON and consumed by the unchanged package builder in deterministic scenario order. This changes wall-clock scheduling only: MC remains 500k, full universe/routes and all scenarios remain intact, and cache misses remain exact recomputation.
