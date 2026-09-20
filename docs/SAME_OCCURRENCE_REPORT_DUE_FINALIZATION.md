# Same-occurrence dynamic REPORT_DUE finalization repair

Stage B baseline / P1.3 intermediate SHA: \`a0f6e9a70ca205ecf7de0590307c36841956856f\`.

This document is evidence only. It is not authority and does not change V6, scheduler ownership, methodology, report cadence or the 20/25/30/25 football weights.

## Proven 19:30 failure path

Natural occurrence: 2026-09-19 19:30 WIB. The pre-core report route could evaluate false from stale fixture state. The existing natural-core plan stored that Boolean as \`report_due\`. Core upkeep then refreshed the current 19:00 logical slot successfully, but the terminal core proof still carried the original false value.

Before this repair, \`validate_natural_occurrence_completion(..., report_due=false)\` could return \`visible_silence_allowed=true\`. \`authorize_post_core_stage\` validated against the \`report_due\` already stored in the core proof. Separately, \`finalize_same_occurrence_alert_evidence\` accepted \`alert_triggered\` and finalized values only for an alert that had already been routed. It had no authority or mechanism to promote a pre-core false route to true.

Therefore a fresh post-core fixture with \`started=true\` and \`finished=false\` could exist while the occurrence still followed the stale preliminary false route. This is the exact routing gap repaired here. No V6 acquisition/publisher defect is implicated.

The deterministic regression case binds run id 35442926265 and a GW5 fixture with kickoff 2026-09-19T11:30:00Z (18:30 WIB), preliminary not-live evidence, and post-core \`started=true, finished=false\`. It must promote FINAL_REPORT_DUE to MATCH.

## New flow

1. Preserve scheduler occurrence identity.
2. Determine PRELIMINARY_REPORT_DUE from schedule-known/static facts and already-known evidence.
3. Run the existing NATURAL_CORE_UPKEEP_GATE unchanged.
4. After the gate terminalizes, evaluate compact freshest-valid scoring-GW lifecycle evidence.
5. FINAL_REPORT_DUE = PRELIMINARY_REPORT_DUE OR SAME_OCCURRENCE_DYNAMIC_TRIGGER.
6. Preserve due monotonicity: false->true allowed, true->false forbidden.
7. Refine mode independently from due stickiness. A pre-live MATCH may become POST_MATCH or POST_ALL_MATCH after fresh completion evidence.
8. Combine overlaps into one visible report.
9. Allow visible silence only when preliminary=false, dynamic=false and final=false after the post-core check.
10. If the dynamic trigger is unresolved, do not fabricate Match and do not silently complete. Continue the existing freshest-valid evidence ladder without a second full-core acquisition.

## Boundaries

- V6 code/config/workflows: unchanged.
- NATURAL_CORE_UPKEEP_GATE acquisition behavior: unchanged.
- Issue #431 transport: unchanged and exactly one current-slot full-core attempt maximum.
- Scheduler cadence/count: unchanged.
- Authority count: unchanged.
- P1.3 event model: untouched by Stage B.
- 20/25/30/25, Gate0, scenario lifecycle, WAIT/PREPARE/ACT: unchanged.
- No Monte Carlo, P1.6, P1.7, package optimizer or mini-league work is introduced.

Natural runtime acceptance remains separate from deterministic/unit CI. A future natural scoring-GW lifecycle transition must still prove the repaired route in production.
