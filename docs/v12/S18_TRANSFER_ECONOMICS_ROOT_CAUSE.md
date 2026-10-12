# S18 Transfer Economics Root Cause

## Failure

The 16:32 controlled DEEP occurrence could expose legacy `economics_status` and
`bank_after`, but did not expose one canonical execution-economics object. Hit,
free-transfer consumption, affordability, and horizon net deltas therefore
became unavailable or non-executable downstream.

## Producer repair

P1.2B now emits `transfer_economics` for every route with the canonical
`status`, `transfer_count`, `ft_consumed`, `hit_points`, `bank_after`,
`affordable`, and `executable` fields. The rule engine remains the only source
of hit points. Missing authenticated sell value or unresolved economics keeps
the object `PARTIAL` and `executable=false`.

Unresolved horizons remain `None`; they are never represented as numeric zero.
S18 consumes this object for integrity and execution display, while HOLD stays
valid without transfer economics.

## Scope guard

This change does not alter MC500K, P1.7, route-universe search, or WatchlistScore
weights.
