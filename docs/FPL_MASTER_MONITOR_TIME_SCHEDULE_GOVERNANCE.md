# FPL Master Monitor Time Schedule Governance

Contract: `FPL_MASTER_MONITOR_TIME_SCHEDULE_GOVERNANCE_V1`

Operational timezone authority: **Asia/Jakarta (WIB / UTC+7)**.

This document is the human-readable companion to `config/runtime/collector_policy.json`. Machine behavior is enforced by `src/engines/collector_gate.py` and workflow schedules.

## 1. Master hourly evaluation

The engine performs an internal evaluation every hour at minute `:30` WIB. An internal evaluation does not automatically authorize a visible user report.

Visible output is authorized only for a governed mode: Normal scheduled report, Deadline Day Mode, Match Mode, Critical Price Alert, or Permitted Emergency. Otherwise the engine evaluates internally and remains silent.

## 2. Normal daily schedule

- **04:30 WIB, Daily Deep Review.** Primary payload: `data/deep_review_payload.json`. Full 15 OWNED + 20 governed external WATCHLIST review, 3-5 GW primary horizon, supported 10-15 GW strategic outlook, fixture-by-fixture tactical opponent analysis, rest/congestion, domestic/European/international workload, xPts/xMins/start security, XI, bench, C/VC, chip, transfer/challenger, price/value, model validation and source health.
- **12:30 WIB, Midday Tactical Monitor.** Primary payload: `data/decision_brief.json`. Fresh injury/team news, training/press conference, tactical matchup, xMins/start security, transfer/watchlist/challenger, fixture/rest/congestion, C/VC, price radar and material consensus/divergence. The governed 15 + 20 contract remains in force.
- **21:30 WIB, Night Tactical + Price Monitor.** Primary payload: `data/decision_brief.json`. Final normal football review, price-change risk, late team/tactical information, transfer pressure, watchlist/challenger changes, workload, next-day risk, C/VC and squad structure. Price Radar is mandatory.

Other `:30` checkpoints are internal-only and silent unless another visible mode is active.

## 3. Deadline Day Mode

Deadline Day Mode begins exactly **24 hours before the Official FPL deadline**. The Official FPL deadline is Tier-1 authority.

From the first `:30 WIB` checkpoint inside T-24h through the official deadline, emit a **full visible Deadline Day report every hour**. Do not suppress a report because nothing changed. When appropriate state:

`NO MATERIAL CHANGE SINCE PREVIOUS CHECKPOINT`

and still produce the complete governed report.

## 4. Deadline Day fresh-data requirement

Before every visible Deadline Day report, perform a fresh source sweep. Do not merely reuse the previous report.

Where accessible and relevant, classify named sources as `AVAILABLE`, `PARTIAL`, `STALE`, `UNAVAILABLE`, or `NO MATERIAL UPDATE`. Never fabricate a source finding.

Source priority:

1. Official FPL native/direct endpoints, Official FPL website, Premier League official, official clubs, official manager/team communications.
2. Reliable beat reporters, verified press-conference reporting, reliable injury/lineup reporters.
3. FPL Live / LiveFPL, OneFPL, FFFix, FFHub, FFScout.
4. Ben Crellin for fixture/chip/BGW/DGW/rearrangement context.
5. X/Twitter and Reddit as lower-authority signal sources requiring cross-checking.

## 5. Direct Official refresh near deadline

Runtime data remains the production bridge. During Deadline Day, when runtime bridge age exceeds **30 minutes**, refresh direct Official FPL native data.

Also refresh direct Official data when a material native factual state may have changed, including injury/news, player status, price, deadline/GW state, fixtures, event state and submitted/public picks where available.

If runtime and direct Official disagree on native factual fields, **Direct Official FPL wins** and the divergence must be recorded.

## 6. Final Review

Final Review is an intensified checkpoint inside Deadline Day Mode, not a terminating mode.

- If the official deadline is between **00:00 and 01:59 WIB**, Final Review is **T-3 hours**.
- Otherwise Final Review is **T-1.5 hours**.

Final Review intensifies latest user/submitted baseline, legality, injury, xMins, starting probability, lineup leaks, tactical matchup, congestion, C/VC, XI, bench order, chip, affordability, price, transfer/watchlist comparison, source divergence and emergency risks.

Hourly Deadline Day reports continue at `:30` after Final Review until the official deadline.

## 7. Deadline pass and post-deadline reconciliation

At the official deadline, Deadline Day Mode ends and system state transitions to `POST_DEADLINE_RECONCILIATION`.

Priority:

1. Fetch Official FPL submitted picks when available.
2. Compare final user-side pre-deadline baseline with submitted picks.
3. Reconcile 15-player squad, Starting XI, bench, C, VC and chip.
4. Submitted Official picks become authoritative fact.
5. Never infer submitted C/VC/XI while Official data is unavailable.
6. Never mutate historical submitted Gameweek state.

Once reconciliation completes, current Gameweek submitted state is canonical.

## 8. Match Mode

Match Mode applies only after the Gameweek is active.

At every hourly `:30` checkpoint, check whether at least one Premier League fixture belonging to the **current scoring Gameweek** is officially live.

A fixture qualifies only when its Official state is `started=true`, `finished=false`, and its `event` equals the current `scoring_gw`.

If at least one qualifies, emit **one consolidated Match Mode report**. If none qualifies, emit no Match Mode report. Multiple simultaneous live matches remain one consolidated report.

A kickoff-time proximity window is not sufficient to activate Match Mode.

## 9. Match Mode priorities

Prioritize personalized live points, OWNED players currently playing, C/VC, goals, assists, clean sheets, cards, Bonus/BPS, DefCon where relevant, minutes, starter/substitution/DNP state, autosub implications, captaincy transfer implications, injuries, tactical role observations, material WATCHLIST performances, `EMERGING_CHALLENGER` triggers and next-GW implications.

Always separate **FACT LIVE EVENT** from **MODEL / TACTICAL INTERPRETATION**. Never create a BUY/SELL recommendation purely from one live haul.

## 10. Emerging Challenger

A non-owned player can trigger `EMERGING_CHALLENGER` through a brace, goal + assist, major xG/xA performance, meaningful role/start-security change, advanced positioning, set-piece/penalty evidence, strong box involvement or material xMins improvement.

This is discovery only. It does not automatically become BUY, TRANSFER, or WATCHLIST PROMOTION.

After the match, run the generic OWNED-vs-CHALLENGER comparator over Next GW, 2 GW, 3 GW and 5 GW horizons.

## 11. Collision and mode priority

Never produce duplicate reports at one checkpoint. Priority is:

1. `DEADLINE_DAY_FINAL_REVIEW`
2. `DEADLINE_DAY`
3. `MATCH_MODE`
4. `NORMAL_DEEP_REVIEW`
5. `NORMAL_MIDDAY`
6. `NORMAL_NIGHT`
7. `CRITICAL_PRICE_ALERT`
8. `PERMITTED_EMERGENCY`

Material information from lower-priority modes must be folded into the single higher-priority report.

Example: 21:30 simultaneously Deadline Day + Final Review + Night Monitor produces one full Deadline Day Final Review. 21:30 with a live current-GW match and Night Monitor produces one Match Mode report with Night Tactical content folded in.

## 12. Price monitoring

Price Radar is mandatory in 04:30 Deep Review, 12:30 Midday, 21:30 Night, every Deadline Day hourly report, and Final Review.

Confirmed Official price changes are FACT. Predicted direction, threshold and ETA are MODEL / PREDICTION and must not be presented as fact.

## 13. Critical price alert exception

Outside normal visible schedule, an immediate visible alert is permitted only when price movement becomes genuinely actionable, such as affordability destruction, material sell-value impact, planned transfer becoming impossible, multi-player structure becoming invalid, or deadline proximity making delay materially harmful.

Do not emit routine non-actionable price noise.

## 14. Domestic, European and international workload

Continuously ingest relevant scheduling and workload changes across Premier League, Champions League, Europa League, Conference League, Carabao Cup, FA Cup, international fixtures and other relevant competitive matches.

Capture match date, kickoff, location, travel, actual minutes, started/benched, substitution minute, extra time and days of rest before the next PL fixture. Feed this into xMins, rotation risk, tactical comparison, OWNED-vs-WATCHLIST, OWNED-vs-EMERGING_CHALLENGER, captaincy, XI and bench order.

## 15. Player comparator timing

Re-evaluate the generic OWNED-vs-CHALLENGER comparator on new WATCHLIST publication, material live performance, xMins or start-security change, injury, suspension, role or manager tactical change, Europe/cup confirmation, international call-up/minutes, price change, fixture rearrangement, owned-player deterioration, challenger improvement, every 04:30 Deep Review and every Deadline Day checkpoint.

Required horizons: Next GW, Next 2 GW, Next 3 GW, Next 5 GW. Add 10-15 GW strategic context where evidence is reliable enough.

## 16. Visible schedule summary

Normal day:

- 04:30, full Deep Review.
- 12:30, Midday Tactical Monitor.
- 21:30, Night Tactical + Price Monitor.
- Other `:30`, internal-only/silent.

Deadline Day:

- Every `:30` inside T-24h through deadline, full Deadline Day report.
- Final Review T-3h for 00:00-01:59 WIB deadlines, otherwise T-1.5h.
- Hourly reporting continues after Final Review.

Active Gameweek:

- Every `:30` with at least one officially live current-GW PL fixture, Match Mode.
- No live current-GW fixture, no Match Mode.

## 17. Master scheduling rule

Every hour at `:30`:

1. Evaluate current FPL phase.
2. Validate Official deadline/event state.
3. Refresh runtime state.
4. Determine active operating mode.
5. Check live-match state.
6. Check source freshness.
7. Check squad/decision changes.
8. Check challenger triggers.
9. Check price urgency.
10. Decide whether visible output is authorized.

Never send a routine visible report merely because the hourly engine ran. Never skip an hourly visible report during Deadline Day Mode. Never send Match Mode when no current-GW Premier League match is live. Never duplicate reports on mode collision. All scheduling uses WIB / Asia/Jakarta.
