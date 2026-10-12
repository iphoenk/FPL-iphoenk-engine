# S15 cross-section evidence quality

Change timestamp: 2026-10-12T15:40:00+07:00

S15 now receives the exact S02 full-season and P(start) acceptance state before rendering. A current model snapshot remains usable, but it is marked Partial when the exact occurrence-bound history or minutes evidence is unavailable/limited. This prevents S15 from claiming HIGH evidence confidence while S02 is explicitly unavailable.

The locked S15 table schema is unchanged.