# P0 FPL OIDC rotating access: production security gate (2026-10-11)

Status: **CODE STAGED, NOT ENABLED**. This is a security review/implementation
boundary, not proof of unattended or supported renewable access.

## Grounded facts

- On 2026-10-11 07:35 WIB the owner-only iOS Shortcut observed one
  `oidc.user:` browser record with a nonempty `refresh_token`.
  No token value was sent to the repository or a conversation.
- Current V6 `OfficialFPLClient` supports protected bearer/session inputs,
  not managed refresh-token rotation. Current private publisher/probe reads
  `FPL_ACCESS_TOKEN` and `FPL_SESSION_B64` from environment secrets.
- Legacy `src/sources/official_auth.py` has a refresh helper which only returns
  `access_token`. **It is not the rotating production implementation.**
- Premier League official public OpenID discovery returned HTTP 200 in
  GitHub Actions run 38099542251 (2026-10-11 07:46 WIB). It advertised issuer
  `https://account.premierleague.com/as`, token endpoint
  `https://account.premierleague.com/as/token`, and `refresh_token` grant.
  This verifies provider metadata, NOT the FPL browser client configuration,
  rotation policy, refresh lifetime or browser/server coexistence.
- The provider's own PingFederate documentation says rotation, token reuse
  protection and grace windows depend on client/server configuration.

## One controlled live grant, WITHOUT changing natural scheduler

The `v6-auth-probe.yml` workflow now offers an owner-only
`auth_attempt=CONTROLLED_ONCE` via **Actions → V6 private auth diagnostic →
Run workflow** on `main`. The workflow checks the exact owner identity,
uses the existing protected `v12-private-reports-publisher` environment,
temporarily selects rotating auth for that ONE job, and requires an explicit
owner-selected input. It DOES NOT require changing `FPL_AUTH_MODE` or
`FPL_OIDC_CONTRACT_VERIFIED` environment variables.

Before running:
- Owner agrees to possible Safari logout or refresh-token family collision;
  this has not been verified for the live FPL SPA client.
- The encrypted credential exists, the temporary bootstrap secret is deleted,
  `FPL_OIDC_CLIENT_ID` is configured, and the protected encryption key is present.
- Confirm no competing controlled credential probe is active.
- Do NOT refresh via Safari or resume browser silent renewal concurrently.
- Keep `FPL_AUTH_MODE` disabled for natural jobs. Controlled grant is one-shot,
  not a supported-production-client-policy certification.

The workflow intentionally makes a single token grant attempt. It writes a
durable IN_FLIGHT marker before POST, persists any replacement refresh token,
and reads it back before invoking authenticated /me and /my-team. Subsequent
probes may use a still-live saved access token without a second exchange.
Do not retry a failed or timed-out grant; record a redacted error and
investigate/reenroll safely.

Observed proof stages MUST remain distinct: public discovery and client-ID
format; owner-approved first grant HTTP status; persisted replacement version;
identity and exact team checks; second-worker reuse; subsequent controlled
natural V6 and V12 evidence; genuine native visible delivery. No one status
alone implies permanent refresh.

The former frozen cross-CPU artifact `36287336832` expired or became
unavailable by 2026-10-11, breaking repository governance. It is replaced
ONLY by the independently verified direct 3-CPU PASS run `38101198457`
(artifact `v12-runtime-cross-cpu-acceptance-38101198457`, physical CPUs 3,
8 probes, bit-identical sha256
`89f41be085a1e387eb87ee86dfecfb5d4cf4c2924a20221ee27c09f757c4db87`).
The gate continues fetching and checking actual unexpired proof evidence.

## Enforced state-machine contracts

The staged `rotating_oidc.py` provides fail-closed logic for an owner-approved
and independently audited implementation. No calls are connected to production
until a durable encrypted backend and provider contract are verified.

1. Store MUST supply durable atomic compare-and-swap, confidential storage,
   restrictive IAM and independent read-back after a write.
2. Lease MUST serialize across every job, process and workflow. A Python
   thread lock or a workflow-local mutex is NOT enough. A GitHub Actions
   concurrency group can serialize participating jobs in the same repository,
   but it does not protect an external worker or browser.
3. Write IN_FLIGHT before POST to the verified HTTPS token endpoint.
4. Never retry the POST if a timeout may have consumed a one-time token.
5. A missing replacement refresh token is blocked by default. Use a
   nonrotating policy only when the official client policy is independently
   verified, not because a mocked test passes.
6. Save new refresh/access state atomically, load independently, compare, then
   permit the application to use the access token.
7. Crash/uncertain result requires explicit re-enrollment; never silently
   roll back to the prior refresh token.
8. Once the access token is obtained, private /me and /my-team/{team_id}
   must both pass HTTP 200 and established 3462711 identity/15-pick validators
   before publishing any private finance, FT or selling-price facts.
9. A failed private state MUST NOT gate Official public fixture, picks, MATCH
   or mini-league acquisition and native report delivery.

## Implemented opt-in persistent backend (second stage, 11 October 2026)

The private-reports Git repository holds **only authenticated encrypted ciphertext**
at `.auth-private/fpl-oidc-credential.enc`. The Fernet key resides **only** in
the protected GitHub Actions environment secret `FPL_OIDC_STORE_KEY`.
Never add either the key or the raw tokens to repository files or reports.

- A strict remote allowlist pins writes to `iphoenk/fpl-reports-private`.
- Each update fetches the freshest `origin/main`, checks the credential version,
  commits only encrypted bytes in a temporary Git worktree, and pushes with
  fast-forward semantics. A raced writer fails rather than overwriting.
- The initial encrypted IN_FLIGHT state is a cross-runner exclusive grant claim;
  no other process can re-use the same refresh token. A failed/missing final
  write or crash requires explicit owner re-enrollment, never blind retry.
- The owner-only `v6-oidc-owner-bootstrap.yml` workflow seeds ciphertext using
  a token supplied as a **protected environment secret**, not a workflow input.
- Private publisher and read-only auth probe use the backend only when the
  environment variable `FPL_AUTH_MODE=rotating_oidc` is explicitly selected.
  The legacy bearer/session paths and public-first operation remain intact.
- `FPL_OIDC_CONTRACT_VERIFIED=true` is a privileged **owner approval flag**;
  it must not be set based only on provider metadata or fake-token CI tests.
  Confirm the browser client ID, its expected token grant policy and possible
  Safari session impact first.
- GitHub Actions environment secrets themselves have separate access controls
  and are not readable back; the durable encrypted Git blob is versioned and
  independently read back after each write. The private Git history is
  immutable audit provenance for **ciphertext only**.
- The bootstrap secret `FPL_OIDC_BOOTSTRAP_REFRESH_TOKEN` MUST be deleted by
  the owner from GitHub Settings → Environments immediately after enrollment,
  because Actions cannot delete it without separate privileged API permissions.
  Never treat its lingering presence as permanent credential storage.

### Owner-only iPhone setup after code and security CI is green

1. Safari → github.com → `iphoenk/FPL-iphoenk-engine` →
   **Settings → Environments → v12-private-reports-publisher**.
2. Add protected environment secret `FPL_OIDC_STORE_KEY` with a locally
   generated **32-byte random URL-safe-base64 Fernet key**. Use only secure
   browser/Shortcuts local crypto; never paste it into a chat or screenshot.
3. Retrieve the refresh token locally from the already-authorized Safari FPL
   session using an approved, owner-inspected iOS Shortcut. Copy directly to
   environment secret `FPL_OIDC_BOOTSTRAP_REFRESH_TOKEN`, and clear clipboard.
   Do not output it in a Shortcut notification, iCloud note, issue or PR.
4. In repository **Actions → FPL protected OIDC credential enrollment →
   Run workflow**, choose **ENROLL**. Inspect only status/version. This
   stores ciphertext without calling the official token endpoint.
5. Delete the temporary bootstrap environment secret in GitHub. Verify the
   encrypted file is present in the private repo without decoding it.
6. Extract the **non-secret** client ID from Safari's OIDC storage record and
   set environment variable `FPL_OIDC_CLIENT_ID` in the same environment.
7. Independently validate supported public-client refresh behavior, Safari
   collision/re-login policy, and that the client ID is correct; then set
   environment variable `FPL_OIDC_CONTRACT_VERIFIED=true`.
8. Set environment variable `FPL_AUTH_MODE=rotating_oidc`. Run one controlled
   **V6 private auth diagnostic** to intentionally perform the first live
   grant. Observe only redacted /me, identity and /my-team 3462711 outcomes.
9. Verify `IN_FLIGHT → READY` persisted a newer encrypted credential version;
   run another worker/probe, verify re-use without a second refresh, and
   verify finance/FT provenance and canonical V12 report consumption.
10. If Safari was invalidated by the server grant, log back into FPL there.
    If the server rejects the grant, **do not** repeatedly run refresh; use
    owner-authorized **REENROLL** after diagnosing the provider behavior.

**No unattended refresh is green merely from CI.** No refresh token has been
enrolled by the assistant, and no live grant has been performed.

## Prior design constraints / external-store alternatives

Choose an existing approved secret manager (e.g., AWS Secrets Manager with
DynamoDB conditional lease / version state, or a similarly audited service).
GitHub Actions environment secrets ARE encrypted but cannot be read back as a
new value by the management API. A default GITHUB_TOKEN is not proven to have
permission to update them. A distinct GitHub App with verified scoped secret
write permissions may be considered only after least-privilege review.

Before enabling, prove:
- service/resource exists, encryption and IAM policies, region, audit history;
- non-chat one-time iPhone enrollment interface;
- server-only persistent read+write and CAS, independent worker read-back;
- durable IN_FLIGHT marker and emergency re-enrollment path;
- verified issuer, token URL and public-client grant contract from official
  discovery/client data, with account-level session collision assessment;
- integration tests with fake providers, then owner-authorized controlled
  real exchange plus second independent worker reuse;
- no raw credentials in logs, job summaries, artifacts, caches or reports.

The existing repository/governance scheduler stays untouched. This staged
component is inert and requires explicit dependency wiring under protected
environment controls once the backend is verified.

## Owner-only iPhone enrollment: DO NOT RUN YET

After BOOTSTRAP_READY has been independently demonstrated:
1. Open logged-in Fantasy Premier League in Safari.
2. Use the existing `Run FPL` Shortcut only on the Premier League webpage;
   independently verify that it uses the page's own origin.
3. Copy the OIDC credential locally in Shortcuts without a screenshot or
   sharing sheet destination. Do not return its value to ChatGPT or a report.
4. In Safari, sign in to the **preapproved and deployed** secure enrollment
   interface. Paste directly into its protected secret-entry control; check
   only existence/version/last-updated metadata, never retrieve the value.
5. Run one deliberately authorized probe. Validate /me and /my-team/3462711;
   do not confuse a successful access-token check with proven refresh rotation.
6. Only after issuer and collision policy confirmation, execute one controlled
   refresh, verify persisted replacement plus a second worker's reuse, and
   verify private V6 and canonical V12 finance.
7. Re-login to Safari if the identity provider invalidates the browser session.

**There is no approved enrollment URL or workflow yet. Do not paste a real
credential into any random website or GitHub issue/PR/comment.**

## Acceptance/status language

CODE_READY = code and mocked test suite green.
BOOTSTRAP_READY = persistent store and secure iPhone enrollment work.
AUTH_LIVE = owner-authorized official endpoints verify identity.
ROTATION_PROVEN = official real refresh, persistence, second-worker reuse.
FULL_GREEN_PROD = correct canonical V12 + natural scheduling + native visible
delivery independently verified. None of these are interchangeable.
