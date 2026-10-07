# V12 Occurrence Terminality Contract

The natural occurrence orchestrator classifies collected, allowlisted publication evidence through one canonical downstream classifier:

- READY_FULL requires full runner status and every existing exact-slot, QA, delivery, publication, integrity, privacy, and report-readiness boundary.
- READY_DEGRADED permits runner_status=PARTIAL only when the publisher emits READY_DEGRADED, the degradation has a known attributable governed reason, Stage3/P4 engineering closure is report-first and non-blocking, and all human-facing, private-delivery, exact-publication, historical-artifact, latest-advancement, digest, privacy, and football-mathematics boundaries pass.
- FAILED_VERIFY remains fail-closed for ungoverned partials, delivery or QA failures, wrong slots, missing publication, digest mismatch, privacy or authority violations, fabricated evidence, and mandatory football-mathematics failures.

The orchestrator collects historical path, size, body SHA, canonical SHA, receipt, digest, latest-body and Stage3 evidence before classification. This preserves forensic technical evidence even when classification fails. The classifier does not acquire facts, run models, schedule occurrences, or create a second publisher.
