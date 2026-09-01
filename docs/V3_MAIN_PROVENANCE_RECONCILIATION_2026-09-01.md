# V3 Main Provenance Reconciliation — 2026-09-01

## Incident

A direct commit was written to `main` while capturing the user-confirmed GW3 transfer state:

- parent: `05b0baaef83503e50d3ef489d26f3675a9c00b1e`
- direct commit: `2195231345180f6768c7a5cc10d51419d777e304`
- commit message: `state: capture GW3 Aina to Ajayi transfer`

The V3 main provenance guard correctly failed closed because the commit was not associated with a merged pull request.

## Scope audit

GitHub compare confirms the direct commit is exactly one commit ahead of its parent and changes only:

- `config/locked_squad.json`

No prediction mathematics, optimizer logic, DSS semantics, tactical model, serving semantics, runtime publication code, provenance implementation, or security flag was changed by the direct commit.

## Reconciliation

This governed PR intentionally advances the V3 provenance trust anchor to the audited state-only commit `2195231345180f6768c7a5cc10d51419d777e304`.

This is a one-time reconciliation of an already-published direct state commit. It is not an exception mechanism for future direct writes.

Security invariants remain unchanged:

- `require_anchor_in_first_parent_history = true`
- `require_each_first_parent_commit_after_anchor_from_merged_pr = true`
- `fail_closed_on_github_api_error = true`

After this reconciliation PR is merged, every first-parent commit after the reconciled anchor must still be associated with a merged PR. Future direct commits to `main` remain blocked.

## Expected recovery

1. Merge this reconciliation through the normal PR path.
2. V3 CI push validation checks the merge commit against the reconciled anchor.
3. The merge commit must resolve to this merged PR.
4. V3 CI must pass before runtime publication is allowed.
5. The `V3 Runtime` workflow may then regenerate `runtime-data` from the new governed `main` source commit.

No history rewrite or force-push is required.
