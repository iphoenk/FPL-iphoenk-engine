# FPL iphoenk Engine

> **Last runtime/documentation sync:** `2026-09-27T14:29:45+07:00`

**Probability-driven decision engine for Fantasy Premier League.**

FPL iphoenk Engine combines factual football data, probabilistic player modelling, tactical analysis, squad optimization, and Monte Carlo simulation to support FPL decisions.

> Independent open-source project. Not affiliated with or endorsed by the Premier League or Fantasy Premier League.

## Architecture

```text
Public football data
        ↓
      V6
 Factual Data Plane
        ↓
Canonical V12
Analytics & Decision Engine
        ↓
Private Manager Plane
Squad-specific decisions & reports
```

**V6** owns factual data, normalization, freshness, identity, and evidence lineage.

**Canonical V12** owns modelling, probabilities, tactics, optimization, simulation, and decision semantics.

Manager-specific squad state and reports remain outside the public factual plane.

## What it does

| Area | Capability |
| --- | --- |
| Minutes | xMins, availability, P(start), cameo/DNP risk |
| Players | xG, npxG, xA, xGI, shots, creation, role |
| Goalkeepers | Saves, clean sheets, save-point distributions |
| Defenders | Clean sheets, DefCon, attacking and set-piece threat |
| Midfielders | Goals, assists, creation, penalties and set pieces |
| Forwards | Goal process, box involvement and attacking role |
| Tactics | Player role × team system × opponent matchup |
| Lineup | XI, formation, bench, captain and vice |
| Transfers | Exact legal transfer-package search |
| Horizons | GW+1, 2GW, 3GW and 5GW |
| Uncertainty | Point distributions, blank/haul risk and quantiles |
| Simulation | Correlated Monte Carlo |
| Mini-league | Ownership, starter and captain exposure |
| Post-match | Process vs result and player trajectory |

## Decision model

The football baseline combines four evidence groups:

```text
20% Proven / Historical
25% Tactical / Role
30% Current Underlying
25% Fixture / Security
```

The engine is **distribution-first**, not just xPts-first.

Typical outputs include:

```text
xMins
P(start)
Expected Points
P(blank)
P(haul)
Q10 / Q25 / Q50 / Q75 / Q90
```

Starting probability, event rates, and point outcomes are modelled probabilistically rather than treated as fixed values.

## Transfer decisions

Transfer analysis starts from the eligible FPL universe rather than a manually selected shortlist.

Routes are compared with **HOLD** across separate horizons:

```text
GW+1
2GW
3GW
5GW
```

The engine also considers exact affordability, selling value, free transfers, hits, future FT opportunity cost, downside, regret, reversal risk, and squad flexibility.

Monte Carlo is used when deterministic comparison is not sufficient.

## Decision states

Final decisions use three operational states:

```text
WAIT
PREPARE
ACT
```

The engine keeps **facts → model output → uncertainty → decision** separate rather than presenting every estimate as fact.

## DEEP decision-content delivery barrier

DEEP reports are deliverable only when canonical analytics, decision materialization, rendering, and semantic validation agree. Missing or unsupported evidence remains explicitly degraded or unavailable rather than being invented by the presentation layer.

## PRICE human-facing delivery barrier

PRICE reports follow the same fail-closed principle: price evidence, freshness, affordability context, and decision state must remain traceable to governed inputs. A PRICE report must not manufacture unavailable manager state.

## What makes it different

FPL iphoenk Engine combines several layers that are often separate in other FPL projects:

- full-universe player scanning;
- xMins and P(start);
- position-specific probability models;
- tactical and role-aware matchup analysis;
- exact lineup and transfer optimization;
- multi-GW package evaluation;
- correlated Monte Carlo;
- mini-league context;
- GW1-to-current post-match learning;
- public compute separated from private manager state;
- governed and fail-closed delivery.

## Repository

```text
src/                 engine and analytics
config/              runtime and model configuration
control/             canonical control contracts
scripts/             operational tools
tests/               regression and validation
docs/                architecture and methodology
.github/workflows/   CI and governance
```

Detailed methodology, runtime contracts, and architecture are maintained under [`docs/`](docs/).

## Installation

```bash
git clone https://github.com/iphoenk/FPL-iphoenk-engine.git
cd FPL-iphoenk-engine

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
python -m pytest -q
```

Production acceptance may require additional runtime and governance checks beyond the local test suite.

## Privacy

The public repository contains reusable factual and compute components.

Manager-specific squad state, financial state, transfer routes, captaincy, mini-league membership, and private reports are not intended for public storage.

## Status

Active architecture:

- **V6** factual data plane
- **Canonical V12** analytics and decision engine
- **Private manager plane** for personalized state and output

Current production health should be determined from runtime and CI evidence, not from a static README SHA.

## Disclaimer

Football and FPL outcomes are inherently uncertain. This project is a decision-support system, not a prediction oracle.

Fantasy Premier League, FPL, Premier League, and related marks belong to their respective owners.
