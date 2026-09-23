# Evidence metadata
source: audit assembly from GitHub source, Actions runs, production artifacts, and compliant workflow_dispatch audit benchmark
commit_sha: 918da08b892320592b9d51684e0130933a6fbb7a
timestamp_utc: 2026-09-23T13:38:53Z
status: AVAILABLE

# V12 DEEP evidence bundle

| Item | Status | Path |
|---:|---|---|
| 1 | AVAILABLE | `A_snapshot/snapshot.json` |
| 2 | AVAILABLE | `B_code/entrypoint.md` |
| 3 | AVAILABLE | `B_code/code_index.md` |
| 4 | AVAILABLE | `B_code/multiprocessing.md` |
| 5 | AVAILABLE | `B_code/samples/` |
| 6 | NOT AVAILABLE | `C_routes/route_universe.json` |
| 7 | AVAILABLE | `D_e2e/workflows_index.md` |
| 8 | AVAILABLE | `D_e2e/issue431_protocol.md` |
| 9 | AVAILABLE | `D_e2e/timeline_run_*.json` |
| 10 | NOT AVAILABLE | `D_e2e/chatgpt_consumption.md` |
| 11 | AVAILABLE | `E_env/python_env.txt; numpy_config.txt; thread_env.txt; lscpu.txt` |
| 12 | AVAILABLE | `E_env/importtime.txt` |
| 13 | NOT AVAILABLE | `F_perf/bench_668_*` |
| 14 | NOT AVAILABLE | `F_perf/pstats/` |
| 15 | AVAILABLE | `F_perf/run_35858764611_failed_step.log` |
| 16 | NOT AVAILABLE | `F_perf/cold_profile_19_15/; F_perf/cold_profile_19_40/` |
| 17 | NOT AVAILABLE | `F_perf/controlled_cold_deep_raw.json` |
| 18 | AVAILABLE | `G_tests/golden_tests.md` |
| 19 | NOT AVAILABLE | `H_cache_mc/cache_fingerprint.md` |
| 20 | AVAILABLE | `H_cache_mc/mc_rng.md` |

Audit branch base at creation: `918da08b892320592b9d51684e0130933a6fbb7a`.
PR #668 head frozen for this audit run: `03abbdd9e4a1f662d4bb92f588808247d8790892`.
GitHub REST returned 30 commits for PR #668 at capture time, while the task text said 22; all returned commits are preserved in item 1.
No push was made to main, runtime-data-v6, or PR #668 head branch.
Item 16 remains NOT AVAILABLE as a complete item because the terminal 19:40 artifact does not contain a top-level `profile.pstats`; raw summaries and available stage-local pstats are retained.
MANIFEST.json omits its own checksum to avoid self-reference. Raw binary/original artifact files carry source/SHA/time metadata through MANIFEST.json.
