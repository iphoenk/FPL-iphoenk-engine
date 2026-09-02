# V3 Understat QA/QC checklist

- [ ] Registry compiler passes with no undeclared capability or multi-writer drift.
- [ ] Source parsing/schema validation tests pass.
- [ ] Rolling 1/3/5, season, home/away and small-sample shrinkage tests pass.
- [ ] PPDA remains derived/contextual and never directly changes xPts.
- [ ] Full Official FPL universe mapping is attempted across GK/DEF/MID/FWD.
- [ ] Unresolved player mappings remain UNKNOWN, never zero.
- [ ] Understat source failure is fail-soft and truthfully exposed.
- [ ] FAST profile performs no Understat network refresh.
- [ ] XI/bench/formation influence is close-call only and legal.
- [ ] Captaincy semantics remain unchanged by Understat.
- [ ] Watchlist membership cannot be promoted by Understat alone.
- [ ] Transfer-package evidence has no transfer/hit authority.
- [ ] Serving exposes Understat health/evidence without recomputing decisions.
- [ ] Full V3 regression and release acceptance pass.
- [ ] FAST <3s acceptance remains green.
