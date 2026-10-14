# Production-controlled source-join QA and public-first recovery

Change timestamp: 2026-10-14T23:32:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:32:00+07:00

## Exact controlled failures

Controlled DEEP at 14 October 2026 23:14 WIB, GitHub Actions report run 38596886053, completed with HUMAN_FACING_QA failure RENDERED_RAW_MAPPING_REPR and private_delivery=FAIL. The source-consumption ledger (PR #1081) printed `rejected_reasons` directly as a Python mapping. The human-facing QA guard correctly rejected this unsafe implementation. Preserve the QA and Stage3 fail-closed behavior.

At 23:20 WIB, original V6 full-master prefetch generated real source artifacts and its public core, mini-league and public picks were available. But legacy_public_auth_state=AUTH_EXPIRED made strict `complete=false`, and full-master `classify_prefetch_state` produced PREFETCH_FAILED despite `public_core_complete=true`. The protected rotating auth state was NOT_EVALUATED_IN_PUBLIC_PLANE: never infer `/me` and `/my-team` HTTP 200 from the legacy public plane.

## Remediation

- Serialize source rejection reasons as sorted, sanitized `REASON=N` human prose rather than raw mapping repr. This preserves all numeric evidence while meeting the existing human-facing QA contract.
- For full-master prefetch, when public core is complete and authenticated personal data was explicitly deferred by the existing producer policy, label PREFETCH_PUBLIC_FIRST rather than PREFETCH_FAILED. Never change to PREFETCH_FULL without original strict completion, never accept incomplete public core, and never classify deferral as authenticated finance available.
- Retain PRICE-specific private personal readiness separately.
- Add two full-governance regression nodes (required count 1414 -> 1416), for safe diagnostic output and public-first classification.

## Non-claims

Code/CI PASS does not establish the 23:20 DEEP private receipt, OIDC protected store HTTP 200, PRICE current private data, Wave 3 genuine 12/12, natural scheduler acceptance, GW1–GW6 original training archive as-of, full model resolution/calibration, settled GW7 holdout, special Palmer+Rogers MC500K or native ChatGPT host visual proof. No second scheduler, Stage3 relaxation, original frozen GW7 forecast rewrite, P(start) math change, PR #809 or Monte Carlo path change.
