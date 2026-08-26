# V4.8 service architecture

V4.8.0 is a process-isolated, single-host service architecture. It is intentionally not described as a distributed network deployment: each service runs in its own Python process, while one orchestrator owns ordering, the immutable snapshot, and the final failure state.

## Execution flow

1. `snapshot_prediction` refreshes one authoritative point-in-time snapshot and produces enrichment and V4.7.1 predictions. This is the only transitional composite boundary.
2. `rules_compliance` proves the FPL rules implementation independently.
3. `framework_preflight` evaluates framework readiness before optimization.
4. `optimization` runs the unchanged V4.7.2 WC/package search, lineup governance, and evidence sanity.
5. `framework_postflight` executes all 16 Gate 0 checks against decision outputs.
6. `report_governance` applies V4.7.3 checkpoint and action policy.

The centralized V4.8 quality gate runs after the orchestrator and validates both the domain outputs and the service execution evidence.

## Contracts and failure model

- `config/service_registry.json` owns dependency order, commands, timeouts, criticality, and declared outputs.
- `config/service_contract_registry.json` owns artifact paths and minimum schema, version, required-field, equality, and collection-size checks.
- A service is `PASS` only when its process exits successfully and every declared output satisfies its contract.
- Dependency failure stops all downstream execution.
- `latest.json` is hashed after refresh. Any downstream mutation fails the run.
- Logs, timings, contract hashes, and failure evidence are stored in `data/service_orchestration_v4.json`.

## Preserved invariants

- Prediction formula remains V4.7.1.
- WC and package search widths remain V4.7.2.
- Checkpoint governance remains V4.7.3.
- Gate 0 remains exactly 16 checks.
- DSS Core, DSS Extension, and Enhancement counts remain 50, 16, and 8.
- Owned assets use sell cost; unowned assets use current cost.
- A simulated `--as-of` run never authorizes live execution.

## Remaining extraction debt

Snapshot acquisition, enrichment synchronization, and prediction generation still share one process because V4.7 built them around the same in-memory bootstrap and fixture objects. Separating them safely requires immutable raw snapshot contracts first. Until that equivalence work is complete, splitting them across independently fetching services would create inconsistent point-in-time data and is prohibited.
