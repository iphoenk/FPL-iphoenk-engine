from __future__ import annotations

from src.runtime_v3 import registry_compiler, sharded_pipeline_resume


def test_sharded_resume_uses_compiled_topological_waves(monkeypatch):
    calls: list[str] = []

    def fake_run_domain(domain_name, mode, stats, deep_stats, profile):
        calls.append(domain_name)
        return {
            "status": "SUCCESS",
            "domain": domain_name,
            "mode": mode,
            "profile": profile,
        }

    monkeypatch.setattr(sharded_pipeline_resume.domain_process_runner, "run_domain", fake_run_domain)

    compiled = registry_compiler.compile_runtime_plan()
    waves = [[str(name) for name in wave] for wave in compiled["domain_waves"]]
    start = "squad_decision"
    start_wave_index = next(index for index, wave in enumerate(waves) if start in wave)
    expected_waves = waves[start_wave_index:]
    expected_order = [name for wave in expected_waves for name in wave]

    result = sharded_pipeline_resume.resume(profile="exhaustive_precompute")

    assert result["status"] == "SUCCESS"
    assert result["resume_from_domain"] == start
    assert result["executed_domain_waves"] == expected_waves
    assert result["executed_domains"] == expected_order
    assert calls == expected_order
    assert expected_waves[0] == ["squad_decision", "prediction_validation"]
    assert expected_order.index("prediction_validation") < expected_order.index("challenger_analysis")
    assert result["governance"]["domain_waves_from_compiled_registry"] is True
    assert result["governance"]["resume_boundary_expands_to_complete_topological_wave"] is True


def test_resume_wave_helper_preserves_all_siblings_at_boundary():
    plan = {
        "domain_waves": [
            ["upstream"],
            ["squad_decision", "prediction_validation"],
            ["challenger_analysis"],
        ]
    }

    before, selected = sharded_pipeline_resume._resume_waves(plan, "squad_decision")

    assert before == [["upstream"]]
    assert selected == [
        ["squad_decision", "prediction_validation"],
        ["challenger_analysis"],
    ]
