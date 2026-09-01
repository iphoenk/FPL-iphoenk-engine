# V4 governed runtime publisher

V4 production compute runs on the canonical `v4-prediction-engine` branch and publishes runtime artifacts atomically to `runtime-data-v4` through the dedicated GitHub App publisher boundary.

Reusable-workflow callers that request production publication must propagate the repository/environment credential context with `secrets: inherit`. The reusable core remains the sole owner of token minting and publication. Do not replace this boundary with direct human writes, a generic PAT, or an alternate runtime writer.

Production acceptance requires both successful canonical validation and successful runtime publication verification. A successful compute with a failed publisher is not GREEN production and must be reported as stale/degraded serving authority until a fresh governed runtime snapshot is present.
