# FPL iphoenk Engine v3.5.0

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, projection/calibration frameworks, provenance/freshness, snapshot integrity and a noise-resistant Price Radar.

## v3.5 Official Rules Compliance
`src/rules.py` is the single source of truth for published FPL 2026/27 rules used by the engine.

Implemented and regression-tested:
- appearance scoring: 1 point below 60 minutes, 2 points at 60+ minutes
- goals: GK +10, DEF +6, MID +5, FWD +4
- assists +3; clean sheets GK/DEF +4 and MID +1
- goalkeeper saves +1 per three, penalty save +5
- penalty miss -2, every two goals conceded by GK/DEF -1, yellow -1, red -3, own goal -2
- defensive contribution points: DEF 10 CBIT = +2; MID/FWD 12 CBIRT = +2; capped at +2 per match
- published 2026/27 BPS deltas: tackled penalty removed, CBI reduced to 1 BPS per 3, goalkeeper save/big-chance changes, penalty-save BPS 7
- full BPS reconstruction remains Official FPL/Opta authority when raw metrics are unavailable
- chip rules: Wildcard, Free Hit, Triple Captain and Bench Boost once in each half, eight chips total; first set expires after GW19 deadline; only one chip per GW; Free Hit unavailable GW1 and cannot be used in both GW19 and GW20 consecutively
- chip ledger derived from Official history and persisted to `data/chips.json` and `data/latest.json`
- projection imports scoring constants from the rules module rather than hardcoding them independently
- published ruleset ID/source URLs persisted for auditability
- schema version 34

## v3.4.1 Price Radar fix
- actionable threshold: ownership >=0.5% and absolute event net transfers >=5,000
- separates actionable pressure from market noise
- adds confidence labels and regression coverage
- persists filtering consistently into `data/prices.json` and `data/latest.json`

## v3.4 reliability and native persistence
- persists Official `entry`, `history`, `transfers`, and submitted `picks`
- per-source provenance/freshness
- snapshot integrity ID and native change log
- fail-closed structural validation

## Production data flow
`Official FPL API -> GitHub collector/engine -> persisted data/*.json bridge -> FPL Master Monitor`

Direct ChatGPT browsing of Official team-specific endpoints is optional cross-check only.

## Collector / reporting cadence
- Normal Mode: 04:30 Deep Review, 12:30 Midday Tactical Monitor, 21:30 Night Tactical + Price Monitor WIB
- Match Mode: approximately every 3 hours while relevant PL/FPL matches are active
- Deadline Day: hourly at :30 WIB until definitive Final Review
- After Final Review: silent except genuinely material emergency updates

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
python fpl_daily_tasks.py stats-sync --gw 1
python fpl_daily_tasks.py advanced-stats --gw 1 --query "Haaland"
```

## Source authority
1. Official FPL API native fields and Official scoring
2. Persisted Official-FPL-derived bridge state
3. FPL-Core-Insights community enrichment
4. vaastav historical dataset
5. other mirrors only if explicitly enabled
6. web/news/tactical overlays

If direct Official FPL and persisted bridge disagree on a current native field, direct Official FPL wins and the conflict is logged.

## Rules authority principle
Local reconstruction is an audit aid only. It must not override Official FPL `total_points`, bonus allocation, rank, price or other native fields. BPS is not fully reconstructed without all required raw official metrics.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
