# V3.39 P0–P2 End-to-End Housekeeping Audit

Status: candidate branch only; PR #155 remains unmerged.

Audit scope: coding, workflows, registries, runtime orchestration, bounded microservices, shared primitives, artifact ownership, persisted state, compatibility paths, duplicate-compute risk, and release gates.

## 1. Canonical runtime topology

The active background runtime remains exactly seven execution domains and twenty-one capability owners. Domains are orchestration/process boundaries, not alternate business owners.

| Domain | Capabilities | Audit result |
|---|---|---|
| ACQUIRE | official_snapshot, rules, team_state, market_state, live_state | PASS — authoritative acquisition/rules/state split remains explicit |
| ENRICH | advanced_stats, base_snapshot, authenticated_official, historical_prior, tactical_context, source_layer | PASS — enrichment evidence separated from native Official authority |
| MODEL | prediction, prediction_evaluation | PASS — isolated workspace; historical decision snapshot is now declared input to evaluation |
| MARKET | price, official_detail | PASS — isolated workspace; price model and Official detail remain separate purposes |
| DECISION | lineup_governance, challenger | PASS — governed XI/package and challenger evidence remain separate owners |
| GOVERNANCE | governance, watchlist | PASS — final health/governance precedes external DSS watchlist publication |
| PUBLISH | reporting, report_materializer | PASS — reporting owns decision evidence/arbitration; materializer remains serving-only |

Interactive lane: exactly one active interactive service, `unified_fastpath`. `decision_hotpath_service` and `instant_serving` remain compatibility entrypoints/helpers only; no second interactive business owner exists.

## 2. Twenty-one service audit

| # | Service | Core responsibility | Inputs/outputs/ownership audit |
|---:|---|---|---|
| 1 | official_snapshot | core Official FPL public snapshot | PASS; sole core public snapshot owner; downstream consumers reuse artifact |
| 2 | rules | active FPL ruleset/compliance | PASS; Gate0/rules constants remain registry/rules owned |
| 3 | team_state | team, finance, chip factual state | PASS; consumes Official snapshot; no projection ownership |
| 4 | market_state | market/universe factual state | PASS; produces canonical price/universe base artifacts |
| 5 | live_state | current live factual state | PASS; Official snapshot consumer |
| 6 | advanced_stats | advanced stat sync + normalized player features | PASS; feature contract remains decision-neutral except explicit REC opt-in |
| 7 | tactical_context | observed tactical team/player materialization | PASS; single tactical evidence materialization owner |
| 8 | base_snapshot | deterministic base fan-in | PASS; staged multiwriters retain one declared final owner |
| 9 | historical_prior | previous-season prior | PASS; no fabricated missing history |
| 10 | source_layer | machine source/enrichment health | PASS; Official remains native authority; challengers fail-soft |
| 11 | price | price prediction/trajectory | PASS; separates Official factual fields from modeled timing |
| 12 | prediction | xMins/xPts/team strength/package candidate generation | PASS; xMins canonical primitive explicitly points to `src.models.xmins_v3` |
| 13 | authenticated_official | optional private Official precision | PASS; separate network purpose; not required for public factual history |
| 14 | official_detail | Official detail/history expansion | PASS; scoped network owner, no core Official refetch duplication |
| 15 | prediction_evaluation | frozen forecast settlement/calibration | FIXED; `decision_validation_snapshots.json` now explicit isolated-domain input |
| 16 | lineup_governance | legal XI, bench, C/VC, chip/package governance | PASS; latest-file contract preserved; stale target-GW chip override rejected |
| 17 | challenger | external/internal challenger scorecard | PASS; advisory comparison owner, not final transfer authority |
| 18 | governance | framework health + overlays + evidence maturity | FIXED; persisted artifacts/latest keys now explicitly declared; active probes no longer recompute via legacy model modules |
| 19 | watchlist | DSS-generated external 20-player watchlist | PASS; downstream of governance; 5 per position contract retained |
| 20 | reporting | decision-first report + enrichment + genuine predeadline snapshot | FIXED; snapshot command/artifact now declared; arbitration and snapshot ownership explicit |
| 21 | report_materializer | compact/deep serving artifacts | PASS; may reduce fields but cannot create football decisions |

## 3. P0–P2 ownership additions

`FINAL_DECISION_ARBITRATION` is a reporting-owned shared governance primitive implemented by `src.engines.decision_arbitration`. It is not a service and cannot become an alternate XI/captain/chip/transfer owner.

`PREDEADLINE_DECISION_SNAPSHOT_EVIDENCE` is reporting-owned evidence implemented by `src.engines.prediction_decision_snapshot`; `prediction_evaluation` is consumer-only. This prevents capture/settlement ownership ambiguity.

`XMINS_DISTRIBUTION` remains prediction-owned and now names `src.models.xmins_v3` as the canonical implementation.

## 4. Bugs/debt found and fixed by this audit

1. Reporting module-batch executed `prediction_decision_snapshot` while service registry omitted the command and output artifact. Fixed.
2. Isolated MODEL `prediction_evaluation` read `decision_validation_snapshots.json` without declaring it as an input. Fixed; historical genuine decision evidence can now be seeded into MODEL workspace.
3. P2 writer emitted decision snapshot schema v2 while artifact contract still enforced v1. This had been invisible because the artifact was undeclared. Fixed to schema v2 while keeping the additive `DECISION_VALIDATION_SNAPSHOTS_V1` contract identifier.
4. Snapshot owner string incorrectly implied prediction-evaluation ownership. Fixed to `reporting.decision_snapshot_evidence`.
5. `decision_arbitration` was active but absent from architecture shared-primitives registry. Fixed as reporting-owned shared governance.
6. `decision_hotpath_service.py` physically duplicated canonical `unified_fastpath` lineup/package regeneration. Collapsed to a thin compatibility facade.
7. Active framework-health service still reached legacy `src.models.projection` and `src.models.optimizer` through compatibility audit probes. Active service now overrides xMins, projection and structural probes to validate canonical artifacts/rules without legacy formula recomputation.
8. Governance service wrote multiple persisted artifacts but declared none. Fixed by declaring framework health, external consensus, competitive load and DSS operational evidence artifacts plus their latest keys.
9. During registry editing, `lineup_governance.latest_file_keys` was accidentally dropped transiently and immediately restored before acceptance; a regression guard now freezes the expected contract.

## 5. Workflow audit

`v3-ci.yml`: active V3 pull-request/push validation. Compile, architecture contract, no-duplicate ownership, complete pytest suite, operational LKG hydration, composite FULL+FAST acceptance and unified interactive benchmark remain required.

`v3-runtime.yml`: canonical V3 scheduled runtime. Master evaluation at minute `:30`; support wakeups `:00/:15/:45` are gated by collector timing governance and do not themselves imply visible reports.

`fpl-engine.yml`: inert compatibility marker only; no schedule. Retained to avoid breaking historical references.

`v4-prediction.yml`: V4-only scheduled gate; explicitly checks out `v4-prediction-engine`.

`v4-timing-probe.yml`: V4-only timing probe; explicitly checks out/calls V4 branch. It is not a V3 runtime owner.

No workflow discovered creates a second V3 production runtime owner.

## 6. Registry audit

- Gate0: exactly 16 fail-closed checks.
- DSS core: exactly 50 active modules.
- DSS extensions: exactly 16.
- Enhancement layers: exactly 8; ENH-08 now explicitly includes final cross-layer arbitration.
- REC registry: 43 entries including split REC-09a/09b; no duplicate IDs.
- Official endpoint ownership: exactly four scoped network purposes — core snapshot, public detail expansion, historical prediction settlement, authenticated private precision.
- Source registry: Official FPL remains native authority; machine challengers/enrichments cannot override native fields; OneFPL machine collector remains disabled/delegated to report-time web.
- Report-time source registry: ten enabled sources; advisory/context authority ceilings remain distinct from native Official authority.
- Report artifact registry: 15 owned + 20 watchlist, tactical context, model validation, weather/report-time context and personal gameweek context remain required.
- Execution profiles: fast/live may reuse bounded enrichment artifacts but cannot change football formulas; full/deep refresh disable reuse.
- Performance SLO: sub-second applies to validated warm serving, not external-network full refresh; correctness cannot be traded for latency.

## 7. Orchestrator audit

The domain orchestrator validates service DAG and exact domain coverage before execution. MODEL and MARKET are the isolated parallel domains. Isolated workspaces are seeded only from each capability's declared `inputs` and `artifacts`; fan-in promotes only declared artifacts and selected `latest` keys. Therefore input/output declarations are executable contracts, not documentation.

The domain runner executes critical capabilities fail-closed, validates declared outputs after each service/batch, clears stale outputs for non-critical failures, and records per-capability timing/reuse diagnostics. Module batches are now regression-tested for exact equality with service-registry command lists.

## 8. Compatibility and retirement status

Intentional compatibility-only modules retained:
- `src.engine`
- `src.engines.decision_intelligence_v313`
- `src.engines.decision_hotpath_service` — now thin facade to unified fastpath
- `src.runtime_v3.instant_serving` — compatibility entrypoint plus freshness/serving helpers reused by unified fastpath

Legacy business implementations still physically present for compatibility/retirement sequencing:
- `src.models.projection`
- `src.models.fixture`
- `src.models.optimizer`

They are forbidden from active service command ownership. Active framework-health no longer invokes legacy projection/optimizer formulas. Physical deletion is intentionally deferred until all external/import compatibility references are proven removable; deletion is not required for current production ownership correctness.

## 9. New regression invariants

`tests/test_runtime_registry_alignment.py` now freezes:
- module-batch ↔ service command equality;
- existence of every active command module;
- retired business modules excluded from active service commands;
- decision snapshot producer/consumer/hydrate/publish/schema/owner alignment;
- governance persisted artifact declarations;
- lineup latest-file contract;
- exact 7-domain / 21-service single assignment;
- V3 workflow owner and inert compatibility workflow semantics;
- reporting ownership of decision arbitration;
- explicit snapshot/xMins canonical ownership;
- decision-hotpath delegation to unified fastpath;
- active framework-health override of legacy formula probes.

## 10. Acceptance rule

This audit does not authorize merge by itself. PR #155 remains unmerged until its latest head passes the complete V3 CI and before/after decision-equivalence review. Predictive accuracy is still data-dependent: no settled-sample accuracy claim may be fabricated merely because engineering/architecture gates are green.
