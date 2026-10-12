# S10 actionable ETA evidence

Change timestamp: 2026-10-12T15:35:00+07:00

S10 now preserves the existing two locked tables while rendering unsupported price-change timing explicitly as `ETA_UNAVAILABLE (reason/state)`. A missing crossing is never presented as a date, calibrated probability, or generic actionable ETA. Producer-bound WIB dates and windows remain unchanged.

Regression coverage uses synthetic rows for a supported date, an explicit no-crossing reason, and a missing reason.