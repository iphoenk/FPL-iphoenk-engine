# P0 private DEEP sparse-rebase remote-readback failure

Audit date: 15 October 2026. Baseline production main: `2dbc12d54fa3790fbc6b4b01e18f11425aefcd33`.

Original controlled DEEP [run 38600091016](https://github.com/iphoenk/FPL-iphoenk-engine/actions/runs/38600091016), logical report slot 14 Oct 23:39 +07, original job `115976851116`:

- First `git push origin HEAD:main` rejected (non-fast-forward) after another private publisher updated main.
- Existing bounded retry fetched `origin/main`, and `git rebase --strategy-option=theirs origin/main` succeeded; next push succeeded to remote `fa11fc9...`. An initial rejected push was therefore **not** the ultimate failure.
- The remote commit included occurrence `native_content.manifest.json`. Original remote Git-object `git show <pinned-sha>:<path>` readback succeeded, but local `(repo / root / "native_content.manifest.json").write_bytes(...)` failed with `FileNotFoundError` because the sparse-rebased checkout no longer materialized the occurrence directory. The missing final receipt meant `PRIVATE_DELIVERY=FAIL` despite first-stage remote publication.
- Canonical report content and occurrence remain immutable. No hashes or evidence may be forged or reconstructed by modifying old receipts.

## Corrective action

Retain existing git push/rebase retries, original remote source readback, SHA comparisons, mode-specific latest identity, manifest chunk parity, and forecast source verification. After the verified pinned remote Git-object readback, explicitly create the local occurrence and latest parent directories before storing remote-readback annotated manifest/receipt. This changes no remote source contents and prevents the local sparse-checkout `FileNotFoundError`.

Test extension enforces parent path reconstruction in the governed test suite. Successful CI and merge prove the code path, not a new actual remote occurrence. Production acceptance still requires a NEW exact-occurrence DEEP delivery, final remote SHA/receipt/hash, 22 sections/26 chunks, valid immutable forecast SHA256, and native host UI acknowledgment verified separately. Preserve fail-closed if concurrent latest changes between remote pin and receipt write.

Change timestamp: 2026-10-15T05:15:00+07:00
Documentation sync: UPDATED


## 15 Oct 2026 second occurrence private receipt parent regression

Controlled V12 #38677939541 ended FAILED in the post-first-push remote readback/publish stage after concurrent private Git writer. Job log identifies FileNotFoundError at ../private-reports/reports/2026-27/gw_7/20261015_104400_plus_0700/delivery_receipt.json; original remote Git-object readback was performed before Python tried to write its updated local receipt. Sparse rebase may leave the local report occurrence directory absent even when remote objects exist. Remediation only reconstructs the local receipt parent before local write. Remote verified SHA and canonical immutable original remain unchanged; do not assume final readback success unless the final private receipt is remotely verified.

Change timestamp: 2026-10-15T13:07:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-15T13:07:00+07:00
