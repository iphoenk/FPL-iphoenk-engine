# V4 Red Audit Hardening Closeout

Scope is intentionally limited to the two red findings from the post-PR #276 audit.

1. Single final decision authority
   - `CANONICAL_DECISION_ARBITRATION_V1` remains the only final HOLD/REVIEW/CHANGE authority.
   - Owned Challenger keeps dynamic ranking, pairwise battle analysis, emerging candidates, and package evidence as advisory `challenge_signal`.
   - Serving fails closed if Owned Challenger's canonical action does not equal the canonical serving action.

2. Governed challenger policy and artifact
   - Owned Challenger policy is bound to release manifest, service registry, service-contract registry, architecture ownership, and architecture attestation.
   - The artifact remains inside the existing optimization boundary. No ninth microservice is introduced.
   - Architecture guard explicitly checks `owned_challenger_single_decision_authority`.

Dedicated QA/QC regression tests reject a second decision authority and verify registry/release/attestation bindings.

Yellow cleanup items from the broader audit are intentionally excluded from this change.
