from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from src.engines.v12_perf_f_acceptance import (
    _case_inputs,
    _mutate_price,
    _mutate_role,
    execute_case,
)
from src.engines.v12_integrated_report_runner import run_deep
from src.engines.v12_p6_runtime import CanonicalPipeline, run_window


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



def test_mini_league_acceptance_uses_governed_selective_warm_path():
    plan = plan_cache_behavior(
        "MINI_LEAGUE_ONLY",
        affected_dependency_keys=["mini_league:9477:entry:3462711"],
    )
    assert plan.expected == {
        "Stage2": "HIT",
        "P1.7": "HIT",
        "MC": "HIT",
        "scenario": "PARTIAL_INVALIDATION",
        "stability": "MISS",
    }

    acceptance_source = inspect.getsource(execute_case)
    assert 'change_class == "MINI_LEAGUE_ONLY"' in acceptance_source
    assert 'warm_reuse_change_class="MINI_LEAGUE_ONLY"' in acceptance_source
    assert "return current_state, dict(plan.expected), {}" in acceptance_source

    pipeline_source = inspect.getsource(CanonicalPipeline.compute)
    assert '"--warm-reuse-state-file"' in pipeline_source
    assert '"--warm-reuse-change-class"' in pipeline_source
    assert "scenario overrides cannot be combined with selective warm reuse" in pipeline_source

    runtime_source = inspect.getsource(run_window)
    assert 'change_class == "MINI_LEAGUE_ONLY"' in runtime_source
    assert 'warm_reuse_state=dict(state.get("warm_state") or {})' in runtime_source

    integrated_source = inspect.getsource(run_deep)
    assert "mini_only_warm_reuse" in integrated_source
    assert "package_with_stage3_pre_mini" in integrated_source
    assert "FROZEN_SAME_OCCURRENCE_PRIVATE_WARM_STATE" in integrated_source
