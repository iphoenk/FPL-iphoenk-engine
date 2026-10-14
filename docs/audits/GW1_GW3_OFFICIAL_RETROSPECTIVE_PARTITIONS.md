# GW1-GW3 Official FPL retrospective player history

The governed V6 `full_master` prefetch already acquires the complete Official
FPL `element-summary/{id}/` universe and archives it in
`data/v6/history/official_detail.json.gz`. The uncompressed
`official_detail.json` is **only a coverage sidecar** and intentionally has
no `players` property. This is not missing data.

To make completed GW1-GW3 independently inspectable, each next governed
full-master prefetch also publishes:

- `data/v6/history/official_gw_1.json`
- `data/v6/history/official_gw_2.json`
- `data/v6/history/official_gw_3.json`

Each partition holds canonical Official element IDs, teams, positions,
GW-specific FINAL/DNP/BLANK status and untouched fixture-level
`element-summary` facts. Each file binds to the same logical report slot and
prefetch run ID; their coverage is **PASS only** with finalized Official
events, validated fixture IDs and exact expected player count. No blank is
converted to zero, and no dummy player row is inserted.

These are `RETROSPECTIVE_POST_DEADLINE_FACTS` and explicitly
`historical_predeadline_source_asof=NOT_ATTESTED`. They **must not** grant
historical GW1-GW3 walk-forward calibration or natural scheduler acceptance.
Predeadline archival witnesses remain a separate gate requiring genuine
original predeadline source objects.

No new data source, cron, scheduling authority, prediction owner, MC mode, or
non-official numerical context is introduced.
