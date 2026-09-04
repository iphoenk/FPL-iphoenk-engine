# V6 Free-Source and Matchday Weather Policy

## Purpose

V6 remains a **data-only acquisition platform**. It does not own FPL predictions, optimizer decisions, transfers, captaincy, or chip decisions. Free external evidence may be registered when it adds useful independent context and can be handled truthfully.

## Source activation tiers

The configured source universe is registry-driven. Source counts are not hard-coded in Python or workflow assertions.

- **core**: safe, repeatable machine ingestion that materially adds evidence.
- **pilot**: free public source that is useful but must prove runtime stability before being treated as core.
- **reference_only**: free evidence that may be used for targeted retrieval, but is not mirrored into scheduled runtime snapshots because of editorial structure, usage terms, or lack of a stable machine contract.
- **disabled**: paid, restricted, unsuitable, or explicitly dropped by owner decision.

### New free active sources

- `solio_analytics` — core, public no-auth JSON model evidence.
- `open_meteo_weather` — core and mandatory fixture-weather context.
- `check_the_chance` — pilot bookmaker-derived probability evidence.
- `fantasy_football_pundit` — pilot lineup/start-probability and team-news evidence.

### New free reference-only sources

- `bbc_team_news`
- `premier_injuries`
- `fpl_form`
- `fpl_review_free`

These references are discoverable in V6 configuration but deliberately excluded from hourly health counts and persisted runtime snapshots.

## Open-Meteo contract

Open-Meteo is a mandatory context source because adverse matchday conditions can materially affect football execution even when they should not be converted into an uncalibrated FPL points coefficient.

V6 queries the 20 current 2026/27 Premier League home venues in one multi-location request and joins weather to the **Official FPL fixture authority** using the home team and kickoff time.

Collected signals include:

- temperature
- relative humidity
- precipitation probability
- precipitation intensity
- rain
- showers
- WMO weather code
- sustained wind speed
- wind gusts

The next-FPL-event fixture row receives the nearest hourly forecast point to kickoff when available.

### Governance

Weather evidence follows the canonical precedence:

`LIVE_OBSERVED > CLOSEST_TO_KICKOFF_OBSERVATION > FRESH_FORECAST > STALE_FORECAST`

Severity is rendered as:

`NORMAL / NOTABLE / ADVERSE / EXTREME`

The current Open-Meteo adapter supplies **FRESH_FORECAST** evidence. It does not falsely label modelled current conditions as a station observation.

Hard rules:

- `weather_direct_xpts_multiplier = false`
- `weather_alone_can_trigger_transfer = false`
- weather is contextual evidence for matchup, role, technical execution and risk interpretation
- Official FPL remains fixture/team authority
- missing weather must be explicit; values are never invented

Legacy attention thresholds from the prior weather advisor are preserved as low-level flags (30 km/h wind, 60% rain probability, 5°C cold), while precipitation intensity and gusts provide additional severity context.

## Cadence

- Open-Meteo: hourly.
- Solio: every 4 hours, hourly in the deadline window.
- Check The Chance: every 6 hours, hourly in the deadline window.
- Fantasy Football Pundit: every 6 hours, hourly in the deadline window.
- ClubElo: every 6 hours; HTTPS, shorter timeout, last-good cache preserved.

The scheduler remains hourly. `NOT_DUE` is an intentional state and does not indicate source failure.

## Attribution

Open-Meteo data is attributed as: **Weather data by Open-Meteo.com (CC BY 4.0).**
