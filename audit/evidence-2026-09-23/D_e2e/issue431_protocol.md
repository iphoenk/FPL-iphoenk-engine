# Evidence metadata
source: Issue #431 comments + current V12 workflow + run 35858764611 job 107173580175
commit_sha: 918da08b892320592b9d51684e0130933a6fbb7a
timestamp_utc: 2026-09-23T13:07:57Z
status: AVAILABLE

Command poster observed: account `iphoenk`.
V12 command form observed: `/v12-report-run report_mode=DEEP report_slot=<slot> checkpoint_time=<time> [profile_mode=COLD]`.
Parser gate: `.github/workflows/v12-integrated-report-runner.yml:40-45`; parse job uses embedded Python.
Completion step name: `Publish compact completion proof to issue 431`.
Completion command in Actions job: `gh issue comment 431 ...`.
Completion poster observed: `github-actions[bot]`.
