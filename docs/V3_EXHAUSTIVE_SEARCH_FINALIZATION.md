# V3 Exhaustive Search Finalization

V3 keeps the interactive FAST serving SLO separate from exhaustive transfer-package search completeness. The canonical decision semantics remain owned by `src.models.package_optimizer_v2`; exhaustive execution may use differential-locked accelerators only when they preserve that surface exactly and fail back to the canonical scalar scorer at ambiguous numerical boundaries.

## FULL search authority

`search_authority=FULL` means the search originates from the complete eligible Official FPL projection universe and uses **zero candidate pruning**. FULL production search does not use watchlists, discussed-player targets, benchmark packages, fixed top-N lists, single-move seeds, candidate budgets, pair budgets, or exact-package caps.

`safe_per_gw_dominates` is research/diagnostic evidence only. Same-team/position, lower price, no-lower per-GW mean and no-higher per-GW standard deviation is not a sufficient proof of package-level robust dominance because lineup selection, captain selection and aggregate variance can change at package level. It must therefore never remove candidates from a FULL production search.

The exhaustive finalizer:

- scans the complete eligible Official FPL projection universe;
- excludes only entries that are not eligible under governed Official status/identity constraints or are already owned;
- enumerates every single replacement from the complete eligible pool for the outgoing position;
- enumerates two-transfer candidates directly from `outgoing pair × complete eligible incoming position pools`, independent of constituent single-transfer legality;
- uses only exact structural impossibility filters for aggregate cash and final club-cap violations before sequential validation;
- validates transfer execution order step by step with exact sell values, incoming prices, running ITB and club limits;
- for its guarded hot path, uses an exact sequential-legality adapter only under prevalidated invariants (legal current squad, unique non-owned incoming players and position-preserving replacements), with canonical-helper fallback outside those invariants and differential regression coverage;
- scores every sequentially legal package under the canonical package-scoring semantics;
- builds the efficient frontier from **all evaluated legal packages**, never only the retained publication top-N;
- regenerates `package_decision.json` through the existing `build_package_decision` owner and requires Gate0 revalidation;
- never changes projection, xPts, DSS, tactical or lineup-scoring mathematics.

## Exact execution acceleration

The optional `ExactBatchScorer` is an execution accelerator, not an independent scoring authority. It uses the same governed scoring context and is differential-tested against `CompiledPackageScorer`. Candidates near formation ties or three-decimal floating-point publication boundaries are re-scored by the canonical scalar scorer. Retained publication/decision surfaces must be canonically revalidated before authority is published.

Parallelization, batching and chunking are execution mechanisms only. They may not change the universe, remove candidates, change legality, alter scoring semantics or make a lossy frontier approximation. Partition-local exact Pareto skylines may be merged because the Pareto frontier of a union is exactly the frontier of the union of each partition's local frontier.

## Truthfulness gates

`search_authority=FULL` is allowed only when runtime diagnostics prove all of the following:

- `candidate_pruning_applied=false` and `candidate_pruned_count=0`;
- `lossy_pruning=false`;
- no single/pair/exact-package budget or cap is applied;
- pair generation does not depend on legal-single seeds;
- every sequentially legal package is scored under the canonical scoring semantics;
- the efficient frontier input is `ALL_EVALUATED_LEGAL_PACKAGES`;
- final package decision passes Gate0 revalidation.

Performance failures must not be hidden by increasing authority, widening timeouts, weakening SLOs, introducing top-N/caps, or silently degrading intelligence. If exhaustive evidence is incomplete, authority must remain PARTIAL/DEGRADED rather than publishing a false FULL state.
