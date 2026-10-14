# Exact-occurrence prefetch cutoff for current-report advisory context

Change timestamp: 2026-10-14T23:34:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:34:00+07:00

The logical slot identifies a governed report occurrence. Understat/FotMob acquisitions may finish later in that exact run. Controlled V6 run 38596441188 checked sources around 2026-10-14T16:15:12Z for logical slot 2026-10-14T23:14:00+07:00. Strictly comparing effective_at to the nominal slot wrongly rejects potentially useful current-report evidence. Such after-slot sources are **not** evidence that they existed at the earlier nominal slot or before a historical GW deadline.

After PR #1082, both the active materializer and integrated report runner already bind the original V6 detail to its exact report kind, logical slot, prefetch run ID, generated timestamp, and lossless historical archive. This change uses the bound original prefetch generated_at as the advisory source observation cutoff, rejecting any later source, while keeping the logical slot independent. Canonical roster and fixture observations remain source identity and cutoff gated. S02 now reports the distinct clocks, verified/eligible/consumed/rejected counts, and `historical_predeadline_source_asof_admission=NOT_ASSERTED`.

No old GW1-GW6 training fold is admitted; no numerical role/manager effect, canonical P(start), xMins, xPts, GW7 immutable forecast, Stage3, P1.7, MC500K, scheduler or PR #809 changes. A provider aggregate is never allocated to fictitious fixture rows.

Two new regressions validate postlogical-but-preprefetch admission and future/naive timestamps. Existing active materializer test now explicitly covers a legitimate postlogical source. 54 required governance files and 1,416 test IDs remain mandatory. Actual production DEEP consumption requires postmerge exact-occurrence private receipt; Wave 3 natural acceptance requires genuinely natural slots.

## Controlled DEEP QA failure recovered in code

Controlled DEEP run `38596886053` on pre-fix main `4b03c22f96bf` failed `HUMAN_FACING_QA` because S02 formatted `rejected_reasons` as Python mapping repr. Private publication correctly aborted, so that run is not a successful receipt. The renderer now uses the existing human-safe compact formatter for both source rejection mappings. The existing S02 visible-contract regression checks rejection reasons are rendered as prose and raw mapping repr is absent. Only a fresh production run with a passing private receipt can promote delivery.
