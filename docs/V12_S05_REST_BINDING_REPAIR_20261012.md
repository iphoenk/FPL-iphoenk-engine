# V12 S05 rest binding repair

Change timestamp: 2026-10-12T15:12:00+07:00  
Documentation sync: UPDATED  
Documentation timestamp: 2026-10-12T15:12:00+07:00

The S05 fixture display adapter previously consumed only the optional
per-fixture projection field `rest_from_previous_fixture_hours`. Production
workload context already contained verified `days_rest`, so the report was
truthful at the workload layer but lost the value at the visible fixture row.

The repair binds, in order:

1. the optional per-fixture workload interval;
2. the workload row's exact next-planning-fixture `days_rest`;
3. the interval derived from Official FPL fixture kickoff ordering.

This is presentation/context binding only. It does not alter xPts, P(start),
xMins, or apply a fatigue penalty. The regression covers the production-shaped
Official FPL fixture ordering fallback.
