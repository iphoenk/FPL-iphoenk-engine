# V12 Previous-DEEP Baseline Contract

This artifact is a governed presentation/LKG projection of the last fully accepted DEEP occurrence. It does not recompute football mathematics and does not replace the canonical private report bundle.

| Field / surface | Source section | Consumer | Why required | Can heavy internals be omitted? | Provenance requirement |
| --- | --- | --- | --- | --- | --- |
| report_slot, occurrence_id, planning_gw | top-level canonical/serving identity | baseline binding, S03 | prove strictly older occurrence and planning context | No | exact occurrence identity; prior slot must be older than current |
| runner/pre-render/post-render/human statuses | canonical QA | baseline validator | admit only fully accepted prior reports | No | all PASS; delivery READY_FULL |
| canonical_bundle_sha256, canonical_body_sha256 | canonical private report | baseline validator/audit | bind projection to immutable heavy source | No | valid SHA-256 lineage |
| S01 operational_state, decision_dashboard, primary_decision | S01 | Decision Delta | previous action and route | No | canonical presentation copy only |
| S02 player, element_id, P(start), xMins, 1GW, availability, role, price relevance | S02 | Decision Delta player state | compare decision-critical OUR15 state without numeric invention | No | preserve source values exactly; no recomputation |
| S06 XI, bench, formation, captain, vice | S06 | Decision Delta | compare selected lineup state | No | canonical presentation copy |
| S09 chip | S09 | Decision Delta | compare chip state | No | canonical presentation copy |
| S15B rank_battle | S15B | Decision Delta mini-league state | derive prior rank, points, gaps and adjacent rivals with unchanged existing function | No | denominator/rank presentation remains occurrence-bound |
| S17 source_health.finance | S17 | Decision Delta | compare finance availability state | No | canonical presentation copy |
| S19 final_judgement | S19 | Decision Delta/final decision | authoritative prior transfer, route, XI, bench, formation, C/VC | No | must remain consistent with prior S01 |
| all 23 compact presentation sections | S01..S19 | degraded PRIOR fallback / client presentation | preserve truthful historical context when fresh analytics are blocked | Visible fields: No. Internal traces: Yes | presentation_status, authoritative_binding and prior_source_occurrence retained |
| route matrices, MC samples, full-universe traces, raw source payloads, repeated overlays | internal canonical analytics | audit/reproducibility only | not required by client rendering or previous-decision comparison | Yes | retained only in private canonical report_bundle.json |

Governance rules:

- `latest/previous_deep_baseline.json` advances only after a `READY_FULL` DEEP publication with runner, pre-render, post-render and human-facing QA all PASS.
- A degraded occurrence never replaces the LKG baseline.
- A baseline is rejected if its report slot is equal to or newer than the current occurrence.
- The LKG carries all 23 compact presentation sections so degraded rendering can label historical content as PRIOR with its exact source occurrence.
- Decision Delta continues to use the existing `_decision_snapshot_from_report` and `_decision_delta_surface`; the LKG introduces no second history or decision model.
- The production report lane reads `personal/` and `latest/` only. It does not recursively scan or check out `reports/**`.
- Heavy canonical `report_bundle.json` remains in private per-occurrence history for audit/reproducibility.
