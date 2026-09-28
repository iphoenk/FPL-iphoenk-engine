from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from src.engines import v12_p6_runtime
from src.engines.v12_integrated_report_runner import (
    refresh_mini_league_only_state,
    refresh_price_only_state,
)
from src.engines.v12_perf_f_acceptance import (
    _require_same_slot_prefetch,
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
    assert '"payload_fingerprint": payload_fingerprint' in source
    assert '"report_slot": report_slot' in source
    assert "if key != \"authoritative_binding\"" in source
    assert "safe_qa_failure" in source
    assert '"pre_render"' in source
    assert '"post_render"' in source
    assert '"human_facing_failures"' in source
    assert '"final_delivery"' in source
    assert '"reused_layers": ["Stage2", "P1.7", "MC"]' in source
    assert '"football_math_recomputed": False' in source
    assert "optimize_lineup(" not in source
    assert "run_package_monte_carlo(" not in source


def test_price_only_acceptance_uses_governed_partial_executor():
    source = inspect.getsource(execute_case)
    assert 'if change_class == "PRICE_ONLY"' in source
    assert "refresh_price_only_state(" in source
    price_branch = source.split('if change_class == "PRICE_ONLY"', 1)[1]
    price_branch = price_branch.split("current_state = warm_pipeline.compute(", 1)[0]
    assert "warm_pipeline.compute(" not in price_branch
    assert "return current_state, dict(plan.expected), {}" in price_branch


def test_production_p6_uses_same_price_only_partial_executor():
    source = inspect.getsource(v12_p6_runtime.run_window)
    assert 'if change_class == "PRICE_ONLY"' in source
    assert "refresh_price_only_state(" in source
    price_branch = source.split('if change_class == "PRICE_ONLY"', 1)[1]
    price_branch = price_branch.split("current_state = pipeline.compute(final_identity)", 1)[0]
    assert "pipeline.compute(final_identity)" not in price_branch
    assert "return current_state, dict(plan.expected), {}" in price_branch


def test_price_only_partial_refresh_reuses_stage2_p17_and_keeps_qa():
    source = inspect.getsource(refresh_price_only_state)
    assert "build_price20(" in source
    assert "build_actionable_price_radar(" in source
    assert "_enrich_watchlist_rows(" in source
    assert "_enrich_all15_rows(" in source
    assert "validate_pre_render_qa(" in source
    assert "validate_post_render_qa(" in source
    assert "validate_final_delivery_barrier(" in source
    assert '"reused_layers": ["Stage2", "P1.7"]' in source
    assert '"partial_layers": ["MC", "scenario"]' in source
    assert '"football_math_recomputed": False' in source
    assert "optimize_lineup(" not in source
    assert "run_package_monte_carlo(" not in source


def test_controlled_prefetch_requires_exact_fresh_full_master_slot(tmp_path):
    runtime = tmp_path / "runtime"
    target = runtime / "data/v6/report_prefetch"
    target.mkdir(parents=True)
    slot = "2026-09-28T20:50:00+07:00"
    payload = {
        "report_kind": "full_master",
        "target_logical_report_slot": slot,
        "fresh_for_target_report": True,
    }
    (target / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert _require_same_slot_prefetch(runtime, slot)["fresh_for_target_report"] is True


@pytest.mark.parametrize(
    "patch",
    [
        {"target_logical_report_slot": "2026-09-28T20:00:00+07:00"},
        {"report_kind": "05:30_price"},
        {"fresh_for_target_report": False},
    ],
)
def test_controlled_prefetch_wrong_lineage_fails_closed(tmp_path, patch):
    runtime = tmp_path / "runtime"
    target = runtime / "data/v6/report_prefetch"
    target.mkdir(parents=True)
    slot = "2026-09-28T20:50:00+07:00"
    payload = {
        "report_kind": "full_master",
        "target_logical_report_slot": slot,
        "fresh_for_target_report": True,
    }
    payload.update(patch)
    (target / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PerfFAcceptanceError, match="LINEAGE_FAILURE"):
        _require_same_slot_prefetch(runtime, slot)
