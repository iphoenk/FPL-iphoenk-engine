# External FPL dashboard adoption registry

Updated: 2026-10-25

This engine registry records external repositories reviewed as implementation references. It does not create a second model authority. Official FPL remains authoritative for official fields, V6 owns factual acquisition/provenance, Canonical V12 owns the decision contract, and the existing correlated MC500K implementation remains the only Monte Carlo authority.

## Governance

- Copy source code only where the source license permits it, retaining attribution and notices.
- For unclear or absent licenses, implement behavior independently and credit the source as a reference.
- External evidence is admitted through explicit adapters with source, timestamp, freshness, coverage and calibration state.
- No external repository may add a scheduler, replace Canonical V12, overwrite Official FPL truth, or create a competing optimizer.
- MC500K is already implemented in this engine through the existing V12 Monte Carlo modules and contracts. External Monte Carlo claims are reviewed as ideas only and are not a replacement.

## Adoption registry

| Source | Useful pattern | Engine destination | Status |
|---|---|---|---|
| [JonnoMillar/fpl-insights](https://github.com/JonnoMillar/fpl-insights) | xGI/90, defensive contribution, fixture binding, availability, captaincy, degraded evidence | V6 evidence adapters and V12 feature contracts | Candidate reimplementation |
| [requiemalex/fpl-analytics-dashboard](https://github.com/requiemalex/fpl-analytics-dashboard) | Per-record validation, normalized types, cache, retry, stale fallback and provenance | V6 acquisition and serving contracts | Candidate reimplementation |
| [avgcloudwizard/wireless](https://github.com/avgcloudwizard/wireless) | One snapshot, last-good retention, freshness and free-transfer reconstruction | V6 runtime publication and report input contract | Candidate reimplementation |
| [ahmedrashadtxt/fpl-strategic-dashboard](https://github.com/ahmedrashadtxt/fpl-strategic-dashboard) | Legal constraints, transfer friction and pre-deadline audit journal | V12 P1.7/P4 and private report journal | Candidate, MIT stated in source README |
| [Doocey/fpl-dashboard](https://github.com/Doocey/fpl-dashboard) | Price history and refresh pattern | V6 price evidence | Reviewed |
| [j-maslin/fpl-dashboard](https://github.com/j-maslin/fpl-dashboard) | Compact league metrics and adaptive charts | Dashboard only | Reviewed |
| [thinesrao/fpl-dashboard-streamlit](https://github.com/thinesrao/fpl-dashboard-streamlit) | Mini-league awards and historical analysis | Dashboard only | Reviewed, MIT stated in source README |
| [uixori-code/fpl-fantasy-dashboard](https://github.com/uixori-code/fpl-fantasy-dashboard) | Public Team ID UX and separated fetch scripts | Dashboard only | Reviewed |
| [dhruvgupta2109/fplmanager](https://github.com/dhruvgupta2109/fplmanager) | Guest Team ID, pitch, fixtures and rank trend | Dashboard only | Reviewed, MIT stated in source README |
| [pdamkier-del/fpl-analytics-app](https://github.com/pdamkier-del/fpl-analytics-app) | Model version and updater separation | Private reports | Reviewed |
| [maballouk/fplanalytic](https://github.com/maballouk/fplanalytic) | TypeScript and test organization | Dashboard only | Reviewed |
| [jorgefhernandezg/fpl-dashboard](https://github.com/jorgefhernandezg/fpl-dashboard) | Public dashboard reference | Dashboard only | Reviewed |

## Monte Carlo position

The existing engine already owns:

- correlated V12 Monte Carlo;
- MC500K minimum path contract;
- common random numbers;
- convergence and variance acceptance;
- formation and captain/vice-captain distribution;
- P1.7 lineup migration and downstream consumption;
- private cache and provenance controls.

External Monte Carlo implementations must not be copied into the engine as a second simulator. Useful statistical ideas may be added only through a reviewed change to the existing V12 Monte Carlo owner, with regression tests and an explicit contract update.
