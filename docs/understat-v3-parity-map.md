# V3/V4 Understat intelligence parity map

V3 reuses the `UNDERSTAT_TACTICAL_INTELLIGENCE_V1` normalized intelligence contract from the V4 reference implementation while preserving V3-native execution, governance and serving.

| Intelligence area | V3 implementation |
|---|---|
| Governed source | `src.sources.understat` |
| Normalized team/player evidence | `src.intelligence.understat_tactical` |
| Full FPL universe mapping | `src.engines.understat_tactical_context` |
| Rolling 1/3/5/STO + home/away | shared normalized contract |
| Small-sample treatment | shared normalized contract |
| PPDA/deep/xG/xGA | shared normalized contract |
| xG/xA/xGChain/xGBuildup | shared normalized contract |
| Tactical matchup | shared normalized contract |
| V3 decision consumption | `src.engines.understat_tactical_consumption` |
| Source health | `src.sources.understat_artifact` + V3 source layer |
| Runtime cache/publication | V3 runtime publish registry |

Parity target is intelligence parity, not identical final decisions. V3 and V4 retain independent native decision models/optimizers.
