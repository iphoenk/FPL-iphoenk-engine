# V3 Exhaustive Search Finalization

V3 keeps the interactive FAST serving SLO separate from exhaustive transfer-package search completeness.

The canonical decision scorer remains `src.models.package_optimizer_v2.score_package`.

The exhaustive finalizer:

- scans the complete eligible Official FPL projection universe;
- permits candidate pruning only within the same Official team and FPL position;
- requires lower-or-equal price, no-lower mean and no-higher standard deviation for every decision-bearing GW before pruning;
- treats missing per-GW evidence as non-prunable;
- exactly scores every legal single and two-transfer package after that proven non-lossy pruning;
- applies the existing sequential cash and squad-legality contract;
- regenerates `package_decision.json` through the existing `build_package_decision` owner;
- never changes projection, xPts, DSS, tactical or lineup-scoring semantics;
- runs outside the interactive FAST wall-clock measurement and before production publication.

`search_authority=FULL` is allowed only when diagnostics prove no single/pair budget, no exact package cap and `lossy_pruning=false`.
