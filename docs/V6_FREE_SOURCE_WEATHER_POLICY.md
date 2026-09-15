# V6 Free-Source and Matchday Weather Policy

## Purpose

V6 remains a **data-only acquisition platform**. It does not own FPL predictions, optimizer decisions, transfers, captaincy, chip decisions, or report-time weather retrieval. Free external evidence may be registered when it adds useful independent context and can be handled truthfully.

## Source activation tiers

The configured source universe is registry-driven. Source counts are not hard-coded in Python or workflow assertions.

- **core**: safe, repeatable machine ingestion that materially adds evidence.
- **pilot**: free public source that is useful but must prove runtime stability before being treated as core.
- **reference_only**: free evidence that may be used for targeted retrieval, but is not mirrored into scheduled runtime snapshots because of editorial structure, usage terms, or lack of a stable machine contract.
- **disabled**: paid, restricted, unsuitable, or explicitly retired by owner decision.

## Weather ownership

Open-Meteo is **retired from active V6 runtime acquisition**. V6 must not poll Open-Meteo, must not require a V6 weather dataset, and weather freshness must not participate in V6 publication or report-delivery health gates.

Matchday weather is owned by the **ChatGPT report-time enrichment layer**:

1. Resolve fixture, venue and kickoff from Official FPL / official competition authority.
2. At report time, ChatGPT queries its available Weather tool/application directly for the actual venue.
3. Prefer the freshest practical hourly forecast centered on kickoff and the match window.
4. Treat weather as low-weight contextual evidence by default.
5. Normal conditions are summarized as `WEATHER: NO MATERIAL IMPACT`.
6. Only materially abnormal conditions may adjust football assumptions, with mechanism, direction and confidence stated.
7. If the Weather tool is unavailable, report the weather scope as degraded and continue delivery. Weather must never block the FPL report.

Hard rules:

- V6 weather is not a required dataset or dependency.
- `weather_direct_xpts_multiplier = false`
- `weather_alone_can_trigger_transfer = false`
- weather must not automatically overwrite xPts, xMins, Starting XI, transfers, captain/vice-captain, or chips
- Official FPL remains fixture/team authority
- missing weather must be explicit; values are never invented

The provider-specific Open-Meteo registry/adapter may remain in repository history or dormant configuration for traceability, but `source_activation.json` is the production activation authority and must keep `open_meteo` disabled unless the owner explicitly changes the architecture again.

## Other free/reference sources

Free and reference sources retain their configured activation status independently of weather. Ben Crellin remains a report-level fixture/calendar reference for BGW/DGW/rearrangement/congestion context and is not a weather provider or player-projection authority.

## Cadence

The V6 scheduler remains hourly. Weather is not on the V6 cadence. Report-time weather refresh follows the FPL Master report/deadline/final-review contract instead.

`NOT_DUE` remains an intentional state for sources that still use adaptive V6 polling and does not indicate source failure.
