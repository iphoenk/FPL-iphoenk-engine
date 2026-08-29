# V3 Compiled-Wave Parallelism

This candidate aligns the runtime scheduler with the already-compiled domain DAG without changing FPL business logic.

## Scope

- consume `V3_COMPILED_EXECUTION_PLAN_V1.domain_waves` for runtime concurrency;
- parallelize only multi-domain waves that are isolation-safe;
- require every capability in the wave to declare `isolated=true`;
- reject parallel execution when declared artifacts, latest keys, or latest file keys overlap across domains;
- preserve deterministic isolated workspace fan-in and sequential fallback;
- preserve all 11 execution domains, 6 phases, and 21 capability owners.

## Expected currently safe waves

1. `market_context || prediction`
2. `squad_decision || prediction_validation`

## Acceptance

- no change to xPts/xMins, lineup, captain/vice, bench, chip, watchlist, transfer, or report semantics;
- architecture and ownership guards PASS;
- unit/regression suite PASS;
- FULL/FAST material-decision equivalence PASS;
- FAST remains under 10s and preferably under the 7.5s warning threshold;
- compiled execution plan SHA remains unchanged because registry topology is unchanged;
- runtime metadata proves both eligible compiled waves were executed in parallel.
