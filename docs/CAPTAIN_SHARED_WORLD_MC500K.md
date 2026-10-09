# V12 Shared-World Captain and Goalkeeper Calibration

The canonical captain frontier remains the owner of football decision semantics. This module adds an optional shared-world observability and simulation adapter.

## Availability contract

A shared-world result is AVAILABLE only when:

- every selected-XI candidate has a canonical point PMF;
- every goalkeeper candidate has calibrated clean-sheet, conceded-goals, saves, bonus, penalty-save and appearance probabilities;
- the goalkeeper payload carries source, dataset, calibration version and evidence cutoff provenance.

Missing calibration returns UNAVAILABLE. No default goalkeeper event probability is substituted.

## Simulation contract

The C/VC simulator uses exactly 500,000 paths and a deterministic seed. The same world-uniform stream is used across candidates, and the vice-captain is activated only when the sampled captain appearance state is DNP.

Published outputs include candidate distributions, C/VC distribution, captain winner probabilities, vice activation probability, Q50/Q75/Q90, convergence standard error, seed, source/dataset lineage and evidence cutoff. Optional mini-league entries use the same simulated world for rank distributions.

S08, S18 and S19 must consume the returned canonical C/VC object. This adapter does not select a captain independently and does not convert EO into expected points or relative-points forecasts.
