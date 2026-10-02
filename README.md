# FPL iphoenk Engine

> **Last runtime/documentation sync:** `2026-10-03T06:24:42+07:00`
> **Production main at sync:** `95241f03303c6ff25f6118bc783236d431ad5fe9`  
> This timestamp records when this human-readable README was reconciled with the repository. Live runtime health and current production evidence come from the active workflows and runtime artifacts, not from this timestamp.

A governed Fantasy Premier League decision engine that separates **public football facts and reproducible compute** from **private manager-specific state and decisions**.

The active architecture is deliberately simple:

- **V6** owns the factual data plane.
- **Canonical V12** owns analytics, probability, tactics, optimization, decisions, and report semantics.
- **Private delivery** owns manager-specific state and decision output.

The core principle is:

> **V6 tells V12 what is factually true. V12 decides what those facts mean for FPL.**

Mandatory integrated DEEP delivery is fail-closed on same-occurrence factual binding: the exact governed V6 report-prefetch must reach terminal SUCCESS and be read back from runtime-data-v6 before `/v12-report-run` is started. Unrelated issue comments are isolated from governed V6 concurrency so they cannot replace a pending prefetch.

Scheduled visible-report handoff is single-trigger and event-driven: the owner-only `/fpl-master-tick` occurrence command is handled by `.github/workflows/fpl-master-occurrence-orchestrator.yml`, which dispatches the existing governed V6 report-prefetch and canonical V12 integrated runner with one unique request identity, waits for both exact child runs, verifies the same-occurrence private serving publication, and writes a durable non-private receipt to issue #431. The orchestrator has no cron and is not a second scheduler, model, optimizer, factual plane, or publisher. Repeated commands for an already-ready occurrence reuse the existing private delivery state instead of recomputing the report. The receipt proves backend occurrence completion; user-visible delivery remains a separate ChatGPT-side acknowledgment barrier.

Occurrence delivery integrity is mode-specific and hash-bound. DEEP verifies the exact per-occurrence `serving_report.md`, the current `latest/report.md` pointer, the private delivery receipt, and the canonical body SHA-256 as one identity. PRICE is DST-bound to 23:30 Europe/London and verifies its exact per-occurrence `report_body.md`; it never assumes `latest/report.md` belongs to PRICE because the generic serving pointer may still reference the latest DEEP occurrence. Public occurrence receipts carry the exact private history path and canonical body hash for downstream exact-slot retrieval without digest substitution.

Occurrence idempotency trusts only orchestrator receipts authored by `github-actions[bot]`; arbitrary public issue-comment text cannot satisfy the ready-receipt guard. The scheduler independently requires exact occurrence identity and private receipt evidence before visible delivery.

DEEP user-visible presentation is governed by `config/delivery/v12_deep_presentation_lock.json`. The locked contract preserves the approved 23-section human analyst layout, exact Scanner20/RISE20/FALL20 row contracts, S15B numerator/denominator/percentage semantics, S01↔S19 reconciliation, and the current S16B lifecycle. Canonical engine/audit artifacts may retain machine codes, but the visible DEEP report must not fall back to generic recursive key/value dumps or expose raw internal structures as primary wording.

Mandatory visible DEEP delivery is also fail-operational at the presentation boundary: orchestration and the integrated runner both guard exact-slot prefetch terminality, the runner performs a bounded runtime-data-v6 re-fetch before declaring upstream blockage, and a due occurrence must publish one truthful 23-section private report as either `READY_FULL` or `READY_DEGRADED`. Degraded output never fabricates Stage3/MC proof, marks only the actual root stage failed, labels reused analytics `PRIOR`, and can be atomically upgraded to `READY_FULL` for the same occurrence. Private `latest/report.json`, `latest/report.md`, and `latest/delivery_status.json` form the canonical serving surface for ChatGPT/web/mobile consumers.

Report-first production now separates **REPORT PROD** from **ENGINEERING** acceptance. A DEEP occurrence is publishable when the canonical 23-section report, presentation/human-facing QA, truthful CURRENT/PRIOR provenance, S01↔S19 consistency, and serving snapshot pass. P4 scenario closure, PERF-F latency, warm-cache benchmarks, and the 53 technical-gate closure remain mandatory engineering evidence but are not publication prerequisites. This changes delivery gating only; V6 factual authority and Canonical V12 decision mathematics remain unchanged.

The integrated report delivery lane materializes only the private serving surface required at runtime: `personal/`, `latest/`, and `reports/`. Engineering-only `acceptance/` and `scenarios/` are excluded from report-lane checkout; this changes I/O only and does not weaken report production, privacy, provenance, or analytics gates.

Canonical DEEP section assembly is source-resolved per section in the locked order **CURRENT → CURRENT-BOUND → PRIOR → UNAVAILABLE**. `CURRENT-BOUND` requires exact lineage, unchanged dependencies, and mathematical applicability proof; `PRIOR` always carries its source occurrence and is historical context only. All 23 resolved sections are provenance-validated before rendering, so stale analytics cannot be silently relabelled as current.

`serving_report.json` is the stable client-facing contract for ChatGPT/web/mobile. Schema v2 carries occurrence/report slot/GW, delivery and decision status, freeze time, source freshness, per-section states, lineage and supersedes. Canonical artifacts are validated before any private `latest/` pointer replacement; a candidate that fails report-production, presentation, or governed credential/privacy validation cannot overwrite the last-known-good serving snapshot.

Production report workflow treats Stage3/P4 closure as **engineering evidence only**. Stage3 execution still runs and records PASS/FAIL/DEGRADED truth, but its nonzero result cannot override a passing REPORT PRODUCTION GATE. The final human-delivery verdict depends on successful private report publication plus allowlisted public operational proof, not on P4/PERF-F closure.

Private publisher failures emit only bounded allowlisted reason codes to operational logs. REPORT_PRODUCTION_GATE failures expose gate identifiers only; unknown publisher exceptions are reduced to a generic failure code, so delivery incidents can be repaired from evidence without leaking private report content or credentials.

Client serving JSON uses an explicit presentation projection for the canonical 23 DEEP sections. Heavy audit/reproducibility structures remain in the private canonical `report_bundle.json`; the client artifact preserves presentation semantics and provenance while enforcing a low-single-digit-MiB regression ceiling.
S19 carries the canonical operational decision token alongside its human-readable final judgement so the fail-closed S01↔S19 consistency gate compares the same authoritative WAIT/PREPARE/ACT state without weakening presentation semantics.

Delivery, privacy, latency, historical-validation and consumption architecture are governed by `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`. Revision 6 supersedes earlier Delivery Architecture Plan wording where inconsistent.

Visible delivery timing is machine-governed by `config/delivery/v12_delivery_schedule.json`: DEEP at 04:30/12:30/21:30 Asia/Jakarta, PRICE at 23:30 Europe/London with DST-safe WIB conversion, exact deadline checkpoints, quiet-hour handling, single-report overlap, and T-15/T-10 precompute timing.

Cross-CPU governance now uses a verified frozen direct-proof registry: a transitive PASS is allowed only when the registered GitHub run/artifact is revalidated, the proof commit is an ancestor, protected semantic paths are unchanged, and normalized runtime/output remain identical. Semantic changes still require a direct current-head multi-CPU proof.

D-P2 precompute control is owner-triggered and non-authoritative: it has no cron, cannot edit the core scheduler title, cannot complete or advance a core slot, and may only hand the unchanged future report occurrence to the existing governed V6 `report_prefetch` path at the Revision-6 T-15 window.

D-P3 crypto preparation defines a private-only AES-256-GCM boundary for manager-specific P1.7/MC caches. Production owner execution selects the encrypted profile explicitly; non-main branch acceptance selects no-personal-cache and receives no decrypt key. Persistent P1.7/MC cache files are authenticated `*.aead.json` envelopes only, with restored non-AEAD files rejected. It remains preparation until exact-head CI, production-key availability, governed encrypted reuse, semantic-equivalence, and natural post-merge acceptance pass.

P4 scenario-materialization failures expose only bounded whitelist diagnostics: scenario/override identity, safe QA or stage codes, non-sensitive cache state, exact lineage hashes, report slot, and hash-only semantic fingerprints. CURRENT15 payloads, private report bodies, decrypted cache contents and secrets are never part of the failure diagnostic surface.

When a canonical scenario returns `PARTIAL`, the same diagnostic surface records only the names of failed Stage3 boolean guards, allowing bounded root-cause repair without exposing private decision payloads or weakening the Stage3 acceptance contract.

Exact occurrence binding preserves the governed report-slot timestamp without rounding half-hour DEEP slots to the hour. P4 failure diagnostics also retain only the exact public Git lineage object IDs for production and runtime-data commits, while semantic fingerprints remain SHA-256-only.

Scheduler production maturity is established after **3 consecutive genuine natural ChatGPT hourly occurrences**. Historical natural proofs remain immutable; manual recovery, controlled runs, and report-prefetch never increment this maturity counter, and an observed gap remains a scheduler-health failure. Runtime epoch metadata is refreshed from the current schedule policy on each accepted natural slot while preserving the original epoch start.

FACT-1/FACT-2 hardening separates live/provisional bonus from final Official FPL bonus/event state, and treats Official set-piece notes as occurrence-bound advisory evidence only. `finished_provisional` is never finalization authority; set-piece evidence cannot directly overwrite xMins, xPts or P(start).

Stage2 public live acceptance consumes the already-published post-deadline Official FPL mini-league manager-picks factual surface for current-squad identity; it does not require or recreate `data/v6/personal/*` in the public runtime.

PERF-0 freezes latency measurement before optimization: closure requires 6 comparable canonical production-main DEEP executions. Natural and controlled production-equivalent executions may qualify, but controlled runs never count as scheduler proof and branch acceptance is excluded. p90 remains informational until n>=10. Exact app/runtime lineage, runtime/cache class and observable CPU/runtime metadata are preserved, while queue, startup, setup, factual acquisition, Stage-2, P1.2A, P1.2B, P1.7, MC, render, QA, private publish and total timing remain distinct. Controlled COLD runs use `SECURE_NO_PERSONAL_CACHE`, do not restore or persist personal-decision caches, and do not receive the production decrypt key.

P4/PERF-F occurrence binding is now immutable for P4-consuming acceptance: the private P4 package records the exact `runtime-data-v6` commit and logical report slot used to build it, and PERF-F checks out that exact runtime commit instead of a later branch HEAD. This prevents hourly factual publication from retroactively changing S15B/mini-league semantics during closure.

P4 scenario schema v4 also persists compact scenario-specific P1.8 rebind inputs. During selective OUR15/P4 serving, only the downstream mini-league overlay is re-evaluated against the current warm mini-league snapshot and S15B is rebound canonically for the same report occurrence; football-route authority, canonical 500k MC, cache policy, and QA remain unchanged.


P4 canonical scenario packages precompute a bounded private BASE_CURRENT15 plus exact OUR15/C/VC unavailability counterfactual set. Each scenario persists the mandatory decision core plus every canonical report section that actually changes versus BASE_CURRENT15, together with canonical Stage3 action, so P6 warm delivery cannot serve a mixed baseline/scenario surface. P6 applies those persisted changes copy-on-write, rebuilds the governed serving artifacts, and reruns all delivery QA barriers without deep-copying the multi-megabyte frozen model state. Occurrence-relative S03 state is preserved truthfully: a scenario with no valid previous visible DEEP baseline remains DEGRADED with the numeric-delta guard instead of being promoted to COMPLETE. Persisted packages use a small manifest plus bounded gzip JSON scenario shards, so private serving does not depend on Git LFS or a monolithic multi-gigabyte blob. Reuse is fail-closed against model, OUR15, GW/fixture, projection-lineage, cache/schema, MC-authority, and owner-context fingerprints; manager-specific package payloads remain private. Production P4 rebuilds restore the same deterministic Stage-2 cache and encrypted AEAD P1.7/MC caches already produced by the integrated runner under identical semantic cache-key families; cache misses still recompute canonically, and restored non-AEAD private files fail closed. P4 workers bind those cache families through the canonical owner environment names `V12_P17_DECISION_CACHE_DIR` and `V12_MC_SIM_CACHE_DIR`, with `SECURE_ENCRYPTED_PERSONAL_CACHE` and the single `FPL_V12_PRIVATE_CACHE_KEY_B64` secret contract; legacy P4-only cache aliases are forbidden by regression tests. Each P4 counterfactual also runs in a fresh spawned child (`max_tasks_per_child=1`) while the outer pool remains capped at two concurrent workers, preventing process-local memoization or mutable module state from crossing scenario boundaries. Controlled PERF-F cold recomputation is pinned to the same normalized BLAS/NumPy runtime class as P4, so exact semantic equality is not polluted by cross-runtime floating-point boundary drift. Independent counterfactuals are evaluated by at most two isolated canonical worker processes using spawn semantics and unique scenario output/cache namespaces, then reassembled through the unchanged deterministic package builder; parallelism changes wall-clock scheduling only, not MC 500k, route universe, scenario coverage, or decision semantics.\n\nP6 warm execution is bounded below six hours, downstream-only, and fail-closed. D-P2 handoff is occurrence-bound; PERF-F measures warm T0 through validated private publication and requires canonical cold semantic equality. PERF-F mismatch diagnostics expose only SHA-256 fingerprints per governed semantic component and component names; they never log private report payloads. P4 selective serving preserves the exact canonical section binding for the same report occurrence and rejects wrong-slot bindings fail-closed, avoiding post-serialization fingerprint rebinding drift. New owner-issued P4 builds supersede obsolete in-progress P4 commands, and the builder revalidates exact production main immediately before private publication so stale packages cannot overwrite the current private scenario authority.\n\nCache invalidation is governed by a frozen four-state dependency matrix: `HIT`, `MISS`, `PARTIAL_INVALIDATION`, and `NOT_APPLICABLE`. Selective reuse is permitted only with explicit dependency keys; uncertain scope falls back to MISS, and every warm path must remain semantically equal to canonical cold output. `MINI_LEAGUE_ONLY` reuses the frozen Stage2, exact P1.7 and canonical 500k MC state, recomputes only the P1.8/downstream decision and presentation surfaces, then re-runs the full render, QA and final-delivery barriers.

## Questions it answers

1. Who should start, sit on the bench, captain, and vice-captain?
2. Which transfer or transfer package improves the squad over 1, 2, 3, and 5 gameweeks?
3. How secure are a player's minutes and starting probability?
4. What do underlying numbers, tactical role, opponent matchup, set pieces, penalties, workload, and recent match evidence imply?
5. Which players are breaking out, regressing, or becoming materially more relevant across the full FPL universe?
6. How do price movement, affordability, free transfers, hits, regret, and reversal risk affect a decision?
7. How should mini-league exposure, captaincy, overlap, differentials, and direct rivals alter decision utility without overriding stronger football evidence?
8. What changed after each match, and should the action remain **WAIT**, move to **PREPARE**, or become **ACT**?

## Architecture

| Plane | Responsibility | Production status |
| --- | --- | --- |
| **V6 factual plane** | Official/public football facts, source normalization, freshness, identity, fixture and price evidence | Active |
| **V12 analytics plane** | xMins, start probability, position-specific probability components, posterior distributions, tactical/role evidence, post-match interpretation | Active |
| **V12 decision plane** | XI/bench, captain/vice, transfer packages, Monte Carlo, staging, mini-league overlay, final action | Active |
| **Private delivery plane** | Current squad state, private finance, exact routes, XI/bench/C/VC, chips, scenarios, full reports | Active |

The public repository may contain source code, models, reproducible football facts, non-sensitive QA/proof, performance metadata, and public-safe caches. Manager-specific state and decision material must remain outside the public factual plane.

## Decision model

The engine does not reduce player evaluation to one headline stat. Current decision surfaces combine four evidence families:

| Evidence family | Weight |
| --- | ---: |
| Proven / historical | 20% |
| Tactical / role | 25% |
| Current underlying | 30% |
| Fixture / security | 25% |

Those surfaces feed the downstream probability, lineup, transfer-package, Monte Carlo, and mini-league layers. Missing evidence is surfaced as unavailable or degraded rather than silently replaced with invented values.

## What the engine measures by position

Every player is evaluated with shared foundations such as **availability, xMins, P(start), role security, fixture context, recent trajectory, price/value, uncertainty, and multi-GW projection**. The event model then changes by FPL position instead of applying one generic formula to everyone.

| Position | Main measured / modelled components |
| --- | --- |
| **GK** | xMins and P(start); shots on target faced; save-count distribution; save percentage; P(3/6/9/12+ saves); expected save points; clean-sheet probability; goals-conceded distribution; penalty-save probability; BPS/bonus behaviour; opponent shot volume and pressure |
| **DEF** | xMins and P(start); clean-sheet probability; goals-conceded downside; DefCon probability and defensive workload; xG/npxG, xA/xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; aerial and set-piece threat; attacking full-back/wing-back role; BPS/bonus |
| **MID** | xMins and P(start); xG/npxG, xA/xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; goal and assist processes; penalty involvement; set-piece role; clean-sheet point probability; DefCon contribution; tactical creation/transition matchup; BPS/bonus |
| **FWD** | xMins and P(start); xG/npxG and goal-generation process; xA and assist process; xGI; shots, shots in box, shots on target, big chances, box touches; key passes/chances created; penalty involvement; set-piece and aerial threat; striker/runner role versus high line, central centre-backs and transition weakness; BPS/bonus |

The matchup layer is role-aware. Examples include runner vs high defensive line, central striker vs central centre-backs, aerial target vs aerial weakness, creator vs weak central pressure, winger vs vulnerable full-back, attacking full-back vs narrow defence, set-piece target vs weak set-piece defence, and goalkeeper vs opponent shot volume.

The model also keeps FPL scoring mechanics explicit, including appearance points, clean sheets, goals conceded, save intervals, DefCon, goals, assists, cards, own goals, penalty misses/saves, and stochastic bonus rather than applying a generic final-point uplift.

## Mathematical and probabilistic core

The engine is intentionally distribution-first. It does not jump directly from raw statistics to one xPts number. The main chain is:

`facts -> availability/minutes states -> posterior event rates -> position-specific event distributions -> exact FPL point PMF -> lineup/package consequences -> correlated Monte Carlo when required -> WAIT / PREPARE / ACT`.

### 1. Canonical football score

The football-only comparison score is fixed to the Canonical V12 evidence weights:

```text
FootballScore
  = 0.20 × Proven/Historical
  + 0.25 × Tactical/Role
  + 0.30 × Current Underlying
  + 0.25 × Fixture/Security
```

Each component is bounded to `[0,100]`; the four weights must total exactly `1.0`. Transfer economics, price timing and mini-league leverage are downstream and are not allowed to rewrite this football baseline.

### 2. Start probability and xMins

Starting probability is not one manually assigned percentage. Multiple signals are pooled in **log-odds space**.

For each start signal `p_i` with weight `w_i`:

```text
logit(p)   = ln(p / (1-p))
pooled_logit = Σ[w_i × logit(p_i)] / Σ[w_i]
raw_P_start_given_available = sigmoid(pooled_logit)
sigmoid(x) = 1 / (1 + exp(-x))
```

The observed season start rate is shrunk toward the neutral prior:

```text
season_start_rate
  = (observed_start_rate × matches + neutral_prior × shrink_matches)
    / (matches + shrink_matches)
```

Rotation and congestion then modify the conditional start probability:

```text
P(start | available)
  = raw_P_start_given_available
    × (1 - rotation_risk × rotation_strength)
    × congestion_factor

P(start) = P(available) × P(start | available)
```

Appearance is represented as a finite-state mixture rather than a single minutes estimate:

```text
states = START, CAMEO, LATE_CAMEO, ZERO_MINUTES

xMins = E[M] = Σ_s P(s) × E[M | s]

Var(M)
  = Σ_s P(s) × (Var(M | s) + E[M | s]^2)
    - E[M]^2
```

The published minutes uncertainty combines state-mixture variance with calibration uncertainty. Entropy of the four appearance outcomes increases the minutes uncertainty when the state probabilities are diffuse.

### 3. Bayesian-style shrinkage of event rates

Observed per-90 rates are not trusted at full strength in small samples. Current evidence is shrunk toward a governed prior:

```text
posterior_rate90
  = (bounded_observed_rate90 × observed_minutes
     + prior_rate90 × shrink_minutes)
    / (observed_minutes + shrink_minutes)

shrinkage_share
  = shrink_minutes / (observed_minutes + shrink_minutes)
```

Early-season extreme rates are winsorized before shrinkage. Historical player priors can themselves be blended with position priors when evidence is available.

Credible-rate intervals use a Gamma-rate approximation. Missing evidence remains prior-only or unavailable rather than being silently converted to zero.

### 4. Count distributions: Poisson vs Negative Binomial

For count events, the basic Poisson model is:

```text
P(X=k) = exp(-λ) × λ^k / k!
```

The engine empirically switches to a Negative Binomial family when the recent sample is sufficiently over-dispersed:

```text
use Negative Binomial when: