# Independent external clock trigger: architecture, activation and rollback (INACTIVE)

Status: implemented but inactive. Nothing here creates a secret, a scheduler instance, a ChatGPT task, or touches issue #431 until the owner gives separate final authorization.

## 1. Measured need
GitHub `schedule` delivered 38 of 456 expected ticks in 19 days (median gap 3.8 h, max 5.4 h). Of 75 DEEP/PRICE slots, 6 (8%) had a tick in the resolver window; the future-only recovery adds 8 (total 19%); 61 (81%) were uncovered. Cron delivery, not code, is the binding constraint.

## 2. Contract found (corrects the premise "repository_dispatch")
The repository uses no `repository_dispatch`. The existing governed path is `workflow_dispatch`:

`fpl-github-clock.yml` (tick) -> `resolve_tick(now)` (the only authority on occurrence identity) -> `fpl-external-clock-fallback.yml` (validates logical slot and -5..+70 min window, dispatches the V6 child, waits, dispatches the orchestrator idempotently with `scheduler_authority=EXTERNAL_CLOCK_FALLBACK`, writes `natural_proof=false` evidence) -> `fpl-master-occurrence-orchestrator.yml` (receipt guard, V6 prefetch, V12 runner, verification, receipt, verified pointer).

The external scheduler therefore only calls `workflow_dispatch` on `fpl-github-clock.yml`; it computes nothing.

## 3. Architecture
```
Cloudflare Worker cron (UTC) --POST dispatches--> fpl-github-clock.yml
        trigger_origin=EXTERNAL_INDEPENDENT_CLOCK, external_trigger_id=<cron@time>
   job gate : vars.FPL_EXTERNAL_CLOCK == 'ENABLED'   (kill switch 1; Worker var EXTERNAL_CLOCK_ENABLED is switch 2)
   resolve_tick(now)                                  same identity MODE|ISO_SLOT as the GitHub schedule
   ops.external_clock_gate                            bounded + idempotent + fail closed
   announce on #431 BEFORE any dispatch               FPL_EXTERNAL_CLOCK_TRIGGER ... natural_proof=false
   -> existing fallback -> V6 -> orchestrator -> V12 -> verification -> verified pointer (origin=EXTERNAL_CLOCK)
```
The GitHub cron `35 * * * *` is unchanged and keeps working in parallel.

Guarantees (all tested in `tests/test_external_clock_gate.py`):
- Eligibility: only a DEEP/PRICE occurrence due in the resolver window; plain ticks are skipped (no V6 work, no comment).
- Duplicate prevention: skip when any run of the exact occurrence is queued, in progress or succeeded; skip after a failed/cancelled/timed-out attempt (no automatic retry). Simultaneous triggers are serialised by the fallback concurrency group (per logical slot), the orchestrator group (no cancel) and the orchestrator receipt guard. A latent defect was fixed: the fallback's idempotency check used the title `FPL Master occurrence ...`, which never matched the orchestrator run-name `FPL EXTERNAL_CLOCK_FALLBACK occurrence ...`.
- Fail closed: variable unset or not exactly `ENABLED`, run listing failure/timeout/permission error/garbage, missing output, announcement failure => no dispatch. Non-external origins are unchanged.
- Provenance: the announcement precedes the dispatch; the verified pointer records `origin` `RECOVERY` > `EXTERNAL_CLOCK` > `SCHEDULED_OR_FALLBACK`; evidence says `schedule_origin=EXTERNAL_INDEPENDENT_CLOCK`, `natural_proof=false`, `github_scheduled_natural=false`. An external-triggered occurrence is never labelled a GitHub scheduled natural one. ChatGPT natural acceptance remains an independent observation of the ordinary ChatGPT task and is not changed by any trigger.
- Isolation: external origin never runs the audit or recovery jobs; no new permission and no new secret in the clock workflow; the Worker holds the only new credential.
- Timeouts: Worker aborts after 10 s, one attempt per invocation (the next ping is the retry), GitHub side unchanged (45 min job).

## 4. Schedule
One cron expression (one of five free-plan triggers): `5,20,35,50 21,22,23,0,5,6,14,15 * * *` UTC. For every one of the >600 DEEP/PRICE occurrences between March and November 2026, including both UK clock changes, at least four pings fall in the resolver window and each resolves to exactly that occurrence (test).

## 5. Provider comparison
| Provider | Reliability | Security | Complexity | Cost | Notes |
| --- | --- | --- | --- | --- | --- |
| Cloudflare Workers Cron Trigger (recommended) | [Kemungkinan Besar] fires within seconds of schedule; no contractual SLA on the free plan | secret in Worker secret store; no inbound surface | low: one Worker + one secret | Free plan: 100,000 requests/day, 5 cron triggers per account, 10 ms CPU per trigger (a single fetch waits on I/O); paid plan from US$5/month | facts from Cloudflare Workers pricing/limits pages |
| Google Cloud Scheduler | [Kemungkinan Besar] high, documented SLA | IAM + Secret Manager | medium: GCP project, billing, HTTP target with auth header | [Kemungkinan Besar] a few free jobs per billing account, then cents per job per month | good if ICON+ already runs on GCP |
| AWS EventBridge Scheduler | [Kemungkinan Besar] high, documented SLA | IAM + Secrets Manager, API destination | medium | [Kemungkinan Besar] free tier covers this volume | good if AWS already used |
| cron-job.org or similar SaaS | [Menebak] unknown, community service | PAT stored with a third party | low | free | weakest governance; not recommended for a write-capable token |
| Self-hosted cron on an existing server | depends entirely on that host | token on a server you operate | low if a server exists | zero marginal | single point of failure unless monitored |

"Prefer existing infrastructure": if the owner already operates an always-on cloud account (GCP, AWS) or a monitored server, use it, reusing `deploy/external-clock/worker.js` logic (one authenticated POST). Without such infrastructure, Cloudflare Workers is the recommendation.

## 6. Credential
A dedicated GitHub identity (bot account or GitHub App installation), not the repository owner, with access limited to this repository and permission Actions: write (+ metadata read). Because the identity is not the owner, the owner-only authorities (`OWNER_CONTROLLED`, `CHATGPT_FPL_MASTER_SCHEDULER`) stay closed to it. Residual exposure: a holder of Actions write can dispatch any `workflow_dispatch` workflow, including the orchestrator with `EXTERNAL_CLOCK_FALLBACK` (already true for any collaborator). Fine-grained PATs expire (monitor expiry); an App avoids that.

## 7. Expected SLA and cost
- Trigger coverage: at least four independent pings per slot window. If each is delivered with probability 0.9, the chance that none arrives is 0.0001; [Menebak] trigger-level availability of 99% or better, to be measured, not assumed. This bounds delivery of the TRIGGER, not of the report: the pipeline itself still has to succeed (the last orchestrator run before this work failed on the since-fixed catalog mismatch).
- Cost: US$0 (Cloudflare free plan; public repository Actions minutes; about 28 pings/day, about 8 resulting in a short tick job, roughly 10 minutes of runner time per day). Upper bound US$5/month if the paid plan is ever needed.

## 8. Activation checklist (owner; none performed)
1. Final written authorization.
2. Choose provider; create the dedicated GitHub identity and a token with Actions: write limited to this repository.
3. Deploy the Worker with `EXTERNAL_CLOCK_ENABLED="false"`; store `GITHUB_TOKEN` as a Worker secret.
4. Dry run: set the repository variable `FPL_EXTERNAL_CLOCK=ENABLED` outside a report window; trigger once manually; expect the tick job to log `NO_REPORT_DUE_IN_RESOLVER_WINDOW` and write nothing.
5. Set `EXTERNAL_CLOCK_ENABLED="true"` before a slot window; expect within the first ping: one `FPL_EXTERNAL_CLOCK_TRIGGER` comment, one fallback run, one orchestrator run titled `FPL EXTERNAL_CLOCK_FALLBACK occurrence ...`, later pings logging `OCCURRENCE_RUN_ACTIVE` or `OCCURRENCE_ALREADY_SUCCEEDED`.
6. Verify the verified pointer entry shows `origin=EXTERNAL_CLOCK`.
7. Known follow-up on activation: the missed-slot audit counts only `schedule` runs as ticks, so a slot missed while the external trigger was active would still be diagnosed from GitHub cron alone; adjust the diagnosis after activation, with evidence.

## 9. Monitoring
Per-slot expectation: at least one `FPL_EXTERNAL_CLOCK_TRIGGER` or `FPL_GITHUB_CLOCK` comment plus a receipt; the 22:50-style audit reports MISSING/FAILED counts; Worker logs (`FPL_EXTERNAL_CLOCK` JSON lines: DISPATCHED / REJECTED / ERROR); token expiry date tracked by the owner; weekly delivery ratio from the audit artifact.

## 10. Rollback
Immediate: delete the repository variable `FPL_EXTERNAL_CLOCK` (or set any value other than `ENABLED`): the next ping is rejected at job level. Second switch: set Worker `EXTERNAL_CLOCK_ENABLED="false"` or remove the cron trigger. Final: revoke the token. In-flight orchestrator runs finish normally; no state needs reverting because the trigger writes only announcement comments. The GitHub cron and the ChatGPT task are untouched throughout.
