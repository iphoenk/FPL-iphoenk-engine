# V5.0.0-beta.4 Advanced Acceptance Hardening

V5 beta.4 is an isolated candidate track. Production remains **V3.20.0** at main SHA `15e75599045f901958753c2bcb275fceacc94d7c` and schema 48. Nothing in this track authorizes automatic production promotion.

## What is implemented

- Runtime release fingerprint and cached release attestation bind the candidate to V5 version, exact production baseline and governed runtime content.
- FeatureBundle distinguishes `UNAVAILABLE`, `AVAILABLE` and `ACTIVE`. `ACTIVE` requires explicit consumption evidence. Missing data is never silently converted to zero.
- Prediction exposes a shadow-only advanced overlay: start/bench/DNP xMins distribution, bounded sustainability diagnostic, probabilistic attacking-return evidence, empirical-only DefCon probability, and model/aleatoric uncertainty decomposition. Base authoritative xPts is preserved during beta.
- Evaluation freezes pre-deadline forecasts, checks temporal leakage, settles finished gameweeks, and compares settled metrics with a frozen baseline. Absence of a baseline is not a pass.
- Correlated package simulation supports deterministic replay, common-shock correlation and adaptive stopping, but is not decision authority until calibration evidence exists.
- Team Review is an isolated read-only bounded context. It cannot mutate truth or decision authority and is not published to the user report until explicitly adopted.
- V3/V4 capability parity is registry-driven. V4 remains research/reference, never production authority.

## V3.20 source-boundary convergence

The beta.4 source registry follows V3.20 production semantics. Network locations and ingestion timeouts are registry-owned; active artifact aliases are gameweek-independent; OneFPL automated collector access is disabled and delegated to report-time access; Understat direct scraping is disabled by default. Official FPL remains the only native external authority.

## Production-candidate gates

Operational acceptance requires three postvalidated `REAL_SHADOW` cycles on the same V5 version, exact production baseline, and exact runtime release fingerprint. Prediction acceptance is separate and mandatory: at least four settled gameweeks, 1,000 player-GW samples, 750 starter samples, 300 clean-sheet samples, all required metrics, temporal guard PASS, and non-regression against a real frozen baseline.

Because beta.4 currently has no populated frozen baseline in `config/intelligence/prediction_evaluation.json`, prediction acceptance intentionally remains blocked. This is a fail-closed design, not an implementation failure.
