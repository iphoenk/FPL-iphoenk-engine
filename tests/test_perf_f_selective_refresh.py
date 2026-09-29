from __future__ import annotations

import inspect

import pytest

from src.engines.v12_p6_selective_refresh import (
    SelectiveRefreshError,
    _scenario_section_delivery_state,
    refresh_p4_scenario_state,
)
from src.engines.v12_perf_f_acceptance import (
    _requires_p4_package,
    execute_case,
)


def test_our15_and_p4_hit_use_canonical_precomputed_selective_path():
    source = inspect.getsource(execute_case)
    assert 'change_class in {"OUR15_AVAILABILITY", "P4_SCENARIO_HIT"}' in source
    assert "refresh_p4_scenario_state(" in source
    branch = source.split(
        'change_class in {"OUR15_AVAILABILITY", "P4_SCENARIO_HIT"}',
        1,
    )[1].split("current_state = warm_pipeline.compute(", 1)[0]
    assert "warm_pipeline.compute(" not in branch
    assert "return current_state, dict(plan.expected), {}" in branch


def test_p4_selective_refresh_preserves_full_delivery_barriers():
    source = inspect.getsource(refresh_p4_scenario_state)
    module = inspect.getmodule(refresh_p4_scenario_state)
    assert module is not None
    module_source = inspect.getsource(module)
    for token in (
        "materialize_deep_report(",
        "render_deep_text(",
        "validate_pre_render_qa(",
        "validate_post_render_qa(",
        "validate_human_facing_body(",
        "validate_deep_human_facing_manifest(",
        "validate_final_delivery_barrier(",
    ):
        assert token in module_source
    for sid in ("S06", "S08", "S09", "S14", "S19"):
        assert f'"{sid}"' in source
    assert "run_package_monte_carlo(" not in module_source
    assert '"content": raw.get("content")' in module_source
    assert "for sid in sorted(surface_ids)" in source
    assert "write_serving_artifacts(" in module_source
    assert "deepcopy(dict(state))" not in module_source
    assert '"qa_relaxed": False' in module_source
    assert '"second_methodology_created": False' in module_source


def test_remaining_perf_f_cases_do_not_fall_through_to_full_pipeline():
    source = inspect.getsource(execute_case)
    for case in (
        "CAPTAIN_CHANGE",
        "VICE_CAPTAIN_CHANGE",
        "MATERIAL_PROJECTION",
        "P4_SCENARIO_MISS",
    ):
        assert case in source
    pre_full = source.split("current_state = warm_pipeline.compute(", 1)[0]
    assert "refresh_revalidated_base_state(" in pre_full
    assert pre_full.count("refresh_p4_scenario_state(") >= 2
    assert '"canonical_p1_1_override_equivalence": True' in pre_full
    assert '"wrong_base_package_rejected": True' in pre_full


def test_material_projection_control_is_one_way_unavailability():
    from src.engines.v12_perf_f_acceptance import _mutate_material_projection

    source = inspect.getsource(_mutate_material_projection)
    assert 'target["chance_of_playing_next_round"] = 0' in source
    assert "else 100" not in source
    assert "no owned available element" in source


def test_only_p4_consuming_perf_f_cases_attach_private_scenario_package():
    for case in (
        "OUR15_AVAILABILITY",
        "MATERIAL_PROJECTION",
        "P4_SCENARIO_HIT",
        "P4_SCENARIO_MISS",
    ):
        assert _requires_p4_package(case) is True

    for case in (
        "NO_CHANGE",
        "MINI_LEAGUE_ONLY",
        "PRICE_ONLY",
        "CAPTAIN_CHANGE",
        "VICE_CAPTAIN_CHANGE",
    ):
        assert _requires_p4_package(case) is False

    source = inspect.getsource(execute_case)
    assert "if _requires_p4_package(case)" in source


def test_p4_s03_unavailable_baseline_stays_degraded():
    state, reason = _scenario_section_delivery_state(
        sid="S03",
        replacement={
            "decision_delta": {
                "baseline_state": "UNAVAILABLE",
                "summary": "BASELINE UNAVAILABLE — no prior valid visible DEEP",
                "no_recomputation_no_numeric_delta": True,
            }
        },
    )
    assert state == "DEGRADED"
    assert reason is not None


def test_p4_s03_available_baseline_can_be_complete():
    state, reason = _scenario_section_delivery_state(
        sid="S03",
        replacement={
            "decision_delta": {
                "baseline_state": "AVAILABLE",
                "rows": [],
                "summary": "NO MATERIAL DECISION CHANGE",
            }
        },
    )
    assert state == "COMPLETE"
    assert reason is None


def test_p4_s03_unavailable_baseline_fails_closed_without_guards():
    with pytest.raises(SelectiveRefreshError):
        _scenario_section_delivery_state(
            sid="S03",
            replacement={
                "decision_delta": {
                    "baseline_state": "UNAVAILABLE",
                    "summary": "missing required sentinel",
                    "no_recomputation_no_numeric_delta": False,
                }
            },
        )
