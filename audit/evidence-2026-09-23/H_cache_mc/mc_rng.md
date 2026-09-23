# Evidence metadata
source: src/engines/v12_monte_carlo.py at PR #668 head + run 35748919665 production artifact
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: AVAILABLE

RNG constructor: `np.random.Generator(np.random.PCG64(int(seed)))`.
`canonical_package_seed`: hashes projection fingerprint, football route signature excluding economics, and correlation model version; returns `int(digest[:8], 16)`.
Production artifact seed: `4133427706`; `common_random_numbers=true`; `actual_paths=500000`.
Parallel shards: `np.random.SeedSequence(int(seed)).spawn(workers)`; one uint64 child seed per shard. Each shard evaluates all material routes against the same sampled football world. Linux start context: `fork`. Results are sorted by shard index before concatenation.
Published seed policy: `EXPLICIT_FIXED_INTEGER_PER_EXECUTION`.
