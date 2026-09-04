# V6 Standalone Isolation Proof

This file is intentionally V6-owned and exists as a steady-state repository orchestration proof.

Acceptance for the pull request that introduces this marker:

- Repository governance runs.
- FPL V6 CI contracts run.
- V3 CI does **not** run.
- V3 Runtime does **not** run as a consequence of this V6-only change.
- V3 Package Precompute does **not** run as a consequence of this V6-only change.
- V4 production workflows do **not** run as a consequence of this V6-only change.

The proof is valid only when the pull-request and subsequent main-push evidence agree. V6 remains an upstream data-only platform; V3, V4, and future engines are downstream consumers and are not V6 implementation dependencies.
