# FPL iphoenk Engine v3.39.0

- **P0 GW1-GW6 retrospective performance bridge (13 Oct 2026):** active V12 DEEP S02 now exposes a strict six-GW Official FPL history plus verified non-official Understat 2026/27 process metrics and FotMob FT fixture outcomes. Source-native player/fixture crosswalks, exact occurrence equality, timezone-aware no-future-leakage, and explicit status separation are mandatory. FotMob FT cannot promote unfinished Official FPL event or provisional player FPL points to FINAL. The advisory source bridge preserves all 667 Official FPL players, their six per-GW states when raw evidence exists, position-specific metrics, and source authority; nonofficial season totals are never retroactively allocated to individual GWs. Chelsea GW6 Xabi Alonso 3-4-2-1 Palmer/Rogers/João Pedro observed roles are match-specific evidence, not a fabricated numerical coach fit or a direct P(start)/xMins/xPts adjustment. The canonical V12 model, MC500K, scheduler, GH workflows, private authority, and 22-section ordering are unchanged.

- **Wave 3 bounded provenance inventory recovery (13 Oct 2026):** natural Wave 3 18:00 WIB ingestion published successfully but the observer failed while globally slurping every Actions artifact (`unexpected end of JSON input`). The observer now enumerates only successful natural proof runs from `v6-wave3-proof.yml` and successful main-branch push chaos acceptance runs from `v6-ci.yml`, reads their run-scoped artifacts with fail-closed GitHub API retries, and preserves all downstream immutable provenance checks. CI tests cover result filtering, current-run exclusion, missing metadata and mismatched artifact producer identity. This is transport recovery only; it neither fabricates missing natural slots nor changes 12/12 acceptance, scheduler authority, private report, formation MC500K, or native UI host acknowledgment.

- **GW1–GW6 official history V6–V12 alignment (13 Oct 2026):** full_master now derives its factual history planning GW from unambiguous Official FPL is_next / is_current event identity, matching V12's forward GW7 planning horizon while leaving live GW6, fixtures and mini-league scope unchanged. It acquires full Official element-summary GW1–GW6 for every eligible player and stamps both compressed raw history and summary sidecar with exact report kind, logical slot, and prefetch request ID. GW6 provisional remains PENDING and historical acceptance PARTIAL until all Official events and fixtures are final. Regression tests cover six GW slots, finality, event ambiguity, and occurrence stamping. No alternate scheduler, forced settlement, MC change, or synthetic production GREEN.

- **Active DEEP S02 analytical evidence binding repair (13 Oct 2026):** unlike dormant report-build helpers, the final canonical producer used by issue-comment V12 DEEP now binds exact-occurrence full-season historical coverage and all-15 per-player P(start) evidence into S02 and S19 *before* producer fingerprints and native publication. Stale GW6 source/GW1–GW5 history for GW7 remains PARTIAL; missing final Official GW6 never becomes PASS. A focused integration-path regression prevents repeat 0/0/UNAVAILABLE artifacts when bound evidence exists; required full governance baseline reviewed and ratcheted to 1,382 nodes. No changes to MC500K, scheduler, official results, or private authority.


- **Formation MC sampling-evidence recovery (13 Oct 2026):** the eight legal formation MC500K views now bind canonical `sampling_diagnostics.route_path_semantics.by_gw` (not `performance`, which contains timing data). Captain haul/blank, vice activation, autosub and per-GW expected autosub value are validated across all six GWs; missing or invalid sampled rates fail closed, never display fictitious `0.0`. GW7 XI mean P(DNP) derives from sampler `state_frequencies`, never from an absent `players.p_dnp` field. Two synthetic regressions cover missing GW and missing metric. MC500K, P1.7, official-history, native-host evidence boundary, authority and scheduling are unchanged; production remains non-GREEN until post-merge fresh receipt and real native UI acknowledgment.

- **Active integrated S02 GW7 history acceptance (13 Oct 2026):** the actual V12 integrated runner now requires same-occurrence V6 `full_master` evidence, exact source/target planning-GW range, finalized Official historical events and fixtures and verified fixture IDs before full-history PASS. Stale GW1–GW5 for GW7, provisional GW6 and mismatched occurrence produce PARTIAL with explicit reasons. Reviewed governance now requires 1,382 collected nodes including the active DEEP S02 binding regression and the earlier historical coverage tests; no scheduler, decision-model or history receipt changes.


- **Formation MC absolute P10/P90 schema repair (13 Oct 2026):** canonical correlated MC500K returns absolute outcome fields `p10` and `p90`, while the formation adapter incorrectly requested `Q10` / `Q90` (paired-delta fields), displaying UNAVAILABLE. The adapter now binds the canonical absolute quantiles, rejects missing values, and has real-schema regression tests. No simulation or P1.7 authority changes.


- **GW7 full-history finality / source-target range closure (13 Oct 2026):** V6 coverage PASS now requires every historical GW official event and every corresponding fixture to be FINAL, with provisional GW states exposed as PARTIAL. V12 S02 acceptance independently checks required planning GW, exact GW1..N−1, finality and fixture identity; it cannot promote V6 GW1–GW5 into GW7 full-history PASS. No manual GW6 finalization, backfill, alternate scheduler or P1.7/MC change.


- **GW1–GW(N−1) fixture identity / S16B lifecycle hardening (13 Oct 2026):** V6 full-season coverage is PARTIAL if Official element-summary fixture IDs cannot be reconciled against the same-occurrence fixture catalog; raw rows are preserved. V12 S16B prospective baseline markers without receipt/body fingerprint are no longer asserted delivered. Natural 04:30 eligibility, controlled exclusion and receipt-aware migration are regression-tested. Additionally, MATCH separates Official FPL `PROVISIONAL_90` fixture counts from LIVE and FINAL, so GW6 cannot claim 10 games LIVE when they are finished-provisional; `finished=true` remains the only FINAL evidence. Historical GW1–GW6 production coverage and a genuine natural S16B still require remote evidence; no GREEN claim is implied.

- **Native ChatGPT host acknowledgement boundary (13 Oct 2026):** the V12 DEEP consumer now emits typed native blocks, a canonical-text S06 pitch, and a full chunk-path ledger. The old self-attested `user_visible_acceptance=True` cannot elevate a report to `VERIFIED`: only a trusted, signed, same-occurrence ChatGPT-native host event covering every section and chunk may do so. The 07:55 controlled report retains `REMOTE_READBACK_PASS` / `native_ui_acceptance=UNVERIFIED` until that real host event exists. Synthetic unit tests prove gate logic, not production user-visible acceptance. No scheduler, MC500K, P1.7 or historical receipt changes.

- **Public auth source separation (13 October 2026):** V6 prefetch now preserves its legacy credential result and labels that result as PUBLIC_LEGACY_CREDENTIALS. The separately protected rotating-auth state is NOT_EVALUATED_IN_PUBLIC_PLANE until verified by the protected publisher; no public result may imply protected credential expiry or protected authentication success. The existing data boundary and scheduler are unchanged. Required governance suite: 1,379 test nodes.

- **Final persisted receipt proof and latest native parity (13 Oct 2026):** controlled DEEP 06:11 published remote readback PASS but issue proof hashed the pre-readback receipt rather than the byte-identical final private receipt; occurrence manifest showed REMOTE_READBACK_PASS while latest manifest stayed TRANSPORT_PASS. The integrated publisher now rereads the final immutable remote receipt before public proof and updates latest native manifest from the same validated occurrence with full byte parity and hash gate. Required V12 suite is ratcheted to 1,377 cases across 51 files. This does not assert user-visible native rendering or change canonical MC, P1.7, scheduler or past occurrence history.

- **Mode-aware private report readback and required CI ratchet (13 Oct 2026):** MATCH 02:30 failed after a successful private push because the remote validator required a DEEP-only native manifest. The verifier now checks remote occurrence canonical SHA256, receipt identity, and mode-specific latest digest for all modes; only READY_FULL DEEP requires the lossless native manifest/chunk round trip. Non-native MATCH/PRICE and evidence-based degraded DEEP keep native UI acceptance UNVERIFIED. The governed full V12 suite is increased from 50 files/1367 nodes to 51 files/1375 nodes, including 8 mode-specific readback regression cases, without dropping any prior tests. This repairs delivery transport, not the FPL analytics, scheduler authority, or MC500K.

- **Formation MC wrapper binding (12 Oct 2026):** S14 validation now unwraps the canonical `formation_mc.payload` shape used by the producer, while all P1.7 evidence fields are rendered through the human-facing summary path. This preserves the fail-closed delivery barrier and does not change MC500K or route mathematics.
- **Formation MC human-facing QA repair (12 Oct 2026):** S06/S08/S14/S19 now require the canonical Formation MC table whenever bound formation rows exist, and XI/bench values are rendered as human-facing summaries without Python mapping repr. This changes presentation validation only; MC500K, P1.7, scheduler, and private delivery contracts are unchanged.
- **Lossless native manifest/chunk transport (12 Oct 2026):** DEEP native content keeps the legacy full artifact for compatibility and publishes a compact manifest plus line-bound section chunks. Producer round-trip and remote readback are fail-closed; transport PASS never implies native ChatGPT UI VERIFIED without an explicit consumer acceptance receipt.
- **CI trigger note (12 Oct 2026):** controlled S18/S19 verification remains separate from natural acceptance and requires terminal governance evidence on the exact head.
- **Native consumer gate (12 Oct 2026):** the structured consumer now rejects invalid manifests, missing or reordered chunks, and partial section consumption; `VERIFIED` remains unavailable until transport, remote readback, and user-visible native acceptance pass for one occurrence.
- **Controlled acceptance boundary (12 Oct 2026):** a successful private readback still reports `REMOTE_READBACK_PASS`; only a separate user-visible native acceptance receipt may advance the same occurrence to `VERIFIED`.

- **Lossless native-content transport (12 Oct 2026):** for READY_FULL DEEP with a serving report, private publication now emits occurrence-bound `native_content.json` in the report directory and `latest/native_content.json`. It preserves **all 22/23 sections, all Markdown rows, S16 player profiles, evidence wording, original source markup, exact canonical bytes and SHA256**, plus typed blocks for a future ChatGPT-native renderer. Content transport PASS is strictly separate from **native ChatGPT UI acceptance = UNVERIFIED**. No second scheduler, external publication, content cap, or recomputed model values. Regression tests reject missing sections, mismatched hashes and truncated blocks. The consumer must replace source HTML with actual native components and separately verify user-visible fidelity before claiming native FULL GREEN.

- **Canonical captain/vice presentation closure (12 Oct 2026):** S08 is the only final C/VC decision authority for S06 pitch badges. P1.7 formation-frontier optimizer C/VC assumptions and exact xPts remain preserved as separate score provenance and are not silently recomputed; illegal S08 C/VC outside the selected XI fails closed. This repairs the observed 16:18 controlled DEEP S06_S08_VICE_CANONICAL_MISMATCH without suppressing validation.

- **C/VC & evidence presentation integrity (12 Oct 2026):** S06/S08/S19 captain and vice identities must agree before READY_FULL; S02 labels numeric model estimates separately from unavailable exact-slot full-history and P(start) acceptance. S15 cross-section quality now uses the canonical PASS/FULL acceptance vocabulary. ChatGPT native visual 22/22 remains a separate user-visible acceptance gate, not established by embedded HTML/CSS or Markdown QA.

> **Last runtime/documentation sync:** `2026-10-14T04:52:00+07:00`
- **P0 natural 04:30 S16B cardinality repair (14 Oct 2026):** Exact post-match S16B validation now recognizes the legitimate numeric zero for duplicate fixtures rather than coercing zero to -1. It still rejects any duplicate, missing fixture or incomplete OWN15 reassessment. Existing required regression extended without changing collected test-node count. No scheduler, MC, model, latest, or V6 factual owner changes. Change timestamp: `2026-10-14T04:52:00+07:00`; Documentation sync: `UPDATED`; Documentation timestamp: `2026-10-14T04:52:00+07:00`.
- **P0 S02 evidence truthfulness (14 Oct 2026):** Chelsea form is shown as UNAVAILABLE when provider fixtures do not pass cutoff/identity gates, never as 0W-0D-0L. The P(start) differentiation audit recognizes verified player-conditioned historical selection separately from uncalibrated role/manager/availability context. Canonical probabilities, scheduler, latest pointers and model parameters remain unchanged. Change timestamp: `2026-10-14T04:25:00+07:00`; Documentation sync: `UPDATED`; Documentation timestamp: `2026-10-14T04:25:00+07:00`.
- **P0 S02 Chelsea historical presentation contract (13 Oct 2026):** Retrospective GW1–GW6 Chelsea results and verified season-player process observations are retained as labeled narrative rows; only two mandatory S02 Markdown tables remain OUR15 (15) and P(start)/DNP evidence (15), preventing historical context from displacing player identity in visible-body QA. Required regression updated without changing suite count. Change timestamp: `2026-10-13T21:54:00+07:00`; Documentation sync: `UPDATED`; Documentation timestamp: `2026-10-13T21:54:00+07:00`.
- **P0 P(start) individualization and GW1–GW6 evidence recovery (13 Oct 2026):** V12_PLAYER_MINUTES now consumes exact-ID verified match-level selection evidence with provisional rows excluded, preserves explicit missing-evidence states, and exposes separate evidence-binding, coverage, individual-resolution, calibration, temporal-integrity, and production-verification layers. The reviewed governance baseline is updated from 1388 to 1391 only for the three required regression tests added by this change. Change timestamp: `2026-10-13T21:10:00+07:00`; Documentation sync: `UPDATED`; Documentation timestamp: `2026-10-13T21:10:00+07:00`.
- **S15 cross-section evidence quality (12 Oct 2026):** S15 now consumes exact S02 full-history and P(start) acceptance state; unavailable or limited binding downgrades availability evidence to Partial instead of overstating Strong/HIGH.
- **S10 actionable ETA evidence (12 Oct 2026):** unsupported price-change crossings are rendered with an explicit governed state/reason; producer-bound WIB dates remain visible and no missing ETA becomes a forecast or probability.
- **S15B scope integrity (12 Oct 2026):** LEAGUE, RIVALS and COMPETITIVE denominator completeness is now shown as an independent PASS/PARTIAL gate; league coverage cannot mask missing rival evidence.
- **S18 transfer economics integrity (12 Oct 2026):** route alternatives now show PASS/PARTIAL economics completeness across hit cost and 1/3/5-GW net values; unavailable economics cannot be presented as executable.
- **S18 canonical producer binding (12 Oct 2026):** FT consumption, hit points, bank-after, affordability, and executable state are sourced from the canonical transfer-economics object; unresolved values remain unavailable.
- **S19 S08 evidence lineage (12 Oct 2026):** final judgement acceptance is bound to the canonical S08 captain frontier and fails closed on cross-section C/VC or frontier mismatches.
- **P1 S08 canonical PMF shared-world closure (12 Oct 2026):** the full 500,000-path shared-world C/VC simulation now accepts the canonical P1.3B point-PMF route without inventing goalkeeper event calibration. Strict goalkeeper-event validation remains available for direct event-calibration callers; the result exposes an explicit not-required status and convergence gate PASS.\n- **P0 exact-slot prefetch collision repair (12 Oct 2026):** the occurrence orchestrator binds an existing active/queued or terminal-success V6 prefetch for the exact report kind and logical slot before dispatching. This prevents GitHub's one-pending-run behavior from cancelling an unstarted prefetch and producing a zero-job `FAILED_PREFETCH`; failed/cancelled runs are never reused. Scheduler authority, report idempotency, MC500K, P1.7 and full-universe routes remain unchanged.
- **P0 full-season player history (12 Oct 2026, PR #988):** Official FPL element-summary history is retained for the entire bootstrap universe across GW1..N-1, with fixture-level rows, double-GW aggregation, FINAL/DNP/BLANK/PENDING states, provenance, and an explicit coverage gate. Missing or pending evidence is never coerced to zero.
- **P0 PRICE prefetch occurrence isolation (12 Oct 2026, PR #989):** V6 workflow concurrency is keyed by logical occurrence for dispatches and immutable issue-comment ID for commands, preventing a later slot from cancelling an earlier pending PRICE/DEEP prefetch while retaining same-occurrence serialization and `cancel-in-progress: false`.
- **P1 S02 V6 occurrence binding (12 Oct 2026, PR #1007):** full-history serving now consumes only the exact current `full_master` V6 prefetch occurrence, supports the lossless gzip artifact, and fails closed on stale or cross-occurrence history. P(start) evidence cannot be presented as production-bound until this exact artifact binding is present.
- **P1 analytics production acceptance (12 Oct 2026, documentation timestamp 2026-10-12T07:05:00+07:00):** DEEP now carries an immutable acceptance manifest for P(start) evidence, S08 captain frontier state, and the Official FPL full-season GW1..N-1 coverage gate. Evidence completeness is separated from model resolution and LOCK readiness, so PREPARE or LIMITED_RESOLUTION cannot be mislabeled executable or fully calibrated.
- **P1 S02 acceptance binding (12 Oct 2026):** owned-player P(start), DNP, xMins, and V12_PLAYER_MINUTES provenance now flow from canonical projections into the serving acceptance payload; absent source evidence remains PARTIAL/UNAVAILABLE.

A governed Fantasy Premier League decision-support engine combining public football facts, probabilistic modelling, full-universe discovery, squad optimisation, Monte Carlo, mini-league context, and private report delivery.

> **V6 establishes factual truth. Canonical V12 interprets those facts for FPL decisions. Manager-specific state and reports remain private.**

- **P1 S02 cohort start-odds transparency (11 Oct 2026):** the DEEP renderer now flags heavily repeated P(start) values and counts rows without supplemental prior/role/manager/normalized-availability start signals. This is a bounded evidence-resolution warning, **not** a re-fit of football odds, a new source of injury probabilities, or a modification of canonical V12_PLAYER_MINUTES, Stage3, P1.7, MC500K, scheduling, or private authentication. Synthetic regressions cover both uniform and differentiated cohorts. Production DEEP and private receipt must be verified separately.

- **P0 protected OIDC Git-CAS authenticated parent push (11 Oct 2026, PR #980):** natural 19:00 hourly maintenance failed before refresh-token POST because the encrypted IN_FLIGHT marker could not be persisted. The 20:13 controlled prefetch confirmed AUTH_UNAVAILABLE fallback while its isolated private snapshot publisher successfully committed. The CAS marker and READY replacement now push the exact detached-worktree commit SHA through the authenticated private checkout; no force, replay, plaintext, second scheduler, MC500K, or P1.7 changes. Regression asserts the authenticated push base. This is a candidate fix, not FULL GREEN: private live auth, canonical DEEP, Stage3, native natural proof and independent private receipt must still pass postmerge.

- **P1 MC route lineage + captain variance binding (11 Oct 2026, PR #979):** production DEEP 17:49 exposed the remaining projection-only S14 gaps: the canonical 500K convergence checkpoint was present but its simulated route/comparator identity was discarded by Stage3's bounded report surface. S14 now carries `selected_route_id`, `route_ids` and `convergence_route_id` for strict final-checkpoint identity checks, without confusing the MC reference route with Stage3 HOLD or best challenger. S08 displays the existing canonical `pmf_variance` rather than a missing `variance` alias. Two synthetic regressions are added to the required governance suite (reviewed total: 1356 tests). Neither probability model, MC 500K kernel, P1.7, price prediction, V6, authentication, scheduler, nor joint captain simulation was changed. Deployment/controlled and natural/native acceptance remain independent.

- **S05 production rest binding repair (12 Oct 2026):** S05 display rows now consume the occurrence-local canonical workload `days_rest` and fall back to exact Official FPL fixture ordering. This repairs a presentation-only field loss without changing P1.1/P1.3 probabilities or applying a fatigue penalty. Regression coverage proves the production-shaped path cannot report `UNAVAILABLE` when official fixture ordering supplies the interval. Change timestamp: `2026-10-12T15:12:00+07:00`; Documentation sync: `UPDATED`; Documentation timestamp: `2026-10-12T15:12:00+07:00`.

- **P1 additive section QA alignment (11 Oct 2026, PR #978):** controlled DEEP 38132292100 proved post-render QA was rejecting correct new S02/S08/S10 evidence tables under the old 1/2/1 schema. S02's second table is an audit of the same 15 players, not 15 additional owners. Exact DEEP schema now requires 2/3/2 tables with 15/5/15 evidence rows, and the downstream visible-body checker counts the primary S02 roster once while rejecting mismatched audit identities. This preserves fail-closed QA, canonical MC500K/P1.7, private authority and natural scheduler. Production and native acceptance remain separate.

- **P1 section evidence repair (11 Oct 2026, PR #977):** S14's numerical summary reads the final 500K P1.4 convergence checkpoint only when the source-selected route, last simulated horizon, and exact path count match the canonical checkpoint; the report distinguishes the MC reference route from the global decision/HOLD and best challenger. S02/S16 expose existing P1.1 start-signal provenance and DNP without changing probabilities. S10 shows native likelihood per player or NOT_CALIBRATED, not synthetic percentages. S08 displays canonical return tail/variance/DNP and explicitly preserves unavailable joint-C/VC evidence. No P1.7, MC seed/path count/kernel, FPL authentication or scheduling changes. CI, postmerge production recompute, private receipt and natural/native rendering are **separate** acceptance gates.

- **P0 Stage3/OUR15 provenance (11 Oct 2026):** public submitted picks are an explicitly stale, non-financial identity fallback, never editable authenticated CURRENT15. Exact team/GW and live /me + /my-team lineage must be bound before private finance is authoritative; Stage3 only accepts S02 degraded after cross-checking 15 distinct submitted IDs, position counts, XI/bench, C/VC, Official provenance and occurrence timestamp. Wrong identity/fixture facts still fail closed. Natural, native visual and full-green production remain independent acceptance gates. See [Stage3 diagnostics](docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md).

- **GW7 owner what-if MC:** PR #963 tests four paired 500K routes (HOLD, Mbeumo only with assumed 1 FT, Mbeumo + Palmer with -4, and Mbeumo + Saka with -4), using P1.7/P1.4 unchanged, and keeping the full result private. Future mini-league top-3 probability is not modelled; GW6 rival ownership is descriptive, not a probabilistic rank claim.


- **P0 hourly owner identity repair (11 Oct 2026):** the first genuine post-merge natural maintenance attempt was safely blocked because the protected job did not define optional FPL_TEAM_ID. The worker now resolves the exact team 3462711 from committed config/v6/consumer_context.json, rejects any conflicting environment override before reading credentials, and preserves the private/public separation. A nonblocking natural job failure must not be counted as successful token renewal. Subsequent real natural validation remains required.

- **Protected hourly OIDC upkeep (11 Oct 2026, PR #975):** the existing genuine ChatGPT hourly core issues-edit event now has a private downstream maintenance job. It reads encrypted access expiry on every eligible real natural occurrence, reuses a healthy token, and only attempts one CAS-guarded refresh within 15 minutes of expiry. It verifies /me and /my-team/3462711 after rotation and retains report-prefetch's 90-second default. The protected emergency pause applies to both workers; ambiguous rotation remains IN_FLIGHT and requires owner action. This adds no scheduler and never blocks Official public acquisition. CI/merge are not proof that the next real near-expiry grant or native delivery succeeded.

- **OIDC private natural V6 activation (11 Oct 2026):** after real owner-controlled refresh and #19 independent reuse (HTTP 200, version 3 unchanged), protected private V6 prefetch defaults to rotating encrypted OIDC; public collection stays independent. Protected `FPL_PRIVATE_AUTO_REFRESH_PAUSED=true` is an emergency stop. Verified finance-only publication requires bank, FT or explicit unlimited, and 15/15 prices. Stale fallback nulls all unauthenticated economics. Natural V12 and next-expiry rotation/delivery remain separate acceptance gates. See [OIDC security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC second-worker reuse-only proof (11 Oct 2026):** the protected V6 auth probe offers owner-only `REUSE_ONLY` (new runner, encrypted store read, current saved access token only; GET /me and /my-team; never refresh or write ciphertext). Green requires correct identity and no store version change; expired tokens fail safely. See [security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC controlled-first-grant gate (11 Oct 2026):** after encrypted iPhone enrollment, owner may choose `CONTROLLED_ONCE` in existing V6 auth probe to test a single official refresh without enabling rotating auth for natural jobs. Possible Safari session collision must be understood; live grant, persistent rotation, /me identity, subsequent reuse and natural V12 delivery are separately verified. Restored hard cross-CPU governance proof from direct 3-model PASS run 38101198457 (not waived). [Security runbook](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **OIDC rotating auth P0 (11 Oct 2026):** official discovery verified; initial fail-closed rotation core merged in #959. Follow-on opt-in V6 integration adds encrypted private Git CAS secret state and owner-only GitHub Actions enrollment, with key protected as an environment secret. This does not enable real refresh until the owner supplies credentials and explicitly verifies the client policy. See [OIDC security and iPhone steps](docs/security/fpl_oidc_rotating_refresh_20261011.md).

- **Authenticated FT recovery (11 Oct 2026):** V6 private my-team normalizes remaining free transfers from an explicit field or, when absent, from verified `transfers.limit` minus `transfers.made` with bounded integers and explicit provenance. `limit=null` stays UNLIMITED, incomplete evidence stays NOT_SUPPORTED. Never derive private finance from public picks; bearer auto-renewal is a separate unresolved credential-lifecycle task.

- **P0 governance sharding (11 Oct 2026):** preserves the original 49 required V12 test files and 1,345 parameterized node IDs with deterministic, disjoint fail-closed test shards. Exactness-heavy P1.7 reference tests are isolated without changing model mathematics; each job captures per-test durations and CPU identity. The existing `v12-required-verify` branch-protection check remains a mandatory aggregator. PR and postmerge push evidence must both be GREEN before production governance is declared recovered.

## Core architecture

`Official/Public Data → V6 Facts → Canonical V12 → Optimisation → WAIT / PREPARE / ACT → Reports`

- **V6 factual plane:** governed facts, freshness, fixtures, prices, and source evidence.
- **Canonical V12:** xMins, probability, tactics, full-universe scanning, optimisation, Monte Carlo, and decision semantics.
- **Private delivery:** manager-specific squad state, scenarios, mini-league context, decisions, and full reports.

A guarded private FPL auth diagnostic is available via the owner-only `/fpl-auth-probe` command on issue #431. It checks `/me`, the configured entry identity, then `/my-team`, and prints only redacted HTTP statuses and availability flags. An unverified JWT expiry claim does not prove accepted authorization. No credential, private payload, or finance amount is logged or published; `AUTH_AVAILABLE` requires verified HTTP 200 for both endpoints and 15 distinct players. Public MATCH remains independent of this probe.

Canonical FPL entry identity is repository-configured. Authenticated personal acquisition is an optional enrichment for private/current finance facts; when auth is intentionally unavailable, governed Official FPL submitted-picks or explicit owner evidence may still support Current15 identity, while auth-only finance fields remain unavailable.

Stage3 upstream failure diagnostics are documented in [docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md](docs/V12_STAGE3_UPSTREAM_DIAGNOSTICS.md); blocked Stage3 remains degraded and privacy-safe.

When Stage3 is blocked upstream, the report remains explicitly `BLOCKED_UPSTREAM` and records only bounded allowlisted guard predicates plus Monte Carlo path/convergence facts. This diagnostic path never claims Stage3 execution or relaxes the 500,000-path and convergence gates.
Optional precompute, warm-worker, and freeze telemetry is reported with explicit `NOT_APPLICABLE`, `OPTIONAL_UNAVAILABLE`, `REQUIRED_PASS`, or `REQUIRED_FAIL` semantics; missing optional telemetry never becomes a delivery failure or a false PASS.

Stage2 public acceptance binds to the latest occurrence-bound `full_master` prefetch. An ad-hoc personal prefetch cannot mask the public manager-picks evidence required for acceptance.
The V6 private publisher validates the freshly isolated `private-reports/personal/current_team.json` after private-boundary splitting, not the previously saved snapshot. The saved file is used only for a strictly degraded fallback, and logs expose only the safe refresh auth-state classification.
If authenticated personal refresh fails but the exact-occurrence public V6 snapshot is published, report delivery may continue from the existing private last-good personal snapshot. The expired-auth fallback validates age from that saved snapshot, never from the fresh failed-attempt artifact. The report preserves its original GW and timestamp and marks it stale or degraded; auth-only finance fields remain unavailable. Public-core publication or validation failures still block this fallback.

Injury and availability evidence is target-aware and claim-aware. Raw and normalized claims, polarity, training or appearance evidence, manager assessment, target GW or fixture, timestamps and evidence cutoff remain provenance fields; FPL 50%/75% flags are observations, never medical or start probabilities.

Captain distributions now have an optional calibrated goalkeeper event layer and one shared-world C/VC simulation of exactly 500,000 paths. Missing goalkeeper calibration remains explicitly unavailable; no captain winner or goalkeeper event probability is hardcoded.


### Stage C full-universe scanner (11 Oct 2026)

Stage C is enabled for canonical DEEP candidate discovery by the `feature_default_enabled` configuration default; `V12_STAGEC_SCANNER_ENABLED=0` is the deliberate emergency override. The Stage A multiwindow / Stage B shadow / Stage C pipeline scans the full projection input, reconciles unique projection IDs against Official FPL `bootstrap.elements`, and records the Official denominator, eligible denominator, missing/duplicate/unrecognized IDs, position coverage and screening reason codes. Missing or partial evidence is reported as `DEGRADED` rather than claiming full universe coverage. The scanner contributes bounded, provenance-aware candidate intelligence under S04 and route context, not a second Watchlist20 score, transfer authority, P1.7, or Monte Carlo engine. An actual production PASS still requires an occurrence-bound DEEP execution proof, 20-row S11, canonical 500K Monte Carlo, private delivery receipt and matching latest pointer; passing CI is not that proof.

### S05 planning-GW display scope (11 Oct 2026)

Verified 12:27 WIB production S05 completed and passed Stage3, but the visible fixture table included all 380 season fixtures rather than the ten GW7 matches. The integrated report now passes `planning_gw` into the **display-only** fixture projection; only fixtures whose Official FPL `event` exactly matches the planning GW are rendered. Full-season fixture inputs remain available for workload mathematics, source evidence and historical context. An existing regression test now verifies that all ten target-GW cards survive, unrelated-GW/unknown-event rows do not leak, and another GW maps only its own fixtures. The strict conditional S05 table rows/columns QA remains active.

### S05 exact rendered-table verification (11 Oct 2026)

The 49 required V12 files now contain 1,345 parameterized node IDs (five additional S05 regression tests, zero removals); the governance fail-closed manifest baseline has been ratcheted accordingly. S05 can display two occurrence-bound tables: verified Official PL fixture identity and optional verified weather. The presentation lock now requires **exact header columns and complete row counts** for every actually bound S05 table. When weather is unavailable, the weather table is omitted without hiding valid fixture rows; any missing bound fixture, missing bound weather table, extra unauthorized table or malformed column fails closed at final human-facing QA. The strict check repairs the first post-#968 production failure `S05_RENDERED_TABLE_COUNT` without downgrading report validation or changing V12 scoring.

### S05 verified non-PL schedule acquisition (11 Oct 2026)

ESPN scoreboard date ranges `dates=YYYYMMDD-YYYYMMDD` began returning HTTP 400 in September 2026. The S05 report-time acquisition now requests separate calendar months with `dates=YYYYMM`, deduplicates native event IDs, filters verified source events to the exact report window, and retains event-specific source URLs. Any failed monthly response fails its competition coverage rather than being interpreted as zero fixtures; when non-PL authority is still incomplete, S05 remains truthfully `DEGRADED` while Official FPL remains the Premier League fixture authority. This does not alter V6, xPts/xMins, optimiser, Monte Carlo, private finance, or scheduler ownership.

## Reports

Official Public API MATCH adoption (#954) extends V6 per-entry GW facts with Official transfer hit, automatic substitutions, raw submitted picks, verified previous-GW cumulative totals (58 manager histories), fresh fixture/score and event-status snapshots, with source lineage. V12 produces provisional net/live ranks only from verified evidence, never promotes static standings to live, and remains independent of private /me and /my-team authentication. [Endpoint inventory and remaining proof requirements](docs/official_public_api_inventory.md). The production FULL GREEN acceptance still requires a verified exact-occurrence prefetch, 58/58 hit/baseline coverage, 13/13 rendered sections and delivery receipt.\n\nMATCH public-first recovery: the canonical V12 runner previously accepted DEEP/PRICE only and rejected governed MATCH requests before creating report artifacts. An isolated MATCH adapter now consumes exact-occurrence Official FPL V6 submitted picks (11 XI, 4 bench), GW live points, all 58 ICON+ managers, and displays the 13 locked MATCH sections including fixture scores, MATCH10 exposure and MATCH13 source status. Auth-only bank/FT/purchase/selling values remain unavailable on AUTH_EXPIRED; provisional gross scores are explicitly not verified net league ranks until transfer hit/autosub authority is complete. No private session, P1.7, MC 500K, chip ledger, or scheduler behavior changes.


S06 mobile pitch displays the entire already-calculated **CURRENT15** P1.7 formation frontier (including 3-4-3 where a legal canonical row exists), not only two leading routes. Formation xPts remain unchanged. Missing rows are explicitly labelled unavailable. DCL→Barry and DCL→Gonzalo are roster-transfer scenarios **not computed** by the S06 presentation change; each still requires validated finance, legality, canonical lineup optimization and full 500K MC before any recommendation. GW6 team news from 20 clubs and 113 player signals is ingested as bounded secondary evidence via the existing P1.1 adapter. V6 facts and P1.7 decision ownership are unchanged.

**DEEP** is the full planning report, **PRICE** handles price/timing, **DEADLINE / FINAL** is the final pre-deadline checkpoint, and **MATCH** covers post-deadline and matchday monitoring.

Primary schedule: **DEEP 04:30 / 12:30 / 21:30 Asia/Jakarta** and **PRICE 23:30 Europe/London**. Deadline and Matchday use governed checkpoints. T-24 through T-3 bind to the official deadline and emit one occurrence-bound DEEP report; T-2 through T-5 remain delta/final overlays.
ChatGPT automation `FPL Master Monitor V12` is the sole recurring scheduler, running every HH:30 Asia/Jakarta. At each genuine natural occurrence, its **first production-side effect** is the governed update of issue #431 TITLE with the exact hourly logical slot, followed by title readback. This triggers the V6 core via `event=issues`; report-prefetch cannot substitute for scheduler health. For due DEEP/PRICE or verified live MATCH checkpoints, the same master may post exactly one occurrence-bound `/fpl-master-tick` comment on #431 after verifying no existing exact-slot command/receipt. The downstream GitHub issue-comment orchestrator runs report prefetch, V12, QA and private publication, but cannot prove user-visible native delivery on its own. No independent GitHub clock/cron, ad-hoc replay, or alternate scheduler is authoritative. PRICE remains bound to 23:30 Europe/London (DST-safe).

Occurrence commands are exact-time only: future report slots are rejected, and private serving state created before its claimed occurrence cannot satisfy idempotent reuse.

S09 chip availability is fail-closed: a missing/`UNAVAILABLE` chip ledger is **not** evidence that Bench Boost, Wildcard, Triple Captain or Free Hit remains usable. Only explicitly verified `AVAILABLE`/`UNUSED` entries appear as remaining; incomplete states are labeled unresolved without guessing. This affects presentation only, not the canonical chip decision or authenticated source authority.

S18 action board keeps all six canonical decision axes and projects the best-alternative route as a bounded, two-column decision table (route, outbound/inbound names, executable status, hit, 1/3/5GW net deltas, P(beats HOLD), robustness). Mini-league evidence (football EV priority and rank-gain utility) remains visible in a small labeled subsection. The full optimizer route stays intact in its original canonical evidence; no nested matchup/route dictionaries are dumped in the mobile-visible S18 presentation. Missing values remain UNAVAILABLE; this is presentation-only and does not change ACT authority or Monte Carlo.

The S18 production human-facing presentation lock now derives an **exact** one-table route contract and optional second mini-league evidence table from the *bound canonical route fields*. It verifies column order, 13 mandatory route labels, matching mini-league row labels, and exact row/table counts, rejecting missing or unexpected tables instead of weakening validation. This closes the `S18_RENDERED_TABLE_COUNT` production failure observed during controlled DEEP at 19:45 WIB on 9 Oct 2026. No change to route mathematics or MC.

S08 human-facing QA is state-aware: `LOCK` requires visible `Current C:` / `Current VC:` labels, while `PREPARE` and other non-locked states require `Current C baseline:` / `Current VC baseline:`. This preserves explicit provisional captain identity without weakening rendered-content acceptance.

## Captain risk and mini-league review

For a CLOSE football frontier, a goalkeeper captain with weaker 10+ haul
probability and Q90 than an equally secure attacking alternative is marked
PREPARE rather than falsely LOCKed. A review pair is shown, never automatically
executed. LEAGUE / RIVALS / COMPETITIVE captain share and EO, denominator
coverage, current rank/gaps and PROTECT/BALANCED/ATTACK posture are reported
as observed historical mini-league context; they are not target-GW forecasts
or a substitute for correlated captain/vice Monte Carlo. Missing scopes and
unverified GK clean-sheet/conceded/saves/bonus/penalty-save calibration remain
explicitly unavailable. S08, S18 and S19 must share the canonical C/VC.

## DEEP decision-content delivery barrier

DEEP is occurrence-bound, provenance-aware, privacy-safe, and may degrade explicitly when evidence is unavailable rather than inventing data. Its visible renderer is presentation-lock driven: the header carries report identity only, S04 owns material news/developments, S14 is bounded to optimizer/search evidence, S15 owns decision-evidence quality, S17 owns technical health/freshness/lineage, and mini-league context uses the dynamic Competitive Window.

## PRICE human-facing delivery barrier

PRICE follows the same factual/provenance boundary and never invents unavailable manager state or decision output.

## Captaincy

Captaincy is now distribution-first: S08 compares legal selected-XI candidates using canonical P1.3B one-GW return distributions, treats Phaul as the existing P(points ≥ 10) tail rather than a second weighted signal, and classifies the football frontier as CLEAR, CLOSE, or FRAGILE. Mini-league LEAGUE/Competitive Window exposure may break only a CLOSE football decision when standing-gap context is complete; EO never overrides a clear football edge, and nonnumeric competitive EO is treated as unavailable rather than coerced. S15B is evidence-only, while S08, S18, and S19 consume one canonical C/VC decision. Cross-player joint correlation and candidate-specific relative-points captain MC are not currently fabricated when unavailable.

## Governance

The engine scans the **full eligible FPL universe**, separates facts from inference, preserves uncertainty, and keeps manager-specific state private.

**Current-state authority** comes from governed CI/runtime evidence and `runtime-data/data/runtime_manifest.json`; this README and `MASTER_TASK_LIST_V3.md` are only a **human-readable projection**.

Detailed methodology, formulas, evidence weighting, privacy, scheduler, delivery architecture, presentation contracts, P4/P6, cache behaviour, and performance governance live under `docs/v12/`.

Delivery authority: `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`  
Schedule authority: `config/delivery/v12_delivery_schedule.json`

> **Caveat:** this is a decision-support system, not an oracle. FPL outcomes remain stochastic and source evidence can change quickly.


## DEEP captain presentation integrity (9 October 2026)

The canonical captain frontier remains distribution-first and position-neutral. When the goalkeeper captain is classified CLOSE and the decision is PREPARE, the DEEP S08 and S19 surfaces label the named C/VC as a **provisional baseline**, not a locked or executable captain recommendation. The existing attacking review challenger (when available) is explicitly displayed as an advisory candidate, with the goalkeeper-event calibration and shared-world relative-points evidence still required before lock. A genuinely LOCKed captain retains the canonical display contract. S08, S18 and S19 must remain consistent. This change does not alter P1.7, MC 500k, squad optimisation, or mini-league exposure mathematics.

## S19 cross-position captain decision visibility (9 October 2026)

S19 FINAL JUDGEMENT now renders the canonical S08 captain frontier for all
eligible selected-XI positions (GK/DEF/MID/FWD), especially CLOSE decisions.
The bounded comparison shows xPts, P(blank), P(10+), Q90, P(start), xMins
and evidence completeness without new weights, invented probabilities,
arbitrary xPts near-tie thresholds, or a second captain owner. Competitive
Window posture and tie-break status are explicitly identified as secondary
to canonical football distributions. LOCK means a canonical resolved C/VC;
PREPARE labels the displayed C/VC as provisional, not executable.
The S19 human-facing gate rejects missing or reordered CLOSE-frontier
evidence relative to S08. This change does not touch P1.7, MC 500k,
universe/routes, S16B, scheduler, private publisher, or PR #809.

## S19 seven-layer captain acceptance boundary (9 October 2026)

The S19 judgement now exposes the owner-approved seven evidence layers:
canonical xPts; PMF-derived P(10+)/P(15+), Q75/Q90 and multiple-return
availability; P(blank)/P(DNP)/P(start)/xMins; variance and head-to-head
with explicit cross-player dependence assumptions; Competitive Window plus
actual relative-rank simulation status; C/VC fallback plus joint-simulation
and vice-activation status; and explicit evidence-confidence status.
Unimplemented event-joint multiple returns, covariance, or rank MC
must show UNAVAILABLE. A canonical LOCK is not automatically proof that
all seven layers have complete evidence. S19 must state PARTIAL_EVIDENCE
where those inputs remain unresolved. No new CaptainScore, EO-derived
points, position preference, substitute optimizer, or fabricated MC.

## CLOSE captain production LOCK evidence guard (9 October 2026)

A CLOSE football frontier may preserve or recommend an eligible, owned
C/VC provisionally, but observed captain/EO percentages must not certify
the pair as LOCK. The existing canonical captain reconciler now requires
a valid shared-world C/VC simulation with exactly 500,000 paths and an
explicit convergence PASS; an exposure-driven switch also requires
simulated mini-league rank consequences. Until these checks pass the state
is PREPARE, and S08/S18/S19 must label the selected pair provisional.
This does not forbid goalkeeper captaincy: a robustly CLEAR GK can still
LOCK. No new CaptainScore, changed P1.7, pseudo-consensus or fabricated
relative-points estimates are introduced.

## Seven-layer captain permanent CI regression gate (9 October 2026)

The required V12 verification suite explicitly includes goalkeeper-tail,
cross-position seven-layer visible-report, and distributional captain
frontier governance tests. It rejects false CLOSE LOCK when real joint
C/VC confidence or mini-league rank evidence is unavailable, preserves
valid CLEAR goalkeeper captains, and checks S08/S19 consistency.


**GW6 what-if transfer / formation matrix (10 Oct 2026):** `python -m src.engines.v12_transfer_matrix --output artifacts/gw6_transfer_matrix.json` enumerates 42 roster combinations, including **Konsa→Lewis Hall** with/without Tavernier→Saka and Bruno→Mbeumo, over all eight P1.7 legal formations (**336 rows**); previous Davis/Castagne/Mykolenko alternatives remain for comparison. Hall's Newcastle identity and £5.3m price come from public V6 predictor (addendum `config/intelligence/gw6_hall_candidate.json`). Hall frees an Arsenal slot when Saka enters. With illustrative stale-value £0.2m bank, Bruno→Mbeumo + Tavernier→Saka + Konsa→Hall is indicatively £0.2m short; DCL→Barry changes that to +£0.1m, whereas DCL→Gonzalo changes it to -£0.3m. Private bank, selling price, free transfers and hits are **not authenticated**. Only the no-transfer baseline has verified 500K P1.4 MC. All what-ifs require distinct canonical P1.7 and 500K MC before action. No CURRENT15, P1.7, MC engine, scheduler, or private delivery mutation.


**GW6 P1.4 3-4-3 MC closure (10 Oct 2026):** The private DEEP what-if step now materializes the exact P1.7 3-4-3 winner per GW with the unchanged canonical bench-order and captain/vice evaluator. Correlated P1.4 runs 500,000 paired worlds for optimized HOLD, DCL→Barry, DCL→Gonzalo and three explicitly fixed 3-4-3 lineups; captain challenger remains optional. Output is a private `gw6-forward-mc.json` attached to the DEEP occurrence, not a bank/FT/transfer authorization. Tests exercise route-specific outcomes and fail-closed formation completeness. Personal finance and hits remain unavailable pending authenticated V6 evidence.


Public Official FPL submitted picks, live data, and mini-league evidence are independent from authenticated personal enrichment. When private authentication is expired, public MATCH delivery continues with explicit unavailable finance fields; authenticated bank, free transfers, purchase prices, and selling values are never derived from public data.

### P0 public-first natural delivery repair (2026-10-11T05:57:00+07:00)

PR #957 isolates the known live command parser failure: audited `reason` metadata is bounded and `MATCH` routes to governed `match_mode` with exact `latest/match.json` verification. Canonical MATCH terminality remains fail-closed on publication, body hash, QA and private receipt; private personal authentication is **not** a public-report prerequisite. In S15B, Official FPL can assign tied league ranks, so Top 10 displays exact first-ten standings positions while retaining actual rank values and rejects missing/duplicate entries. No QA relaxations, MC/universe reductions or alternate scheduler are permitted. Controlled CI, generated Markdown and private latest **do not** prove natural ChatGPT delivery; require genuine scheduler title mutation, exact issue command, orchestration, same-slot prefetch and rendered native user-visible evidence. Historical missing slots remain missing.

- **Stage3 temporal-integrity and OIDC store diagnostics (11 Oct 2026):** an explicit DEEP Stage3 `acceptance_class=INTEGRITY_FAIL` is now forbidden to publish as `READY_FULL` (including `S02_OBSERVATION_TIMESTAMP_INVALID` on an after-slot retry). Independent engineering-only Stage3 closure remains advisory under report-first. Owner-only auth diagnostic `STORE_HEALTH` reads encrypted credential phase/version and coarse expiry metadata without making a refresh request, writing secrets or pretending natural success. Keep natural/receipt/MC500K/P1.7 untouched and use this read-only gate before any possibly destructive re-enrollment.
- **OIDC STORE_HEALTH connected-control command (11 Oct 2026):** control issue #431 accepts the exact owner-only comment `/fpl-auth-probe STORE_HEALTH` as an alias for the existing read-only `STORE_HEALTH` diagnostic. It checks only encrypted-store metadata; it never issues an OIDC grant, refreshes credentials, writes the store, exposes tokens, or counts as natural scheduler proof.



### V6 full-history request isolation (12 October 2026)

Official element-summary acquisition now retries each player request within a bounded budget and records per-player failures without aborting the full universe. Partial coverage remains explicitly PARTIAL/UNAVAILABLE, never promoted to PASS; this repairs request-fanout failure isolation without changing historical completeness gates or report semantics.

### P0 Official fixture lifecycle classification (12 October 2026)

MATCH now distinguishes Official FPL `LIVE`, `PROVISIONAL_90`, `FINAL`, `NOT_STARTED`, and fail-closed `UNKNOWN` states using lifecycle fields. A postponed fixture remains `NOT_STARTED` with an explicit `POSTPONED` substate. Finality is never inferred from minute 90 alone, and future-dated official snapshots are rejected before MATCH rendering.


### S08/S15B rivals-scope gate (12 October 2026)

Captain tie-breaks now require complete LEAGUE, RIVALS and COMPETITIVE scopes. Missing RIVALS coverage remains fail-soft and cannot apply a competitive override or certify a CLOSE captain decision.

## S15B competitive scope integrity

The V12 S15B delivery boundary rebinds the COMPETITIVE denominator to the resolved rank-relative cohort and available rival picks for the current occurrence. LEAGUE and RIVALS remain separate scopes, so legacy league-sized metadata cannot masquerade as Competitive Window coverage.
- **Controlled verification metadata (12 Oct 2026):** S18/S19 acceptance requires current PR governance metadata and exact occurrence-bound evidence.
- **S19 documentation lineage trigger (12 Oct 2026):** canonical S08 evidence binding is verified independently from controlled occurrence acceptance.

- **S19 runtime acceptance binding (12 Oct 2026):** acceptance metadata is rebuilt from the rendered canonical S08 object before S19 validation.


- **S18 rule-engine hit-cost binding (12 Oct 2026):** missing authenticated hit-cost metadata now resolves from the active verified Official FPL ruleset; unresolved rule metadata remains fail-closed.


- **Native UI receipt boundary (12 Oct 2026):** producer and remote evidence never substitute for a user-visible native component acceptance receipt.
