# P0 actual report-time source cutoff admission

14 October 2026. Scope: advisory GW1-GW6 retrospective context **only**. This does not constitute historical predeadline source as-of or prospective GW7 calibration.

## Failure mechanism

The same source V6 `report_prefetch` occurrence can start at nominal logical slot HH:MM but finish normalization after that minute. At controlled logical slot `2026-10-14T23:14:00+07:00`, the V6 source check occurred around `2026-10-14T16:15:12Z`. The prior `_source_is_eligible(source, report_slot)` compares it to `16:14Z`, so even 424 verified Understat player identities and 380 verified FotMob fixture identities can result in 0 S02 join. That was a mismatch of nominal slot vs actual admitted observation time, not license to backdate source records.

## Exact occurrence boundary

`v12_integrated_report_runner._analytics_production_acceptance()` already independently requires matching `official_detail` and `report_prefetch/latest` logical slot, exact report kind, run ID and generated_at. Only after those checks does it pass the **identical** prefetch `generated_at` as `observation_cutoff_at` to `build_retrospective_context()`. The current-report retrospective advisory bridge uses `source.effective_at <= observation_cutoff_at`. Without verified timestamp or exact occurrence, the original source gate remains fail-closed. No implicit wall-clock adjustment, post-prefetch source, inferred capture or temporal backfill is allowed.

S02 now reports logical slot and actual source cutoff separately and labels historical predeadline admission `NOT_ASSERTED`. This does not alter canonical P(start), xMins, xPts, forecast GW7, original GW1-GW6 training folds or Stage3 fail-closed checks.

## CI and production verification

Two deterministic regressions cover the previously rejected valid post-slot/pre-prefetch observation and rejection of future/naive timestamps. Exactly 1,410 reviewed test node IDs across 54 mandatory files. A real DEEP postmerge occurrence, same-source readback, source ledger `consumed_rows` and private receipt remain separate deployment and acceptance gates. A valid source identity alone cannot be counted as DEEP consumed.

Change timestamp: 2026-10-14T23:28:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:28:00+07:00
