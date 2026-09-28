from __future__ import annotations

import inspect

from src.engines.v12_p6_selective_refresh import refresh_p4_scenario_state
from src.engines.v12_perf_f_acceptance import execute_case


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
    assert '"qa_relaxed": False' in module_source
    assert '"second_methodology_created": False' in module_source
