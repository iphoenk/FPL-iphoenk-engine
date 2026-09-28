# FPL V12 P4 Canonical Scenario Package

Status: production candidate from exact main 5ff0e8b2c25a118d099ffb57ea55acda82e1e186.

P4 is a private precomputation layer over the existing Canonical V12 evaluator, never a second model, optimizer, scheduler, or scorer. Public code defines contracts and tests; manager-specific packages remain private.

The bounded package contains BASE_CURRENT15, exactly 15 UNAVAILABLE(player_id) scenarios, and CAPTAIN_UNAVAILABLE / VICE_UNAVAILABLE when material. Every non-base scenario enters through the canonical P1.1 availability path. Post-hoc xPts, XI, captain, route, or S19 mutation is forbidden.

Reuse is fail-closed. The base fingerprint binds model version, OUR15 identity, fixture/GW identity, projection lineage, cache/schema version, MC authority, and owner/private context. Any mismatch is MISS_RECOMPUTE. No approximate or cross-owner reuse is allowed.

Acceptance requires exact decision-surface equality against direct canonical computation, deterministic fingerprints, stale/wrong-base rejection, private-only persistence, and no public personal plaintext.
