# V3 Understat QA/QC checklist

Candidate proof from V3 CI #855 (2026-09-02):

- [x] Registry compiler passes with no undeclared capability or multi-writer drift.
- [x] Source parsing/schema validation tests pass.
- [x] Rolling 1/3/5, season, home/away and small-sample shrinkage tests pass.
- [x] PPDA remains derived/contextual and never directly changes xPts.
- [x] Full Official FPL universe mapping is attempted across GK/DEF/MID/FWD from the canonical Official snapshot.
- [x] Unresolved player mappings remain UNKNOWN, never zero.
- [x] Understat source failure is fail-soft and truthfully exposed.
- [x] FAST profile performs no Understat network refresh.
- [x] No second Understat decision consumer/process owner exists; canonical `tactical_decision_consumption` is reused.
- [x] XI/bench/formation influence remains inside the existing tactical close-call contract and legal candidate universe.
- [x] Captaincy scoring/eligibility/DNP guard/authority remain unchanged; no Understat-specific captaincy formula exists.
- [x] Watchlist membership cannot be promoted by Understat alone; existing close-call tactical reranking is reused.
- [x] Transfer/challenger evidence has no independent transfer/hit authority.
- [x] Serving exposes the resulting canonical tactical context and source health without recomputing decisions.
- [x] Full V3 regression and composite release acceptance pass: 681 tests passed.
- [x] FAST consistency remains below 3s: 2.664s / 2.582s / 2.580s.
- [x] Unified interactive serving remains below 1s: median 25.6ms, max 167.2ms.
- [ ] Production publication source-commit proof after merge.
- [ ] Fresh `runtime-data` Understat artifacts and source-health reconciliation after merge.
