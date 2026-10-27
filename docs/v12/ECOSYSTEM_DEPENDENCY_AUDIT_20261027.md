# FPL ecosystem dependency and impact audit (27 Oct 2026)

Read-only audit. No dashboard, Vercel, secret, scheduler, ChatGPT task or issue #431 change was made.

## Exact references observed

| Repository | Ref | SHA | Note |
|---|---|---|---|
| iphoenk/FPL-iphoenk-engine | main | 088e8706c3fd8d1955cd7517776fad1882d474fd | PR #1203 |
| iphoenk/FPL-iphoenk-engine | runtime-data-v6 | aa5addcc08735c7198b9ce7645d594c19f63211b | hourly V6 data snapshot, run 40428424526 |
| iphoenk/fpl-reports-private | main | d9d8b8985652a2ca8e0a521bc89b0a4883183306 | private canonical artifacts |
| iphoenk/fpl-master-monitor | main | 3c90f72cd993c5d65910cf6a204e314ac2809da5 | read-only foundation, 496 lines |
| iphoenk/fpl-iphoenk-dashboard | main | e68bf2c5f28acda5b67835532a86143bc184d1f1 | protected, cloned read-only, push URL disabled |

## Dependency map

```
Official FPL + 12 other V6 providers
  -> V6 collect/publish (engine workflows, GitHub App writer)
  -> branch runtime-data-v6: data/v6/**  (public raw)
        |-> V12 orchestrator/runner (engine) -> private canonical artifacts (fpl-reports-private)
        |        -> receipt (#431 comment) -> latest/verified.json -> ChatGPT task (read-only)
        |-> DASHBOARD (multiuser-decision-server.mjs): evidence/latest_index.json, health/publish_integrity.json (provenance only)
Dashboard also reads: Official FPL bootstrap/entry/picks/history; iphoenk/fpl-dashboard main public/data meta.json+players.json (legacy global model).
Dashboard vendors a PINNED copy of V12 package-search/lineup rules (vendor/v12/provenance.json, sha 22655d57); it does not import the engine live.
Master Monitor: public Official FPL only; schedule 5 */6 * * *; uploads artifact only; no writes to other repos.
```

## Change-impact matrix

| Change (PR) | Touches | Dashboard-visible? | Reason |
|---|---|---|---|
| #1202 S02 window | Stage3 validator (private-report path) | No | no write to runtime-data-v6; dashboard has no V12 input |
| #1203 V6 trace window | read-side trace validator | No | reads data/v6, writes only the private bundle |
| #1199 external clock (inactive) | workflow_dispatch inputs | No | disabled by repo variable |
| Verified pointer / receipts | private repo | No | private, identifiers and hashes only |
| Any change to data/v6 schema or publish_integrity | V6 publisher | YES | pinned by tests/test_dashboard_v6_consumer_contract.py |

## Dashboard contract baseline (what it actually reads)

- `data/v6/evidence/latest_index.json`: `generated_at` (tz-aware ISO), `sources[].source_id`, `sources[].health`.
- `data/v6/health/publish_integrity.json`: `status == "PASS"`, `observed_at` (tz-aware ISO).
- Missing, failing or naive values degrade to `UNAVAILABLE` or `UNVERIFIED`, never an error. Age over 6 h gives `STALE`.
- Public routes are `/api/*` rewritten to `/api` (api/index.js, maxDuration 180); `/api/decision?entry_id=&horizon=1|3|5` is the single advisory endpoint.

## Blockers established with evidence

- Vercel production deployment ID, alias health and environment cannot be read: outbound HTTPS to `*.vercel.app` from the workspace returns no connection (curl code 000) and the session has no Vercel credential. Baseline VERCEL gate is therefore UNVERIFIED from here and needs the owner (deployment ID, commit and a health probe).
- GitHub API access to the dashboard repository is deliberately not attached (git read only), so its Actions and deployment statuses are not visible.
