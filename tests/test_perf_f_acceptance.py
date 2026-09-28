from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from src.engines import v12_p6_runtime
from src.engines.v12_integrated_report_runner import refresh_mini_league_only_state
from src.engines.v12_perf_f_acceptance import (
    _case_inputs,
    _mutate_price,
    _mutate_role,
    execute_case,
)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _team():
    return {
        "players": [
            {
                "element_id": element,
                "captain": element == 1,
                "vice_captain": element == 2,
            }
            for element in range(1, 16)
        ]
    }


def test_price_case_mutates_real_official_predictor_field(tmp_path):
    runtime = tmp_path / "runtime"
    path = runtime / "data/v6/current/official_price_predictor.json"
    _write(
        path,
        {
            "data": {
                "players": [
                    {
                        "id": 1,
                        "price_change_percent": "90.0",
                        "price_change_projections": [
                            {"offset": 0, "projected_percent": "90.0"}
                        ],
                    }
                ]
            }
        },
    )
    keys = _mutate_price(runtime, [1])
    row = json.loads(path.read_text())["data"]["players"][0]
    assert keys == ["price:1"]
    assert row["price_change_percent"] != "90.0"
    assert row["price_change_projections"][0]["projected_percent"] != "90.0"


def test_captain_and_vice_mutations_keep_single_role_holder(tmp_path):
    private = tmp_path / "private"
    path = private / "personal/current_team.json"
    _write(path, _team())

    assert _mutate_role(private, captain=True) == ["captain"]
    payload = json.loads(path.read_text())
    assert sum(row["captain"] is True for row in payload["players"]) == 1
    assert next(row["element_id"] for row in payload["players"] if row["captain"]) == 3

    _write(path, _team())
    assert _mutate_role(private, captain=False) == ["vice_captain"]
    payload = json.loads(path.read_text())
    assert sum(row["vice_captain"] is True for row in payload["players"]) == 1
    assert next(row["element_id"] for row in payload["players"] if row["vice_captain"]) == 3


def test_p4_miss_uses_real_package_but_mismatched_dependency(tmp_path):
    private = tmp_path / "private"
    runtime = tmp_path / "runtime"
    _write(private / "personal/current_team.json", _team())
    baseline = SimpleNamespace(
        p4_dependencies=lambda: {
            "model_version": "m",
            "our15_fingerprint": "o",
            "fixture_gw_fingerprint": "f",
            "projection_lineage_fingerprint": "p",
            "cache_schema_version": "c",
            "mc_authority": "mc",
            "owner_context_fingerprint": "owner",
        }
    )
    package = {"scenarios": []}
    keys, overrides, extra = _case_inputs(
        case="P4_SCENARIO_MISS",
        runtime=runtime,
        private=private,
        baseline_identity=baseline,
        scenario_package=package,
    )
    assert keys == ["projection_lineage_fingerprint"]
    assert overrides == {}
    assert extra["scenario_dependencies"]["projection_lineage_fingerprint"].endswith(
        ":CONTROLLED_MISS"
    )


def test_controlled_warm_recompute_reuses_baseline_cache_workspace():
    source = inspect.getsource(execute_case)
    assert source.count('workspace=workspace / "warm-baseline"') == 2
    assert 'workspace=workspace / "canonical-cold"' in source
    assert 'workspace=workspace / "warm-change"' not in source
    assert '\"timings\": result[\"timings\"]' in source
    assert '\"timings\": verdict[\"timings\"]' not in source


def test_mini_league_only_acceptance_uses_governed_partial_executor():
    source = inspect.getsource(execute_case)
    assert 'if change_class == "MINI_LEAGUE_ONLY"' in source
    assert "refresh_mini_league_only_state(" in source
    mini_branch = source.split('if change_class == "MINI_LEAGUE_ONLY"', 1)[1]
    mini_branch = mini_branch.split("current_state = warm_pipeline.compute(", 1)[0]
    assert "warm_pipeline.compute(" not in mini_branch
    assert "return current_state, dict(plan.expected), {}" in mini_branch


def test_production_p6_uses_same_mini_league_partial_executor():
    source = inspect.getsource(v12_p6_runtime.run_window)
    assert 'if change_class == "MINI_LEAGUE_ONLY"' in source
    assert "refresh_mini_league_only_state(" in source
    mini_branch = source.split('if change_class == "MINI_LEAGUE_ONLY"', 1)[1]
    mini_branch = mini_branch.split("current_state = pipeline.compute(final_identity)", 1)[0]
    assert "pipeline.compute(final_identity)" not in mini_branch
    assert "return current_state, dict(plan.expected), {}" in mini_branch


def test_mini_league_partial_refresh_reuses_football_math_and_keeps_qa():
    source = inspect.getsource(refresh_mini_league_only_state)
    assert "build_mini_league_snapshot(" in source
    assert "evaluate_mini_league_overlay(" in source
    assert "attach_mini_league_overlay(" in source
    assert "validate_pre_render_qa(" in source
    assert "validate_post_render_qa(" in source
    assert "truncated=False" in source
    assert "validate_final_delivery_barrier(" in source
    assert "safe_qa_failure" in source
    assert '"pre_render"' in source
    assert '"post_render"' in source
    assert '"human_facing_failures"' in source
    assert '"final_delivery"' in source
    assert '"payload_fingerprint"' in source
    assert '"report_slot": report_slot' in source
    assert '"reused_layers": ["Stage2", "P1.7", "MC"]' in source
    assert '"football_math_recomputed": False' in source
    assert "optimize_lineup(" not in source
    assert "run_package_monte_carlo(" not in source
