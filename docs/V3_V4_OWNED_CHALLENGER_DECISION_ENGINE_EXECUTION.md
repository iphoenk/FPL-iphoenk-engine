# V3 + V4 Owned Challenger Decision Engine execution

This branch implements the V3 side of the governed owned-challenger decision-engine mission while preserving the existing canonical V3 architecture.

## Canonical V3 boundary

V3 already owns the comparator in `src.engines.owned_challenger_comparator` under the reporting/decision pipeline. This work MUST extend that owner and MUST NOT create another microservice, ranking authority, player registry, Official-FPL parser, price predictor, or transfer decision authority.

Required behavior:

- screen all 15 authoritative owned players, never a hardcoded OUT player;
- generate challengers from governed DSS evidence and the canonical 20-player external watchlist;
- rank zero, one, or multiple challenged owned players from evidence;
- retain pairwise evidence rather than hide decisions behind a composite score;
- evaluate HOLD plus legal one/two/multi-transfer packages through the canonical package optimizer;
- retain exact affordability, bank, sell value, max-three-per-club, position, FT/hit and chip/Wildcard constraints;
- treat market timing as timing evidence only, never football-decision authority;
- use the shared Official FPL price predictor contract and preserve current price, ownership, progress, projections, raw likelihood, trajectory, freshness and governed ETA;
- never call predictor threshold crossing a confirmed price change; confirmation requires Official `now_cost` reconciliation;
- render natural Bahasa Indonesia ETA such as `Memungkinkan kenaikan harga besok, 1 September 2026 sekitar pukul 06:00 WIB`, where the clock is derived from the governed Europe/London Official update cycle rather than hardcoded;
- preserve next-match, 3-5GW, 10-15GW, xMins/start security, role, tactical/system interaction, rest/congestion, routes to points, uncertainty, structural impact and reversal conditions;
- weather remains contextual and cannot trigger a transfer alone;
- visible watchlist remains exactly 20 excluding owned, 5 GK / 5 DEF / 5 MID / 5 FWD;
- owned Official FACT completeness must be 15/15 and visible watchlist Official FACT completeness 20/20 before complete USER_REPORT publication;
- `DATA_JOIN_DEFECT` is internal diagnostic state only and must never leak as a normal player-table value;
- if mandatory Official FACT hydration cannot reconcile deterministically, publication fails closed rather than emitting a half-complete table.

## User-report contract

Expose a generated `Main Transfer Battles` section. Names must emerge from current squad plus evidence, never from a player-specific rule. For each material battle expose owned -> challenger, V3 edge, V4 evidence when available through governed cross-engine serving, consensus/disagreement, xMins/start, role, next matchup, 3-5GW, 10-15GW, rest/congestion, Official price, Official ownership, predictor direction/progress/trajectory/ETA, confirmed price-change state, structural impact, risk, confidence, decision and flip conditions.

If no robust legal package beats HOLD after costs and uncertainty, explicitly report `NO TRANSFER RECOMMENDED` and explain why.

## QA/QC acceptance

Do not call this GREEN from unit tests alone. Acceptance requires architecture/no-duplicate guards, all-15 screening, no player-specific OUT hardcode, 20-player watchlist completeness, deterministic pairwise evidence, legal 0/1/2/multi-transfer handling, stale-predictor fail-safe behavior, no one-haul auto-change, weather non-authority, natural price ETA, no XI/C/VC/chip regression, runtime benchmark, fresh governed runtime publication and inspection of the serving artifact.

Audit classification remains: RED correctness/factual-integrity/authority/execution defect; YELLOW design/maintainability/observability/operational risk; GREEN verified and hardened.
