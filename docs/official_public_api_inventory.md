# Official FPL public JSON inventory for V6 / V12 MATCH

Audit date: 2026-10-10 (Asia/Jakarta).
Authority: `https://fantasy.premierleague.com/api/`.
This inventory distinguishes **implemented** transport from **actually proven in the
latest production occurrence**. An implemented method is not evidence of HTTP 200.
The production report must use its per-endpoint `http_status`, `checked_at`,
payload digest and source lineage, never the table below, for GREEN decisions.

| Route | Authorization | Expected schema / pagination | V6 acquisition | MATCH consumption | Recovery and truth |
| --- | --- | --- | --- | --- | --- |
| `bootstrap-static/` | Public | `events[]`, `elements[]`, `teams[]`, `element_types[]` | `OfficialFPLClient.bootstrap`; current GW from official event selection | Full player name/team/position dictionary and bonus lifecycle metadata | Fail closed if no verified current or trusted prior bootstrap |
| `fixtures/` | Public | Array of fixture objects | Public client route available; legacy Official snapshot | Full fixture and lifecycle | No HTML scrape; retain stale/source status |
| `fixtures/?event={gw}` | Public | GW-specific fixture array, score, kickoff, `started`, `finished` | MATCH prefetch refresh, raw versioned artifact | MATCH1, DNP, match score/fixture lifecycle | Evidence must be fresh for exact MATCH slot; no GREEN on stale legacy fallback |
| `event/{gw}/live/` | Public | `elements[]` with `id`, `stats`, `explain` | Report prefetch live acquisition; complete raw player stats retained | MATCH3, MATCH6, MATCH7, ownership/EO scoring | Null player points not converted into verified zero |
| `event-status/` | Public | `status[]`, bonus `bonus_added`, `leagues` where present | MATCH prefetch raw snapshot, legacy Official snapshot | Provisional/final bonus and score lifecycle | `finished_provisional` alone is not finalization |
| `entry/{id}/` | Public | Identity, team name and published performance | Report prefetch membership/identity route | Our team and priority league selection | Auth-independent |
| `entry/{id}/event/{gw}/picks/` | Public after deadline | 15 `picks[]`; `entry_history`, `automatic_subs`, `active_chip` | Full league pagination -> per-entry MATCH refresh -> raw and normalized scoring evidence | Locked XI, captain, vice, hits, autosub, gross/net and EO | Incomplete 58/58 triggers explicit degraded status. Past cached XI not acceptable as fresh scoring data |
| `entry/{id}/history/` | Public | `current[]`, `past[]`, chips and transfer history | Client method available, **not yet required by MATCH prefetch** | Optional baseline/tie-break corroboration; not full adopted | Do not assert verified transfer-count tie-break without this evidence |
| `entry/{id}/transfers/` | Public post-publication | Published transfer array | Client method available, **not yet required by MATCH prefetch** | Optional historical comparison | Never substitute for private pending transfers |
| `leagues-classic/{id}/standings/?page_standings=N` | Public | `standings.results[]`, `standings.has_next` | Full pagination up to terminator; manager ID coverage verified | Published standings vs provisional calculated live rank | Do not claim static rank is live |
| `element-summary/{id}/` | Public | Player GW history and future fixtures | Client method available; existing player-detail enrichment may also use legacy route | Supplemental statistics only | Fail softly, never block MATCH on nonessential player details |
| `team/set-piece-notes/` | Public | Official set-piece notes | Existing source method | Optional explanatory context | Advisory; not scoring authority |
| `me/`, `my-team/{id}/` | **Private auth** | Identity and pre-deadline private squad/finance | Explicit authenticated allowlist | **Not required for public MATCH** | 401 must not suppress public acquisition or MATCH delivery |

Additional candidate endpoints from third-party/community listings (e.g. dream-team,
cup-status, special rankings) are **NOT APPROVED** for production until their real
HTTP response and schema are checked. Do not infer API existence from documentation.

## Scoring controls

- Official submitted `position`, `multiplier`, `is_captain` and
  `is_vice_captain` are the locked team authority; a planning XI is not.
- Preserve `entry_history.event_transfers_cost` as a nullable public field;
  `hit = 0` is valid only when Official actually reports zero.
- Official `automatic_subs` is authoritative. Avoid applying a transfer twice
  when Official multipliers already reflect it. Unsettled DNP/vice activation
  remains provisional and must be identified.
- Previous total can be derived from the GW-scoped Official `entry_history`
  (total - GW points) or published classic standings (total - GW points),
  with provenance and provisional caveat.
- `net_gw = gross_gw - official_hit`; `live_overall =
  previous_overall + net_gw` only when both terms have sufficient evidence.
- Official Classic League ties are resolved by fewest eligible transfers
  (Wildcard/Free Hit transfers excluded). If season transfer-count evidence
  was not fetched, show tied positions as **provisional**, not a fabricated
  ordering.
- EW/EO across the league uses **all submitted multipliers** / manager count
  and may legitimately exceed 100%.
- A producer can be `READY_DEGRADED` while preserving 13 visible sections.
  `READY_FULL` requires current Official fixture/status evidence, all
  manager inputs and authoritative hit/baseline handling.
- Do not equate PR/CI success with private publication, receipt, latest
  pointer, or visible user delivery.

## Runtime HTTP verification record

The checked-in inventory is a contract, not a live probe result. The exact
production prefetch lineage must record each endpoint's HTTP status and schema
for the relevant logical slot. At the time this inventory was written, no
fresh controlled MATCH run on the new PR head had been published; therefore
**HTTP 200, latest 58/58 verified net scores, receipt and FULL GREEN remain
unconfirmed**.

Known prior production reference: `MATCH|2026-10-10T21:48:00+07:00`,
`READY_DEGRADED`, root cause
`HITS_AUTOSUB_LIVE_RANK_UNVERIFIED`. This is a baseline observation, not an
acceptance result for these changes.
