# V3 Post-Green Operating Mode

Status: **GREEN PROD runtime / evidence-calibration phase**  
Tracker: #350  
Native GitHub platform hardening: #319

## Purpose

V3 has completed architecture/runtime hardening. The default operating posture is now:

> **Observe first. Calibrate only from genuine settled evidence. Do not refactor a green architecture without a proven defect.**

This document does not create new prediction or decision semantics. It records how the existing governed evaluation policy is to be operated after production hardening.

## Canonical evaluation authority

`config/intelligence/prediction_evaluation.json` remains authoritative.

Required invariants:

- freeze the last genuine pre-deadline snapshot;
- settle only finished Official FPL events;
- genuine pre-deadline capture is required for decision-regret metrics;
- retroactive decision reconstruction is forbidden;
- transfer realized net gain requires exact hit cost;
- retrospective proxy baselines do not count toward predictive-accuracy or dynamic-weight evidence;
- dynamic-weight review requires at least the governed minimum sample (`50` at time of this document);
- position drift is diagnostic-only and may not automatically change weights;
- projection-confidence calibration review starts only at the governed review GW.

Numeric thresholds remain owned by the config above. This document intentionally does not duplicate them as a second runtime authority.

## Evidence to accumulate

### Prediction quality

- points MAE;
- points RMSE;
- xMins MAE;
- starter Brier;
- DNP Brier;
- clean-sheet Brier;
- Spearman rank correlation.

### Decision quality

- captain regret;
- vice regret;
- XI regret;
- first-bench regret;
- transfer comparator realized net gain.

### Diagnostics

Where governed sample size is sufficient, inspect by position, confidence bucket, starter/rotation-risk bucket, price band, fixture difficulty, home/away, and governed tactical/player-role archetype. Diagnostics alone do not grant production calibration authority.

## Production soak contract

Continue observing every production checkpoint for:

- source-health integrity;
- Gate0 16/16;
- DSS core/extensions/enhancements registry health;
- owned-15 authority reconciliation;
- watchlist-20 membership reconciliation;
- batch/interactive tactical parity;
- final lineup metadata and `latest` summary reconciliation;
- publication whitelist and source provenance;
- exact `runtime-data` source attestation;
- FAST and instant-serving SLO compliance.

## Change-control freeze

Until genuine settled evidence justifies a change, do not change solely for cleanup, preference, or speculative improvement:

- prediction/xPts/xMins mathematics;
- optimizer breadth or search width;
- DSS scoring semantics;
- tactical/weather decision semantics;
- lineup, captaincy, chip, or transfer semantics;
- canonical domain/capability ownership;
- calibration thresholds.

Permitted pre-maturity changes are limited to:

1. proven correctness, security, or runtime defects;
2. source/API compatibility fixes;
3. observability/evidence-capture fixes that preserve decision semantics;
4. production-governance hardening;
5. tests and documentation.

## Calibration gate

A production calibration proposal must provide all of the following:

1. genuine pre-deadline snapshots settled only after Official FPL event completion;
2. sufficient governed sample size;
3. before/after metrics on the same settled sample;
4. no post-deadline information leakage;
5. challenger/shadow evidence before production authority;
6. full regression and FULL/FAST acceptance;
7. explicit improvements, regressions, uncertainty, and rollback path.

If these conditions are not met, the correct action is **continue observing**, not tune the model.

## Platform-control boundary

Issue #319 remains separate. Native GitHub branch/ruleset controls are defense-in-depth platform governance and must not be represented as model calibration or engine correctness. V3 runtime may remain production-green while #319 remains open, but #319 is not considered complete until its own native GitHub acceptance criteria are met.
