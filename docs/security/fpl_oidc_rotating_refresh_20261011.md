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

## Required production backend, not yet provisioned

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
