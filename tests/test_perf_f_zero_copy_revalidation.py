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


def test_zero_copy_revalidation_executes_qa_and_preserves_large_files(monkeypatch, tmp_path):
    import json
    import src.engines.v12_p6_selective_refresh as selective

    calls = []
    monkeypatch.setattr(
        selective,
        "validate_pre_render_qa",
        lambda **kwargs: calls.append("pre") or {
            "status": "PASS",
            "render_contract_token": "token",
            "expected_counts": {},
            "expected_fact_keys": [],
            "expected_model_keys": [],
        },
    )
    monkeypatch.setattr(
        selective,
        "validate_post_render_qa",
        lambda **kwargs: calls.append("post") or {"status": "PASS"},
    )
    monkeypatch.setattr(
        selective,
        "validate_human_facing_body",
        lambda body: calls.append("human_body") or [],
    )
    monkeypatch.setattr(
        selective,
        "validate_deep_human_facing_manifest",
        lambda manifest: calls.append("human_manifest") or [],
    )
    monkeypatch.setattr(
        selective,
        "validate_final_delivery_barrier",
        lambda **kwargs: calls.append("final") or {"status": "PASS", "failures": []},
    )
    monkeypatch.setattr(
        selective,
        "_parse_sections",
        lambda body: (["S01"], {}, {}),
    )

    slot = "2026-09-28T21:20:00+07:00"
    report_bundle_path = tmp_path / "report_bundle.json"
    report_body_path = tmp_path / "report_body.md"
    report_bundle_path.write_text("BUNDLE_SENTINEL", encoding="utf-8")
    report_body_path.write_text("BODY_SENTINEL", encoding="utf-8")
    (tmp_path / "execution_proof.json").write_text("{}\n", encoding="utf-8")

    state = {
        "bundle": {
            "report_mode": "DEEP",
            "report_slot": slot,
            "report": {"sections": [{"section_id": "S01", "state": "COMPLETE"}]},
            "section_manifest": [{"section_id": "S01", "status": "COMPLETE"}],
            "compute_contract": {"compute_fingerprint": "abc"},
            "human_facing_manifest": {},
            "visible_body": "already rendered",
            "execution_proof": {"runner_status": "PASS"},
            "governance": {},
        },
        "warm_state": {
            "mini": {"coverage_state": "FULL"},
            "calendar_context": {"weather": [{"fpl_impact": "NORMAL"}]},
        },
        "execution_proof": {"runner_status": "PASS"},
        "output_dir": str(tmp_path),
    }
    result = refresh_revalidated_base_state(
        state=state,
        report_slot=slot,
        change_class="CAPTAIN_CHANGE",
        evidence={"submitted_role_change_revalidated": True},
    )

    assert calls == ["pre", "final", "human_body", "human_manifest", "post"]
    assert report_bundle_path.read_text(encoding="utf-8") == "BUNDLE_SENTINEL"
    assert report_body_path.read_text(encoding="utf-8") == "BODY_SENTINEL"
    proof = json.loads((tmp_path / "execution_proof.json").read_text(encoding="utf-8"))
    warm = proof["warm_selective_refresh"]
    assert warm["canonical_bundle_bytes_reused"] is True
    assert warm["pre_render_qa_rerun"] is True
    assert warm["post_render_qa_rerun"] is True
    assert warm["human_facing_qa_rerun"] is True
    assert warm["final_delivery_qa_rerun"] is True
    assert result["bundle"]["pre_render_qa"]["status"] == "PASS"
    assert result["bundle"]["post_render_qa"]["status"] == "PASS"
