# Full-season historical evidence

The V12 historical evidence contract is `OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1`.

For planning GW N, the reconciliation stage covers every historical slot GW1 through GW(N-1) for every player in the current Official FPL bootstrap universe. Each player record preserves the raw fixture-level `element-summary/{element_id}/` rows and exposes an additive aggregate for double gameweeks.

Slot states are explicit:

- `FINAL`: completed fixture evidence is present.
- `DNP`: the player had a completed fixture slot but zero minutes.
- `BLANK`: no player fixture row exists for a completed gameweek.
- `PENDING`: the Official event is not final; it is never converted to zero.

The coverage gate reports expected and available GW slots, expected player slots, missing records, canonical snapshot timestamp, source authority, and whether fallback was used. The retrospective submitted-team proxy remains separate and cannot be used as predictive pre-deadline accuracy.
## Production occurrence binding

For `full_master` report-prefetch occurrences, V6 publishes the occurrence-bound
`data/v6/history/official_detail.json` artifact. It contains the complete
Official FPL `element-summary/{element_id}/` universe and the reconciled
`OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1` coverage gate. V12 accepts this
artifact only when it matches the checked-out runtime occurrence; missing or
partial element summaries remain visible as `PARTIAL`/`UNAVAILABLE` and are
never converted to zeroes.

V12 production acceptance also binds `p_start`, `xmins`, and DNP evidence from
the canonical `V12_PLAYER_MINUTES` output, while S08 consumes the canonical
captain frontier and its distribution/security evidence.


The V6 occurrence artifact is stored as `history/official_detail.json.gz` (lossless gzip-compressed JSON) so the complete official universe remains publishable within repository artifact limits. The V12 runner reads this form transparently.
