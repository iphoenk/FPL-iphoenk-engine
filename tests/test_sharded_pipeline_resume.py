from __future__ import annotations

from src.runtime_v3 import sharded_pipeline_resume


def test_sharded_resume_uses_registry_boundary_and_compiled_order(monkeypatch):
    policy = {
        "registry": "V3_PACKAGE_OPTIMIZER_SHARDING_V1",
        "workflow": {"resume_from_domain": "squad_decision"},
    }
    domains = {
        "prediction": {"depends_on": [], "capabilities": ["prediction"]},
        "squad_decision": {"depends_on": ["prediction"], "capabilities": ["lineup_governance"]},
        "reporting": {"depends_on": ["squad_decision"], "capabilities": ["reporting"]},
    }
    services = {
        "prediction": {"depends_on": []},
        "lineup_governance": {"depends_on": ["prediction"]},
        "reporting": {"depends_on": ["lineup_governance"]},
    }
    monkeypatch.setattr(sharded_pipeline_resume, "_policy", lambda: policy)
    monkeypatch.setattr(sharded_pipeline_resume.registry_compiler, "load_domain_registry", lambda: {"domains": domains})
    monkeypatch.setattr(sharded_pipeline_resume.registry_compiler, "load_capability_registry", lambda: {"services": services})
    monkeypatch.setattr(
        sharded_pipeline_resume.registry_compiler,
        "compile_runtime_plan",
        lambda **kwargs: {"domain_order": ["prediction", "squad_decision", "reporting"]},
    )
    executed = []
    monkeypatch.setattr(
        sharded_pipeline_resume.domain_process_runner,
        "run_domain",
        lambda domain, mode, stats, deep_stats, profile: executed.append(domain) or {"status": "SUCCESS", "results": {}},
    )

    result = sharded_pipeline_resume.resume(profile="exhaustive_precompute")
    assert executed == ["squad_decision", "reporting"]
    assert result["precompleted_domains"] == ["prediction"]
    assert result["executed_domains"] == ["squad_decision", "reporting"]
    assert result["governance"]["downstream_business_modules_not_hardcoded"] is True
