# Official FPL GW1–GW6 retrospective history: production recovery

Scope: post-deadline factual history, not original pre-deadline inputs or archived forecasts.

The canonical V6 `full_master` report-prefetch collects Official FPL `element-summary/{element_id}/` for the full player universe, validates Official fixture IDs and event finalization, and publishes the raw lossless `data/v6/history/official_detail.json.gz`. The sidecar `data/v6/history/official_detail.json` carries coverage metadata, not raw `players`. Absence of `players` in the sidecar does not imply historical player data are missing.

To make individual completed gameweeks inspectable, the SAME governed V6 occurrence produces:

| GW | Output |
| --- | --- |
| GW1 | `data/v6/history/official_gw_1.json` |
| GW2 | `data/v6/history/official_gw_2.json` |
| GW3 | `data/v6/history/official_gw_3.json` |
| GW4 | `data/v6/history/official_gw_4.json` |
| GW5 | `data/v6/history/official_gw_5.json` |
| GW6 | `data/v6/history/official_gw_6.json` |

Each GW file contains Official element ID, club, position, observed fixture-level player rows, per-GW Official numeric aggregate, match count and truth-preserving `FINAL`, `DNP` or `BLANK` classification. Coverage reports expected/current player counts, number of observed fixture rows, status distribution, finalized Official GW and fixture identity gate. The publication receipt includes the exact report-prefetch run ID and logical report slot. Future, unfinished, missing-player or identity-invalid GW partitions must not claim PASS.

Existing index field `retrospective_gw_1_3` remains backward compatible for GW1–GW3, while `retrospective_gw_1_6` is the full completed-six-GW index. All six files are written only by the existing V6 full-master report-prefetch and published through its normal artifact manifest; no additional recurring scheduler or competing factual owner is added.

The current public runtime V6 sidecar was read on 15 Oct 2026 and showed `expected_players=667`, `covered_players=667`, `available_gw_slots=4002`, six finalized GWs, 380 Official fixture catalog rows, 3,883 verified player-fixture rows, zero fixture-identity anomalies and `coverage_gate.status=PASS`. Note that the 4,002 player-GW slots include genuine DNP/BLANK states, **not** 4,002 confirmed player appearances.

These are `RETROSPECTIVE_POST_DEADLINE_FACTS`; `historical_predeadline_source_asof=NOT_ATTESTED` is unchanged. Historical P(start) walk-forward source-as-of, manager/role context, forecast calibration, natural scheduler proofs, and GW7 immutable forecasts are separate. Production acceptance requires a new actual `full_master` run on merged production main, remote artifact readback, SHA256 receipt and GW1–GW6 per-partition PASS, not simply this code change.
