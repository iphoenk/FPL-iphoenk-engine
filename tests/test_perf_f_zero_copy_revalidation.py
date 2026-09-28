from __future__ import annotations

import inspect

from src.engines.v12_p6_selective_refresh import refresh_revalidated_base_state


def test_revalidated_base_is_zero_copy_but_reruns_all_delivery_barriers():
    source = inspect.getsource(refresh_revalidated_base_state)
    assert "deepcopy(" not in source
    assert "materialize_deep_report(" not in source
    assert "render_deep_text(" not in source
    for token in (
        "validate_pre_render_qa(",
        "validate_post_render_qa(",
        "validate_human_facing_body(",
        "validate_deep_human_facing_manifest(",
        "validate_final_delivery_barrier(",
    ):
        assert token in source
    assert '"canonical_bundle_bytes_reused": True' in source
    assert '"pre_render_qa_rerun": True' in source
    assert '"post_render_qa_rerun": True' in source
    assert '"human_facing_qa_rerun": True' in source
    assert '"final_delivery_qa_rerun": True' in source
    assert '"qa_relaxed": False' in source
    assert 'report_bundle.json").write_text' not in source
    assert 'report_body.md").write_text' not in source
    assert 'execution_proof.json").write_text' in source
