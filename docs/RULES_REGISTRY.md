# Official FPL Rules Registry

The rules registry is the canonical source of season-specific FPL game rules used by the engine.

## Architecture

`config/rules/registry.json` selects the active ruleset.

`config/rules/fpl_2026_27.json` stores season-specific values for squad constraints, legal lineups, scoring, defensive contributions, chips, finance/sell value and BPS changes.

`src/rules.py` is a loader/calculation library. It must not become the authority for season-specific numeric constants.

`src/engines/rules_compliance_audit.py` validates registry integrity, provenance, semantic invariants and optional remote-source drift. Remote changes never auto-mutate the ruleset.

`src/engines/framework_health_audit.py` consumes the audited rules registry before Gate 0. Gate 0 reads budget, position counts, club limits, legal formations, bench rules and chip constraints from the active ruleset.

## Decision order

Official FPL Rules Registry
-> Rules Integrity / optional Drift Review
-> Engine + Data Health
-> Gate 0 Preflight
-> DSS Core 50
-> DSS Extensions
-> Optimizers / candidate generation
-> Enhancement Layers / governance
-> Gate 0 Postflight
-> GO / HOLD / WAIT / REJECT

Any registry-integrity failure is fail-closed for GO. A remote-source drift signal is REVIEW_REQUIRED and blocks an unqualified GO until reviewed; it does not auto-edit rules.

## Season update process

1. Add a new season file, for example `config/rules/fpl_2027_28.json`.
2. Verify every section against Official FPL sources and update `rule_provenance`.
3. Run `python -m src.engines.rules_compliance_audit` and the full test suite.
4. Change only `active_ruleset`, `season` and `rules_file` in `config/rules/registry.json` after review.
5. Run the production collector and confirm Framework Health reads the new ruleset before Gate 0.

Do not edit Gate 0, optimizer budget logic or scoring constants separately when the underlying FPL rule changes. Their consumers must read the active registry.

## Optional remote drift check

Run:

```bash
python -m src.engines.rules_compliance_audit --check-remote
```

This records conservative fingerprints of the declared Official source pages and compares them with the prior persisted source state. Because editorial page changes can be unrelated to rule changes, the remote check is opt-in and only raises REVIEW_REQUIRED. It never changes the active ruleset automatically.
