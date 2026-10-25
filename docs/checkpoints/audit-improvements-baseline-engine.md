# Audit improvements baseline (G00) - engine

Captured 2026-10-25 (Asia/Jakarta, evening) after F01-F06 and E01-E04 landed. Pack: `FPL-Improvement-Claude-2026-10-25`. Figures are a snapshot, not live facts. The dashboard baseline is in `iphoenk/fpl-iphoenk-dashboard` `docs/checkpoints/audit-improvements-baseline.md`.

## Source

| Item | Value |
|---|---|
| Repo | `iphoenk/fpl-iphoenk-engine` |
| HEAD at capture | `2c6186fab9b953a852b86d0a934c808a3cb9a3ab` (PR #1198, E04) |
| Python | 3.13.17 locally |
| Main CI at capture | 20 success, 10 skipped, no failure |

Note: this baseline was taken after the work above, not before it. It records the state the next tasks start from, not the pre-audit state.

## Landed under the pack

F01 #1184, F02 #1187, F03 #1189, F04 #1190, F05 #1191, F06 #1192, E01 #1193, E02 #1194, E03 #1196, E04 #1198 (partial). Merged means in main with CI green; none is deployed or confirmed in production by this document.

## Local checks at HEAD

| Command | Result |
|---|---|
| `python -m src.runtime_v6.domains.governance.authority_contract` | exit 0 |
| `python -m src.runtime_v6.domains.governance.architecture_independence_validate` | exit 0 |
| `python src/platform/repository_test_naming_validate.py` | exit 0 |
| `pytest tests/test_p0_5_deadline_report_plane_stage1.py` | 1 failed, 17 passed |

Known failing test on main: `test_14_single_degraded_field_does_not_remove_structural_section` (`assert 'FAIL' == 'PASS'`). It fails locally on unmodified main and predates the pack; main CI is green, so CI either does not run it in this form or the result depends on the environment. Cause not investigated; not fixed here.

## Environment-dependent failures (sandbox with 2 CPUs)

| Test | Observation | Attribution |
|---|---|---|
| `test_lineup_distributional_optimizer.py::test_p17_cross_route_batch_2043_routes_five_gw_under_ten_seconds` | 11.06 s vs 10 s limit on unmodified main | machine speed, shown by running on main |
| `test_monte_carlo_engine.py::test_canonical_500k_parallel_runtime_acceptance` | `assert 2 == 4` | worker count vs 2 CPUs; not re-run on main, so unproven |

`fastapi` is not installed locally, so `tests/test_live_service_security.py` cannot be collected here.

## Not covered by this baseline

The full pytest suite was not run end to end at this HEAD; only the targeted files above and the 19-file regression set used for E04 (614 passed there, with the failures listed above). CI is the authority for the full suite.

## Open PRs relevant to the pack

#1171 canonical V12 decision service (blocks E05; not mine), #1172 occurrence reconciliation (draft), #1168 V12-R source evidence bridge (draft), #1199 external clock trigger (inactive). Dependabot PRs are unrelated.
