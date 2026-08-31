from __future__ import annotations

from pathlib import Path

from src.runtime_v3 import domain_orchestrator, registry_compiler

ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_derives_isolation_safe_parallel_waves_from_compiled_plan() -> None:
    domains = registry_compiler.load_domain_registry()
    registry = registry_compiler.load_capability_registry()
    services = registry["services"]
    plan = registry_compiler.compile_runtime_plan(domains, registry)
    safe = [
        tuple(str(domain) for domain in wave)
        for wave in plan["domain_waves"]
        if len(wave) > 1
        and domain_orchestrator._parallel_wave_isolation_safe(
            tuple(str(domain) for domain in wave), domains, services
        )
    ]
    assert ("weather_context", "market_context") in safe
    assert ("squad_decision", "prediction_validation") in safe


def test_scheduler_has_no_hardcoded_single_parallel_pair() -> None:
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")
    assert "_PARALLEL_ISOLATED_DOMAINS" not in source
    assert '"parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE"' in source
    assert 'compiled_plan["domain_waves"]' in source
