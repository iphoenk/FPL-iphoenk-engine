from __future__ import annotations

from src.runtime_v3 import domain_process_runner, registry_compiler


def test_domain_process_runner_uses_canonical_compiler_authority(monkeypatch):
    domain_registry = {"domains": {"example": {"capabilities": ["cap"]}}}
    service_registry = {"services": {"cap": {}}}
    calls: list[tuple[dict, dict]] = []

    monkeypatch.setattr(registry_compiler, "load_domain_registry", lambda: domain_registry)
    monkeypatch.setattr(registry_compiler, "load_capability_registry", lambda: service_registry)
    monkeypatch.setattr(
        registry_compiler,
        "compile_runtime_plan",
        lambda *, domain_registry, service_registry: calls.append((domain_registry, service_registry)) or {},
    )

    domain_process_runner._validated_registries.cache_clear()
    domain_process_runner._domains.cache_clear()
    domain_process_runner._service_registry.cache_clear()
    try:
        assert domain_process_runner._domains() == domain_registry["domains"]
        assert domain_process_runner._service_registry() is service_registry
        assert calls == [(domain_registry, service_registry)]
    finally:
        domain_process_runner._validated_registries.cache_clear()
        domain_process_runner._domains.cache_clear()
        domain_process_runner._service_registry.cache_clear()


def test_domain_process_runner_has_no_secondary_domain_registry_path():
    source = open(domain_process_runner.__file__, encoding="utf-8").read()
    assert "DOMAIN_PATH" not in source
    assert '"V3_EXECUTION_DOMAINS_V2"' not in source
    assert "registry_compiler.load_domain_registry()" in source
    assert "registry_compiler.load_capability_registry()" in source
    assert "registry_compiler.compile_runtime_plan(" in source
