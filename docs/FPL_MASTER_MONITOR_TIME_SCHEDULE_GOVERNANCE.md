# FPL Master Monitor Time Schedule Governance

**Contract:** `FPL_MASTER_MONITOR_TIME_SCHEDULE_GOVERNANCE_V2`  
**Effective:** 2026-09-27T04:02:05+07:00

This document is the human-readable companion for V12 delivery timing. The machine-readable authority is `config/delivery/v12_delivery_schedule.json`, under `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`. V6 scheduler policy remains separately owned by `config/v6/schedule_policy.json`.

## 1. Authority separation

- `FPL Master Monitor V12` is the sole recurring FPL scheduler.
- Every natural `:30` Asia/Jakarta occurrence owns current-hour V6 core upkeep.
- Core upkeep is normally silent and does not itself authorize a visible report.
- GitHub watchdog is monitoring-only.
- Visible-report timing is V12 downstream policy and never changes V6 acquisition authority.

## 2. Fixed visible reports

| Clock authority | Report |
|---|---|
| 04:30 Asia/Jakarta | DEEP |
| 12:30 Asia/Jakarta | DEEP |
| 21:30 Asia/Jakarta | DEEP |
| 23:30 Europe/London | PRICE |

PRICE is intentionally London-local. It appears at 05:30 WIB while London is on BST and 06:30 WIB while London is on GMT. DST must not produce a duplicate or missed PRICE report.

## 3. Quiet hours

Quiet window is strictly after 21:30 through before 04:30 Asia/Jakarta.

Extra visible notifications are suppressed during this window except:
- an explicit owner ADHOC request;
- the deadline window from T-3 hours through lock.

The fixed 21:30 and 04:30 DEEP reports remain visible.

Live MATCH and POST_MATCH work may continue silently during quiet hours and feed the next permitted visible report.

## 4. Deadline checkpoints

All checkpoints derive from the current Official FPL deadline.

| Checkpoint | Contract |
|---|---|
| T-24h | DEEP |
| T-12h | DEEP |
| T-6h | DEEP |
| T-3h | DEEP, opens warm deadline window |
| T-2h | delta-first |
| T-1h | delta-first + execution card |
| T-30m | FINAL REVIEW |
| T-15m | GO/NO-GO |
| T-5m | FINAL CONFIRMATION |

Deadline proximity does **not** create visible hourly reports between these checkpoints.

T-2 through T-5 reuse existing canonical S01/S03/S18/S19 ownership plus the execution card; they do not introduce S22/S23 or another report schema.

## 5. Collision/overlap

One instant may carry several obligations. The system emits one coherent visible report only.

Examples:
- DEEP + MATCH → one DEEP+MATCH report;
- deadline checkpoint + MATCH → one deadline-rich report with Match obligation;
- PRICE + deadline → one coherent report carrying both obligations.

No duplicate visible publication is permitted for the same resolved instant.

## 6. Precompute

Scheduled visible reports begin precompute approximately T-15 minutes with target freeze readiness by T-10 minutes. Final data validation/freeze/publication remains bound to the visible slot.

Precompute does not alter scheduler authority and does not count as a natural core slot.

## 7. Warm latency

The ≤15 s delivery target applies only to an already-running P6 warm worker.

T0 = material change/owner command has been received or detected by the warm worker.  
T1 = canonical recompute/render/private publish is validated and consumable.

GitHub queue, runner provisioning, dependency installation and initial bootstrap are explicitly outside this warm metric.

## 8. Acceptance

D0-D5 schedule acceptance requires:
- fixed DEEP slots;
- London-local PRICE with DST tests around 24/25/26 October 2026;
- exactly one PRICE publication per London date;
- nine exact deadline checkpoints;
- quiet-hours behavior;
- one-report overlap;
- precompute T-15/T-10;
- V6 core `:30` authority unchanged;
- no second scheduler.
