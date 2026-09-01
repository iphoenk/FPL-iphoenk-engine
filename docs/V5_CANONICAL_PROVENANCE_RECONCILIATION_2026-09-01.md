# V5 Canonical Provenance Reconciliation — 2026-09-01

## Incident

A direct commit was written to `v5-unified-engine` while capturing the user-confirmed GW3 transfer state:

- parent: `098c9d03df86271fcc4b644df8f7e8c04b3fee55`
- direct commit: `bea82f81bbc3cce0c2bc39b5b5779a68583f5c39`
- commit message: `state(v5): capture GW3 Aina to Ajayi transfer`

The V5 canonical provenance policy rejects unproven direct code/state commits after its trust anchor unless they are an allowed verified governed trigger. This state commit does not match the governed-trigger contract.

## Scope audit

GitHub compare confirms the direct commit is exactly one commit ahead of its parent and changes only:

- `config/locked_squad.json`

No V5 prediction mathematics, optimizer logic, DSS semantics, tactical model, shadow decision authority, serving semantics, provenance implementation, workflow, or security flag was changed by the direct commit.

## Reconciliation

This governed PR intentionally advances `V5_CANONICAL_PROVENANCE_POLICY_V1.trust_anchor_sha` to the audited state-only commit `bea82f81bbc3cce0c2bc39b5b5779a68583f5c39`.

This is a one-time reconciliation of an already-published direct state commit. It is not a bypass for future direct writes.

All security invariants remain enabled:

- `require_anchor_in_first_parent_history = true`
- `require_each_code_commit_after_anchor_from_merged_pr = true`
- `require_merge_commit_sha_match = true`
- `allow_governed_trigger_commits = true` only for the existing tightly-scoped verified trigger contract
- `require_verified_trigger_commit = true`
- `fail_closed_on_github_api_error = true`

After this reconciliation PR is merged with a merge commit, every first-parent commit after the reconciled anchor must still prove either a matching merged PR or the existing verified governed-trigger contract. Future direct state/code commits remain blocked.

## Expected recovery

1. Merge this reconciliation through the normal PR path into `v5-unified-engine`.
2. `V5 Unified Gate` runs on the merge push and enforces canonical provenance before operational use.
3. The merge commit must be associated with this merged PR and its `merge_commit_sha` must match exactly.
4. Once the V5 canonical gate passes, the shadow/evidence scheduler may consume the reconciled branch.
5. `v5-shadow-runtime` must then be regenerated and independently validated; this reconciliation alone does not claim shadow freshness.

No history rewrite or force-push is required.
