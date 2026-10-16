# Stage 2 — coach, formation, opaque role and availability source admission

Date: 16 October 2026. Code base: production main after merged PR #1130 (frozen prospective GW7 OOS replay). This is an **evidence and provenance gate**, not numeric model calibration.

## Proven original inputs

- Official FPL source owns exactly 667 season players, 20 clubs, and their observed availability status.
- Independently established historical 60/60 FotMob matchDetails, 120/120 original match-specific team coach and formation observations, 1,320/1,320 source-native starter identities. 489/667 global provider identities remain independent and the other 178 players' provider presence is unknown.
- V12's `_manager_role_longitudinal` already builds a source-SHA-bound per-player GW1–GW6 manager/formation/provider-slot ledger, without tactical role semantics, contemporary coach appointment, source-as-of inference, or P(start) effect.
- The merged PR #1130 OOS scorer reads frozen prospective private Git source and separately settled V6 source; GW7 had not settled when this change was written, so no OOS numerical PASS is asserted.

## Added Stage 2 source integrity

`src/models/v12_stage2_context_provenance.py` checks (a) Official player+club uniqueness and exact 667/20 expected identities, (b) longitudinal source authority, GW1–GW6 retrospective scope and null future calibrated fields, (c) player and club identity per hashed source-native observation, unique historical fixture IDs and valid GW bounds, and (d) observed Official status completeness without implying medical clearance. Any mismatch produces `source_integrity_state=PARTIAL` plus non-sensitive reason counts. A clean return means *source evidence is structurally credible*, not that future coach/role/medical probabilities are calibrated.

This aggregate audit is executed inside the already governed `build_retrospective_context` method and emitted under `retrospective_context.stage2_context_source_provenance` in the existing DEEP source evidence. It makes no new V6 fetch, runtime, scheduler, or model parameter write. No 667 player identity is dropped because they lack FotMob appearances.

OOS admission still requires an actual final target GW, original predeadline frozen snapshot, independent settled outcomes and model-vs-baseline paired Brier/xMins MAE improvements. `production_activation_allowed=False` without this; no historical predeadline evidence previously agreed to skip is fabricated. Fifteen regression nodes are added to mandatory governance (56 files, 1479 nodes).

Do not alter immutable GW7, MC500K, P1.7, Stage3, numerical `V12_PLAYER_MINUTES`, public-first auth, PR #809, old receipts or the one-scheduler contract. Merge and exact postmerge runtime must be checked separately.

Change timestamp: `2026-10-16T14:27:08+07:00`
Documentation sync: UPDATED
Documentation timestamp: `2026-10-16T14:27:08+07:00`
