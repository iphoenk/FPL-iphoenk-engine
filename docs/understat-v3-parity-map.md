# V3/V4 Understat intelligence parity map

V3 reuses the `UNDERSTAT_TACTICAL_INTELLIGENCE_V1` normalized intelligence contract from the V4 reference implementation while preserving V3-native execution, governance and serving.

| Intelligence area | V3 implementation |
|---|---|
| Governed source | `src.sources.understat` |
| Normalized team/player evidence | `src.intelligence.understat_tactical` |
| Full Official FPL universe mapping | `src.engines.understat_tactical_context` from `official_snapshot.bootstrap` |
| Rolling 1/3/5/STO + home/away | shared normalized contract |
| Small-sample treatment | shared normalized contract |
| PPDA/deep/xG/xGA | shared normalized contract |
| xG/xA/xGChain/xGBuildup | shared normalized contract |
| Tactical matchup | canonical V3 tactical profiles enriched before prediction |
| V3 decision consumption | existing `src.engines.tactical_decision_consumption` shared governance primitive |
| Source health | `src.sources.understat_artifact` + V3 source layer |
| Runtime cache/publication | V3 runtime publish registry |

There is no Understat-specific lineup/watchlist/report decision consumer. Understat extends the canonical tactical evidence owned by `tactical_context`; prediction and the existing close-call consumers reuse that evidence. This preserves one decision authority and prevents duplicate computation.

Parity target is intelligence parity, not identical final decisions. V3 and V4 retain independent native decision models/optimizers.
