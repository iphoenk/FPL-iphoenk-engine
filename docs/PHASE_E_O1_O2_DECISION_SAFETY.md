# Phase E (limited): O2 decision safety gate and O1 point-in-time CURRENT15 resolution

Status: implemented on a PR branch, not merged, not deployed. Owner approval is required for merge.

## O2 decision safety gate (src/engines/v12_decision_safety_gate.py)
- A Captain LOCK or an executable XI requires resolution_status CURRENT_VALID for the planning GW.
- Otherwise the state is clamped to the existing statuses: PREPARE (OUR15 present but not proven current), WAIT (OUR15 unavailable).
- Critical evidence (V6_PUBLISH_INTEGRITY, OFFICIAL_TEAM_IDENTITY) not in a passing state also blocks LOCK; non-critical evidence never lowers a decision.
- An authenticated snapshot older than 15 minutes before the source cutoff whose transfer gap was not verified (no public transfer feed) is not executable (OUR15_TRANSFER_GAP_UNCHECKED).
- Reason codes are traceable in dashboard CURRENT_BLOCKERS and DECISION_SAFETY_GATE; deep delivery validation adds O2_EXECUTABLE_DECISION_WITHOUT_CURRENT_OUR15.

## O1 point-in-time CURRENT15 (src/engines/v12_current15_resolution.py)
- Cutoff is the Official payload checked_at; evidence timestamped after the cutoff is rejected. The legacy report_slot+15min guard is kept only when no cutoff exists.
- A checked_at that is present but unparseable or timezone-naive fails closed. An absent checked_at keeps the legacy path (residual risk, see below).
- Bounded read of personal/snapshots (96h lookback, 64 files, filename and generated_at must agree).
- PUBLIC_INFERRED reconstruction from previous-GW Official picks plus public transfers, fail-closed, no private finance. It is not executable-grade.

## Known limits and owner decisions
- No producer writes the public transfers feed (entry_transfers.json); reconstruction and the gap check are inactive in production until one exists.
- The same-occurrence snapshot is written after checked_at, so it is treated as future evidence; most reports will degrade to PREPARE until the owner decides the cutoff timing.
- Stage3 requires source_class OFFICIAL_SUBMITTED_PICKS for degraded S02, so a PUBLIC_INFERRED report may fail Stage3. Stage3 was not loosened.
- Absent checked_at is not fail-closed.
