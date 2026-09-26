# FPL V12 P1-A Public Exposure Audit

Date: 2026-09-26
Initial production authority: `f1402818519237d3628184e298bd58c0240983bb`
Latest production authority re-audited: `3d433348a04d8207321bc4521808e253f21ed3fc`
Audit / implementation branch: `delivery/private-plane-p1-20260926-r2`
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
| PUBLIC GIT | `runtime-data-v6:data/v6/personal/memberships.json` | league membership / priority-resolution facts produced from the unauthenticated Official FPL `entry` endpoint | NO for reproducible fields, `PUBLIC_FACT` | P1 classification is field/source based: these values are publicly reproducible at the same effective time and are not pending/current private decisions | retain public; do not mix future manual/auth-only metadata into this artifact |
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
- Repository-wide workflow enumeration on production `main` found 11 workflow files. None contains `pull_request_target`; none contains `workflow_run` or `workflow_call`.
- Five workflows accept `pull_request`: repository-governance, repository-naming-policy, v12-stage2-live-acceptance, v12-stagec-analytics-acceptance, and v6-ci. These use only dependency caches through setup-python/pip; no P1.7 or MC decision-cache restore/save was found in PR-triggered workflows.
- The only explicit V12 decision-cache restore/save surface is `v12-integrated-report-runner.yml`, which is not PR-triggered. However, GitHub's documented cache model allows fork PRs to read caches in the base/default branch scope. Therefore storing decision material in a main-scope Actions cache is itself unsafe even if the producer workflow is owner-gated.
- `issue_comment` is a low-trust trigger by platform model. The report workflow explicitly opts into `cache-mode: write`; its current parse gate restricts execution to the repository owner, but P1 still removes private decision caches from public Actions cache so this gate is not the sole confidentiality control.
- No repository/account security setting is changed by this branch without owner approval.

## P1-A6 issue/comment conclusion

Public proof currently publishes decision action. This is a confirmed leak. P1 public proof will use an allowlist and retain only validation status.

## Non-destructive historical handling

No artifact, log, cache, comment, branch history, or Git history was deleted or rewritten during this audit. P1-K will produce cleanup candidates and wait for owner approval.


## Latest-main re-audit after semantic-hardening merge

Production `main` moved by 61 commits after the initial P1 audit. P1 work was
therefore recreated from `3d433348a04d8207321bc4521808e253f21ed3fc`
rather than rebasing the old P1 branch blindly.

The latest production workflow still had all four primary exposure classes:

- public artifact upload still included `report_bundle.json` and
  `report_body.md`;
- public issue #431 still emitted `action=WAIT` on successful DEEP runs,
  including run `36232738219`;
- public Actions cache still restored/saved exact P1.7 and MC cache families;
- `runtime-data-v6` still contained
  `data/v6/personal/current_team.json`.

Actual public job log for run `36232738219`, job `108378850663`, contains
resolved `STAGE3_ACTION: WAIT` and the public report-body artifact path. This
proves the latest production state remained vulnerable after the semantic
hardening merge.

## Current P1 implementation status on r2

The bounded P1 branch now:

- preserves the latest semantic-hardening code as base;
- removes public full-report upload from the integrated report workflow;
- routes canonical output to the private repository before public proof;
- removes Stage3 action and MC path counts from public issue output;
- keeps Stage-2 derived cache public-safe;
- makes P1.7 and MC caches runner-local rather than public Actions caches;
- restores previous visible DEEP baseline from private report history so S03
  semantics remain available;
- reads current/manual personal state from the private plane;
- removes direct public-current-team reads from the integrated runner;
- keeps Stage-2 acceptance on disclosed public submitted picks and public league
  facts, not authenticated current-team state;
- defines a V6 boundary that removes current-team/auth-personal state before
  the public candidate tree is frozen;
- adds P1 privacy/security tests to mandatory PR CI.

No artifact, run, issue comment, cache, branch history, or Git history has been
deleted or rewritten.


## P1-K retained-history inventory status

The current non-destructive historical audit found **44 public V12 completion
occurrences** in issue #431 between 2026-09-21 and 2026-09-26. Successful
occurrences from the period include public decision action values such as
`WAIT`; failed/partial occurrences can still expose artifact names and
operational metadata.

Retained-artifact verification proves that multiple old full-report artifacts
remain accessible. Examples sampled during the audit include:

| run_id | artifact | created | expires | still accessible at audit |
|---|---|---|---|---|
| 35597594711 | `v12-report-DEEP-35597594711` | 2026-09-21 | 2026-10-05 | YES |
| 35617436772 | `v12-report-DEEP-35617436772` | 2026-09-21 | 2026-10-05 | YES |
| 35659302333 | `v12-report-DEEP-35659302333` | 2026-09-21 | 2026-10-05 | YES |
| 35659879299 | `v12-report-DEEP-35659879299` | 2026-09-21 | 2026-10-05 | YES |
| 36126675342 | `v12-report-DEEP-36126675342` | 2026-09-25 | retained during audit | YES |

Run `36126675342` remains the mandatory regression occurrence. Latest-main
re-audit additionally confirmed the same public decision-action leak class in
run `36232738219`.

No retained artifact, Actions run/log, cache, issue comment, or Git commit has
been deleted by P1. Cleanup remains an explicit-owner-approval operation.

## Isolated V6 private-personal publisher correction

PR CI correctly rejected an intermediate design that performed `git push`
from the V6 acquisition job. The acquisition invariant remains unchanged:
the collection job is read-only and cannot publish.

The corrected architecture is:

1. V6 acquisition may obtain authenticated state in the ephemeral runner;
2. `private_boundary.py` removes authenticated current-team/auth-personal
   state before the public candidate tree is frozen;
3. the verified public runtime artifact contains no current-team private
   payload;
4. a separate isolated private-personal publisher job re-runs the governed
   personal fetch against a temporary copy of the verified factual snapshot;
5. only `personal/*` is committed to `iphoenk/fpl-reports-private`;
6. authenticated/private stdout and stderr stay off public logs;
7. manual captures continue to enter the private repo directly and never
   transit through `runtime-data-v6`.

This preserves the V6 factual/public acquisition method and public publisher
governance while separating persistence authority.


## P1-N real DEEP branch acceptance evidence

A real DEEP occurrence was executed from the bounded P1 branch before merge:

- acceptance code SHA: `aad536a3660f4ff3df0a85f62253302b2e0fce7a`;
- run ID: `36245142505`;
- report slot: `2026-09-26T20:26:02+07:00`;
- factual runtime SHA: `d0bada58d308da3c876a741924e1dfa4c3bbd76b`;
- analytics, pre-render, post-render, human-facing, and Stage3 validation: `PASS`;
- private delivery: `PASS`;
- public artifact set: exactly one allowlisted `v12-public-proof-DEEP-36245142505`;
- public artifact contains only `public_proof.json`; no report body, report bundle, scenario, profile log, or decision artifact;
- public issue #431 proof is validation-only and contains no Stage3 action or route material;
- exact public Actions logs were read after completion: decision-leak findings = `0`, unmasked-secret findings = `0`, rendered-report heading/prose findings = `0`;
- private repository commit: `3b63bb2d1580abb8d42d816cf8d5c2b60686d02e`;
- private report path: `reports/2026-27/gw_6/20260926_202602_plus_0700`;
- canonical body SHA256: `aa208b8c571a37a78397a5dd0a621590c93daaff278c1a9bf3a65491a00480b8`;
- canonical bundle SHA256: `ecf26a2f01b04dc6b56dbaff1ced71dbe9666aca817bb1edeaca82ccf1d73d34`;
- public proof carries the same two canonical fingerprints;
- private digest reports `math_recomputed=false` and `decision_source=CANONICAL_OUTPUT_COPY_ONLY`;
- all 23 internal section IDs remain exactly `S01..S19` plus `S06B/S14B/S15B/S16B`;
- the thin publisher persisted report body, report bundle, canonical execution proof, Stage3 acceptance, private execution proof, digest, and delivery receipt.

Observed recompute cost with decision-sensitive Actions caches disabled remained bounded:
Stage-2 cache was a safe `HIT`; exact cross-route package utility completed in
about 18.6 s, funded package utility in about 5.8 s, and Monte Carlo in about
33.6 s. The public proof reports 67.919 s summed stage time.

The temporary owner-only push trigger used solely to obtain this branch
acceptance was removed immediately after evidence capture. It is not part of
the final P1 workflow design.

### Remaining production cutover condition

This branch acceptance does **not** claim final production P1 GREEN yet.
Production `runtime-data-v6` still contains the legacy
`data/v6/personal/current_team.json` because production `main` has not been
merged to the private-plane reader. Deleting that file before coordinated
cutover would break the current production reader and is therefore not a safe
pre-merge cleanup.

The P1 branch changes V6 publication so the private boundary removes this file
before the next public candidate freeze, while a separate isolated job
persists authenticated/current personal state to the private repository.
Final PUBLIC GIT closure therefore requires owner-approved merge/cutover plus
one verified V6 publication on the merged code. Historical destructive cleanup
remains separately approval-gated under P1-K.
