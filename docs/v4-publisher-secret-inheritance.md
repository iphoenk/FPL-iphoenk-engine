# V4 governed runtime publisher secret inheritance

The canonical V4 production-gate caller and scheduler must pass repository Actions secrets into the reusable V4 core with `secrets: inherit`.

The reusable core remains the only governed publisher authority and mints the dedicated GitHub App token from `V4_RUNTIME_APP_PRIVATE_KEY`. No fallback PAT, relaxed branch protection, model-semantic change, optimizer-width change, DSS change, tactical change, or calibration-threshold change is introduced by this operational fix.

The governance serialization optimization retains the existing service contract and only suppresses the intermediate maturity-health write when governance immediately persists the final normalized health artifact.

High-churn machine runtime contracts are serialized compactly to reduce process-boundary JSON I/O. This changes whitespace only: decoded payloads, schemas, decision semantics, optimizer breadth, DSS coverage, tactical evidence, and governance acceptance remain unchanged.
