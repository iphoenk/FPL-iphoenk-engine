# FPL V12 P1-A Public Exposure Audit

Date: 2026-09-26
Production authority: `f1402818519237d3628184e298bd58c0240983bb`
Audit branch: `delivery/private-plane-p1-20260926`
Scope: PUBLIC GIT / Actions artifacts / Actions logs / Actions caches / issues-comments-workflow summaries.

This document records evidence before any functional P1 privacy patch. It does not change V12 mathematics, V6 factual methodology, section IDs, S03 semantics, Stage3 semantics, or decision computation.

## Classification used during audit

- `PUBLIC_FACT`: unauthenticated facts reproducible by the public at the same effective time.
- `PUBLIC_OPERATIONAL_PROOF`: allowlisted non-decision execution metadata.
- `PRIVATE_PERSONAL`: current authenticated/manual team state, finance, pending state, auth/session metadata, or private personal inputs.
- `PRIVATE_DECISION`: route/action/XI/bench/C/VC/chip/staging/scenario/decision render.
- `SECRET`: token, cookie, password, auth header, credential material.

## P1-A evidence table

| Surface | Path / run / cache | Observed content | Sensitive? | Reason | Required action |
|---|---|---|---|---|---|
| PUBLIC GIT | `main:control/fpl_master_v12/FPL_MASTER_STATE_V12.json` | explicit user-confirmed current squad identity plus active scenario/execution state; decision-learning records include route/bench-related fields | YES, `PRIVATE_PERSONAL` + `PRIVATE_DECISION` | main itself contains personal team identity and scenario/decision state, independent of runtime-data-v6 | split persistent model/governance state from private owner state; private overlay reader; keep only non-personal methodology/calibration metadata public |\n| PUBLIC GIT | `runtime-data-v6:data/v6/personal/current_team.json` current HEAD | exact 15-player team, starter/bench state, C/VC, current prices, entry/auth state; finance schema present | YES, `PRIVATE_PERSONAL` | current-team identity and authenticated-capable finance state are personal; current file remains able to carry finance when auth returns | split public submitted facts from private current-team state; private reader + migration; remove private current-team fields from public HEAD after identity proof |
| PUBLIC GIT | historical runtime-data commit `49bda27cdfd54f1910b2c127c101fe4da0d4a332` | authenticated current-team snapshot had non-null bank, purchase price, selling price, chips plus exact 15/C/VC | YES, historical `PRIVATE_PERSONAL` | proves exposure was real, not just schema potential | inventory under P1-K; no history rewrite without owner approval |
| PUBLIC GIT | `runtime-data-v6:data/v6/personal/submitted_picks.json` | submitted picks, bench order, C/VC, active-chip field, entry/gw lineage | CONDITIONAL | post-deadline submitted picks can be `PUBLIC_FACT`; pre-disclosure/current authenticated state cannot | add disclosure/timing contract; never use it as transit for manual/current private state |
| PUBLIC GIT | `runtime-data-v6:data/v6/personal/memberships.json` | entry-linked league memberships/ranks/admin metadata and lineage | YES, `PRIVATE_PERSONAL` | entry-linked personal membership state is not required as public factual plane | move personal membership state to private plane; retain only public league facts needed by model where independently reproducible |
| PUBLIC GIT | `runtime-data-v6:data/v6/report_prefetch/latest.json` and `health/report_prefetch.json` | auth state/actions, entry/personal status and personal-prefetch provenance | YES in part, `PRIVATE_PERSONAL` | auth/session/personal state is explicitly private in P1 contract | sanitize public health proof; move auth-personal fields private |
| ACTIONS ARTIFACT | run `36126675342`, artifact `v12-report-DEEP-36126675342`, artifact id `10860321241` | `report_bundle.json` ~40.2 MB, `report_body.md` ~0.84 MB, `execution_proof.json`, `stage3_acceptance.json`, runtime proof | YES, `PRIVATE_DECISION` | bundle/body contain full decision render; proof schemas carry Stage3 decision action | stop public full-report upload; private publish canonical outputs; public safe-proof artifact only |
| ACTIONS ARTIFACT | COLD profile paths in `v12-integrated-report-runner.yml` | `profile_run.log`, profile summaries/pstats are eligible for public upload | SENSITIVE UNTIL GUARDED | combined stdout/stderr can contain decision material through future/debug output | keep profiling proof allowlisted/sanitized only; no raw combined log in public artifact |
| ACTIONS LOG | run `36126675342`, job `108044301506` | actual public log includes resolved environment value `STAGE3_ACTION` | YES, `PRIVATE_DECISION` | actual decision enum is visible in Actions log | remove decision from step outputs/env; validate actual log with no-leak guard |
| ACTIONS LOG | same job | checkout extraheader shows Authorization field with GitHub masking | SECRET SURFACE, currently masked | a secret-bearing command surface exists even though value is masked | retain GitHub masking; guard for raw auth/token/cookie leakage; never echo private publisher token |
| ACTIONS CACHE | `.cache/v12-stage2` / `v12-stage2-derived-...` | deterministic full-universe projections; key and payload exclude private current15 by implementation contract | NO decision state proven; `PUBLIC_FACT/MODEL` derived | source explicitly fingerprints public/model deterministic inputs and stores projections only | `PUBLIC_SAFE`; retain for performance, guarded by manifest/tests |
| ACTIONS CACHE | `.cache/v12-p17` / `v12-p17-decision-...` | pickled exact decision core including selected route, exact XI identity, bench winner, C/VC winner, alternatives | YES, `PRIVATE_DECISION` | cache payload is decision material | `PRIVATE_REQUIRED`; remove from public Actions cache path; protect/recompute/private-store with measured impact |
| ACTIONS CACHE | `.cache/v12-mc` / `v12-mc-summary-...` | key binds exact route signatures and selected route; MC validates XI/bench/C/VC and caches route-linked summary | YES, `PRIVATE_DECISION` | route-linked cache is decision-sensitive even when payload is a summary | `PRIVATE_REQUIRED`; do not expose via public Actions cache; protect/recompute/private-store with measured impact |
| ISSUES / COMMENTS | public issue #431, multiple V12 completion comments including run `36126675342` | completion proof publishes Stage3 action | YES, `PRIVATE_DECISION` | WAIT/PREPARE/ACT/HOLD is decision intelligence | publish only `stage3_validation=PASS|FAIL`; no action/route/decision |
| ISSUES / COMMENTS | public issue #431 historical V6 acceptance comments | mentions authenticated finance/auth availability and personal snapshot facts | YES, historical `PRIVATE_PERSONAL` metadata | historical comments confirm personal-data exposure beyond artifacts | P1-K inventory; cleanup only after owner approval |
| WORKFLOW TRIGGER | `.github/workflows/v12-integrated-report-runner.yml` | `workflow_dispatch` and owner-gated `issue_comment`; no `pull_request_target` in this workflow | target workflow currently safe from PR-target secret model | owner gate limits commenter-controlled execution; however repo-wide trigger inventory still must be mechanically proven | add repo-wide workflow trigger regression guard before functional cache/publisher change |
| WORKFLOW TRIGGER | `.github/workflows/v6-natural-data-ingestion.yml` | `workflow_dispatch` + governed `issue_comment`; publishes `runtime-data-v6` | personal-state producer is public-plane publisher | producer currently writes `personal/current_team.json`, memberships and submitted picks into public runtime tree | split public factual publication from private personal-state publication |

## P1-A1 artifact conclusion

Confirmed public sensitive artifact exposure. Run 36126675342 remains a regression fixture. Public artifact retention for that run is 14 days and the artifact was still accessible during this audit.

## P1-A2 log conclusion

The baseline validation run has at least one actual decision leak in the public Actions log. Source-only logger review is therefore insufficient. P1-G must scan downloaded job logs from acceptance runs.

## P1-A3 public data branch conclusion

The public branch mixes factual data and personal state. Historical evidence proves authenticated finance was published when credentials were healthy. The migration must be field/dependency aware; public submitted picks may remain only after public disclosure and only as reproducible facts.

## P1-A4 cache conclusion

| Cache | Classification | Evidence-based result |
|---|---|---|
| Stage-2 derived projections | `PUBLIC_SAFE` | public/model-only deterministic projection payload |
| P1.7 decision core | `PRIVATE_REQUIRED` | exact selected XI/bench/C/VC/alternative material stored in pickle |
| MC simulation summary | `PRIVATE_REQUIRED` | cache lineage contains exact route signature + selected route and route-linked output |

The baseline DEEP occurrence spent about 48.94 s in Stage-2 on a miss, 18.23 s in package utility, 5.31 s in funded package utility, and 34.15 s in MC. Cache hardening must therefore measure performance instead of deleting all caches indiscriminately.

## P1-A5 PR / fork security status

- Target report workflow: no `pull_request_target`; owner-gated `issue_comment`; checks out production `main`.
- Target V6 ingestion workflow: governed dispatch/comment triggers in inspected source.
- Repository-wide absence of `pull_request_target` is an explicit acceptance condition and will be proven by a whole-tree regression test on this branch. Connector source browsing cannot enumerate the workflow directory, so a negative repository-wide claim is not made from partial evidence.
- No repository/account security setting is changed by this branch without owner approval.

## P1-A6 issue/comment conclusion

Public proof currently publishes decision action. This is a confirmed leak. P1 public proof will use an allowlist and retain only validation status.

## Non-destructive historical handling

No artifact, log, cache, comment, branch history, or Git history was deleted or rewritten during this audit. P1-K will produce cleanup candidates and wait for owner approval.
