# FPL iphoenk Engine V5

**V5.0.0-alpha.1 · Unified Decision Engine**

V5 is the architectural convergence track for the FPL iphoenk Engine. It combines the reliability/truth strengths of V3 with the prediction/decision strengths of V4 while enforcing single authoritative implementations for rules, state, finance, projection and decisions.

## Operating tracks

- **V3.x** remains the production and scheduled-task runtime.
- **V4.x** remains the active prediction R&D, tuning and calibration track.
- **V5.x** is the overhaul/convergence track and is not production-promoted yet.

## V5 architecture

### Truth plane
- Official FPL API authority
- authenticated read-only Official overlay target
- phase-aware squad state
- registry-driven Official 2026/27 rules
- exact finance and sell-value target
- price trajectory target
- persistence, provenance, freshness and leakage protection

### Intelligence plane
Inherited from the V4.7 baseline:
- official-ID Core Insights integration
- prior-season vaastav reconciliation
- set-piece and penalty role shares
- venue-normalized opponent defensive resistance
- xMins starter-security/competition/rotation priors
- interpretable xPts pipeline
- Monte Carlo scenarios
- package/portfolio optimization
- calibration utilities

### Governance plane
- Gate0 hard constraints
- DSS core registry
- DSS extension registry
- enhancement layers registry
- preflight/postflight health
- centralized quality gates
- V5 convergence acceptance

### Decision plane
V5 introduces explicit contracts for TruthState, PlayerProjection and DecisionTrace. A production-grade V5 recommendation must be traceable from evidence through projection to the final action and checked constraints.

## First V5 migration completed

The V3.9 Official FPL rules registry is now present in V5 and `src/models/projection.py` consumes scoring constants from that registry. This removes the V4 hardcoded goalkeeper-goal value and makes the 2026/27 value of **10 points for a goalkeeper goal** authoritative from one rules source.

## Bootstrap acceptance

```bash
python -m src.v5.acceptance
python -m pytest -q tests/test_v5_bootstrap.py
```

The V5 gate currently checks the convergence manifest, V3/V4 baseline declarations, active ruleset integrity, goalkeeper scoring, rules fingerprinting, projection-to-rules wiring, absence of the legacy hardcoded goal map and the production-promotion lock.

## Existing V4 commands retained during convergence

```bash
pip install -r requirements.txt

python fpl_daily_tasks.py daily --stats
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live

python fpl_daily_tasks.py stats-sync --gw 1
python fpl_daily_tasks.py stats-sync --gw 1 --deep
python fpl_daily_tasks.py advanced-stats --gw 1 --query "Haaland"

python -m src.engines.framework_health_audit --phase preflight --strict
python -m src.engines.v4_decision_pipeline
python -m src.engines.framework_health_audit --phase postflight --strict
python -m src.engines.v4_quality_gate
```

## Promotion rule

V5 cannot replace V3 production until it demonstrates:

1. no material regression against V3 truth/reliability capability;
2. no material regression against V4 prediction/decision capability;
3. no duplicated authority in a V5 decision path;
4. evidence/provenance on predictions and decisions;
5. calibration reporting separate from structural health.

See `docs/V5_CONVERGENCE.md` and `config/v5_convergence_manifest.json` for the migration ledger and acceptance contract.
