# FPL-iphoenk-engine

A governed Fantasy Premier League decision-support engine.

It combines public football facts, probabilistic player modelling, full-universe discovery, squad optimisation, Monte Carlo analysis, mini-league context, and private report delivery.

> **V6 establishes factual truth. Canonical V12 interprets those facts for FPL decisions. Manager-specific state and reports remain private.**

## Architecture

`Official/Public Data → V6 Facts → Canonical V12 → Optimisation → WAIT / PREPARE / ACT → Reports`

- **V6 factual plane** owns governed facts, freshness, fixtures, prices, and source evidence.
- **Canonical V12** owns xMins, probability, tactical analysis, full-universe scanning, squad/transfer optimisation, Monte Carlo, and decision semantics.
- **Private delivery** owns manager-specific squad state, scenarios, mini-league context, final decisions, and full reports.

## Reports

| Mode | Purpose |
|---|---|
| **DEEP** | Full planning and decision report |
| **PRICE** | Price and transfer-timing monitoring |
| **DEADLINE / FINAL** | Final pre-deadline decision |
| **MATCH** | Post-deadline and matchday monitoring |

Primary schedule: **DEEP 04:30 / 12:30 / 21:30 Asia/Jakarta**, **PRICE 23:30 Europe/London**. Deadline and Matchday use governed checkpoints.

Reports are occurrence-bound, provenance-aware, privacy-safe, and degrade explicitly when evidence is unavailable rather than inventing data.

## Principles

- scan the **full eligible FPL universe** before shortlisting;
- model minutes, starting probability, and position-specific outcomes;
- separate factual evidence from model inference;
- optimise XI, bench, captaincy, and transfer packages;
- preserve uncertainty and provenance;
- keep manager-specific state private;
- separate report delivery from unrelated engineering/performance closure.

## Documentation

README intentionally stays short. Detailed methodology, formulas, evidence weighting, privacy, scheduler, delivery architecture, presentation contracts, P4/P6, cache behaviour, performance validation, and engineering governance live under `docs/v12/`.

Delivery authority: `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`

Schedule authority: `config/delivery/v12_delivery_schedule.json`

## Development

```bash
python -m pytest -q
```

Production truth comes from governed CI/runtime evidence, not from a hard-coded README status or branch claim.

> **Caveat:** this is a decision-support system, not an oracle. FPL outcomes remain stochastic and source evidence can change quickly.
