# Evidence metadata
source: GitHub source at PR #668 head
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: AVAILABLE

P1.2B/P1.7: `src/engines/v12_package_utility.py:964-1205`. Production-sized route sets call `optimize_lineup_horizons_exact_batch`; emitted proof sets `worker_count: 1`. Small-set fallback is sequential and also emits worker_count 1. No active process-pool handoff is present in that branch of `_materialize_route_lineups`.

P1.4: `src/engines/v12_monte_carlo.py:2470-2481`. Start method is `fork` via `mp.get_context("fork")`. `ProcessPoolExecutor(max_workers=workers, mp_context=fork_context, initializer=_init_mc_parallel_worker, initargs=(projections, route_defs, tuple(horizons)))`. Task item is `(shard_index, path_count, child_seed)`. `workers=min(requested worker_count, os.cpu_count(), actual_paths)` with lower bound 1.
