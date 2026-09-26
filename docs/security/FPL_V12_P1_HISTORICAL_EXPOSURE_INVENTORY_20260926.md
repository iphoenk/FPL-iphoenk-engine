# FPL V12 P1-K Historical Exposure Inventory

Date: 2026-09-26
Production main audited: `3d433348a04d8207321bc4521808e253f21ed3fc`
P1 branch: `delivery/private-plane-p1-20260926-r2`

This inventory is evidence only. No artifact, log, cache, issue comment, branch,
or Git history is deleted or rewritten by P1-K.

## Retention authority

The repository-level artifact/log retention settings endpoint is not accessible
through the connected GitHub interface. The production report workflow itself
explicitly sets `retention-days: 14` for V12 report artifacts. Actual artifact
expiry timestamps below were read from GitHub and are therefore authoritative
for those artifacts. Workflow-log retention is not asserted beyond runs that
remain readable through the Actions API.

## Public V12 report artifacts still accessible

The following 25 public full-report artifacts were directly verified as
non-expired on 2026-09-26. These are cleanup candidates only; no deletion is
performed without owner approval.

| Run ID | Artifact ID | Surface | Still accessible? | Expires | Sensitive content | Recommended remediation |
|---:|---:|---|---|---|---|---|
| 35597594711 | 10637725213 | V12 report artifact | YES | 2026-10-05T12:06:38Z | full report / decision bundle | delete after owner approval |
| 35617436772 | 10646830790 | V12 report artifact | YES | 2026-10-05T15:14:22Z | full report / decision bundle | delete after owner approval |
| 35659302333 | 10667445046 | V12 report artifact | YES | 2026-10-05T21:50:17Z | full report / decision bundle | delete after owner approval |
| 35659879299 | 10667026143 | V12 report artifact | YES | 2026-10-05T21:56:15Z | full report / decision bundle | delete after owner approval |
| 35726979028 | 10694479953 | V12 report artifact | YES | 2026-10-06T13:03:21Z | full report / decision bundle | delete after owner approval |
| 35727331458 | 10697330065 | V12 report artifact | YES | 2026-10-06T13:38:27Z | full report / decision bundle | delete after owner approval |
| 35741710555 | 10701047851 | V12 report artifact | YES | 2026-10-06T15:04:04Z | full report / decision bundle | delete after owner approval |
| 35748919665 | 10707090457 | V12 report artifact | YES | 2026-10-06T16:12:40Z | full report / decision bundle | delete after owner approval |
| 35826452958 | 10736708076 | V12 report artifact | YES | 2026-10-07T06:58:25Z | full report / decision bundle | delete after owner approval |
| 35839208204 | 10740899847 | V12 report artifact | YES | 2026-10-07T09:06:54Z | full report / decision bundle | delete after owner approval |
| 35843674793 | 10743800809 | V12 report artifact | YES | 2026-10-07T09:59:42Z | full report / decision bundle | delete after owner approval |
| 35858764611 | 10747734725 | V12 report artifact | YES | 2026-10-07T12:10:11Z | full report / decision bundle | delete after owner approval |
| 35858942122 | 10750288439 | V12 report artifact | YES | 2026-10-07T12:46:28Z | full report / decision bundle | delete after owner approval |
| 35860953431 | 10751248208 | V12 report artifact | YES | 2026-10-07T12:54:37Z | full report / decision bundle | delete after owner approval |
| 35861004775 | 10751578247 | V12 report artifact | YES | 2026-10-07T13:20:11Z | full report / decision bundle | delete after owner approval |
| 35969147317 | 10795700978 | V12 report artifact | YES | 2026-10-08T07:24:08Z | full report / decision bundle | delete after owner approval |
| 36087992514 | 10844533665 | V12 report artifact | YES | 2026-10-09T02:53:30Z | full report / decision bundle | delete after owner approval |
| 36106354250 | 10851381658 | V12 report artifact | YES | 2026-10-09T07:14:17Z | full report / decision bundle | delete after owner approval |
| 36108029034 | 10851877173 | V12 report artifact | YES | 2026-10-09T07:33:14Z | full report / decision bundle | delete after owner approval |
| 36126563940 | 10859578686 | V12 report artifact | YES | 2026-10-09T10:55:32Z | full report / decision bundle | delete after owner approval |
| 36126675342 | 10860321241 | V12 report artifact / regression fixture | YES | 2026-10-09T10:59:36Z | full report / decision bundle | preserve evidence until P1 acceptance; then delete artifact only after owner approval |
| 36230096430 | 10901549255 | V12 report artifact | YES | 2026-10-10T08:33:17Z | full/partial decision output | delete after owner approval |
| 36230353873 | 10902522520 | V12 report artifact | YES | 2026-10-10T08:39:43Z | full/partial decision output | delete after owner approval |
| 36231616445 | 10902651206 | V12 report artifact | YES | 2026-10-10T09:04:47Z | full report / decision bundle | delete after owner approval |
| 36232738219 | 10903396432 | latest semantic-hardened production DEEP artifact | YES | 2026-10-10T09:27:51Z | full report / decision bundle | retain as latest baseline until P1 acceptance; then delete after owner approval |

Seventeen additional V12 completion-run IDs from issue #431 were checked and
currently expose no workflow artifact through the API:
`35589223101`, `35596850907`, `35597371301`, `35616603315`,
`35659673732`, `35693691787`, `35696129665`, `35696754116`,
`35697291246`, `35703070607`, `35709678609`, `35818914006`,
`35819075460`, `35819490932`, `35974262163`, `36087840819`,
and `36107757479`.

## Actions logs

Run `36126675342` and latest production baseline run `36232738219` both
have readable public Actions logs. The latter's run job `108378850663`
contains `STAGE3_ACTION: WAIT` and the public `report_body.md` artifact
path. Therefore logs remain an active historical exposure surface even where an
artifact has expired or is absent.

Recommended remediation: delete affected workflow runs/logs only after owner
approval and only after P1 acceptance evidence is safely retained.

## Actions caches

Latest production run `36232738219` proves all three cache families were
restored from prior main-scope runs and then saved again:

| Cache family | Verified production key prefix | Size observed | Classification | Still recoverable in production run? | Recommended remediation |
|---|---|---:|---|---|---|
| Stage-2 | `v12-stage2-derived-Linux-aafaf...` | ~9 MB | PUBLIC_SAFE | YES | retain |
| P1.7 | `v12-p17-decision-Linux-359fa...` | ~61 KB | PRIVATE_REQUIRED | YES | stop future public restore/save; existing cache deletion requires owner approval |
| MC | `v12-mc-summary-Linux-b21b...` | ~21 KB | PRIVATE_REQUIRED | YES | stop future public restore/save; existing cache deletion requires owner approval |

The connected GitHub interface does not expose an Actions-cache listing/deletion
API, so exact surviving cache object IDs/expiry timestamps are not fabricated.

## Public Git history / runtime-data-v6

| Commit / ref | Surface | Sensitive content | Still accessible? | Recommended remediation |
|---|---|---|---|---|
| `runtime-data-v6@5a8ba71f071d0b0fd62b31ebe549e99a964e756b` | `data/v6/personal/current_team.json` | exact current 15 + auth-capable personal schema | YES | remove from current public HEAD through normal P1 publication boundary |
| `49bda27cdfd54f1910b2c127c101fe4da0d4a332` | historical `current_team.json` | AUTH AVAILABLE, bank=5, 15 players, purchase/selling prices, chip state | YES by direct commit reference | history rewrite only after explicit owner approval |

The historical commit proves that private finance exposure occurred in public
Git history when authentication was healthy. P1 does not rewrite this history.

## Public issue comments

Issue #431 contains historical completion comments with
`action=WAIT/PREPARE/ACT/HOLD` semantics. Recent production runs
`36231616445` and `36232738219` still published `action=WAIT`.

Recommended remediation: historical comment cleanup only after owner approval.
P1 changes future publication to validation-only proof.

## Cleanup candidates awaiting owner approval

1. the 25 verified public V12 report artifacts above;
2. affected workflow runs/logs containing decision material;
3. existing main-scope P1.7 and MC Actions caches;
4. historical issue #431 decision comments;
5. optional public Git-history rewrite for private runtime-data snapshots.

Item 5 is destructive and is explicitly outside automatic P1 execution.
