# V4.8.1 service architecture

V4.8.1 runs eight **independent**, process-isolated services on one host. The orchestrator owns dependency ordering, contract validation, immutable-artifact locks, and the final fail-closed state.

1. `raw_snapshot` is the only service permitted to call the Official FPL API. It also conditionally fetches GW1 picks and reconstructs purchase prices before publishing `snapshot.v1`.
2. `enrichment` reads the locked raw contract, optionally refreshes community statistics, and publishes `enrichment.v1` with the raw SHA-256 in its lineage.
3. `prediction` reads both locked contracts and runs the unchanged V4.7.1 prediction formula. Its latest output records both SHA-256 digests.
4. `rules_compliance` validates FPL rules.
5. `framework_preflight` runs checkpoint-aware PRE-FLIGHT governance.
6. `optimization` runs the unchanged V4.7.2 optimizer and unified decision pipeline.
7. `framework_postflight` runs the 16-check POST-FLIGHT gate.
8. `report_governance` emits the unchanged V4.7.3 checkpoint decision.

Every registry boundary is `INDEPENDENT`. A successful raw, enrichment, or prediction process is locked immediately; any later digest mismatch stops orchestration. Runtime contracts are written beneath `data/runtime/` and are intentionally excluded from Git.

The prediction boundary continues to publish the V4.8.0 operational surface (`live.json`, `prices.json`, `price_cache.json`, `health.json`, `chips.json`, the per-GW archive, and append-only `history.jsonl`). `latest.json` keeps pointers to every artifact consumed by reliability and governance checks.

The centralized V4.8.1 quality gate verifies 8/8 service evidence, lineage, decision equivalence, sell-cost correctness, Gate 0 (16), DSS Core (50), DSS Extension (16), and Enhancement Layers (8).
