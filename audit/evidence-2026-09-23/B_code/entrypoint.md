# Evidence metadata
source: .github/workflows/v12-integrated-report-runner.yml at main; src/engines/v12_integrated_report_runner.py at PR #668 head
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: AVAILABLE

`src/engines/v12_integrated_report_runner.py:2189-3650` - `run_deep`
`src/engines/v12_integrated_report_runner.py:3651-3696` - `main`

Workflow normal invocation, line 230:
`python -m src.engines.v12_integrated_report_runner "${args[@]}"`

Workflow COLD profile invocation, lines 217-219:
`python -m cProfile -o artifacts/v12-report/profile.pstats -m src.engines.v12_integrated_report_runner "${args[@]}"`
