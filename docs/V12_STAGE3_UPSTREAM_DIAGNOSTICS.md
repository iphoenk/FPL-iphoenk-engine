# Stage3 upstream failure diagnostics

When the integrated report runner is blocked before Stage3 executes, the workflow writes a truthful `DEGRADED / BLOCKED_UPSTREAM` acceptance record. It reads only the same occurrence's private `execution_proof.json`.

The public diagnostic payload may contain only allowlisted aggregate guard identifiers and Monte Carlo facts: executed path count, canonical pass state, convergence status, and the three convergence stability booleans. It always records `stage3_executed=false`, `stage3_pass_claimed=false`, and `mc_pass_claimed=false` for this branch.

Unknown guard strings and personal data such as team identity, finance, credentials, or player-level private evidence are not copied. If the proof is missing or invalid, the report remains degraded and the absent aggregate facts remain unavailable.

This diagnostic does not change the Monte Carlo threshold or path count, execute Stage3, bypass analytics or QA gates, or convert the historical 8 October stability failure into a pass. A successful runner continues through the existing Stage3 acceptance validator.
