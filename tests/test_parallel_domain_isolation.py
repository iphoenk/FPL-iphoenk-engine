from src.runtime_v3 import domain_orchestrator as runtime
from src.runtime_v3 import registry_compiler


def _safe_parallel_waves() -> list[tuple[str, ...]]:
    registry = runtime._load_domains()
    service_registry = runtime.legacy._load_registry()
    services = service_registry["services"]
    plan = registry_compiler.compile_runtime_plan(
        domain_registry=registry,
        service_registry=service_registry,
    )
    return [
        tuple(str(domain) for domain in wave)
        for wave in plan["domain_waves"]
        if len(wave) > 1
        and runtime._parallel_wave_isolation_safe(
            tuple(str(domain) for domain in wave),
            registry,
            services,
        )
    ]


def test_parallel_domains_are_compiled_and_isolation_safe():
    safe_waves = _safe_parallel_waves()
    assert ("market_context", "prediction") in safe_waves
    assert ("squad_decision", "prediction_validation") in safe_waves

    registry = runtime._load_domains()
    policy = registry["policy"]
    assert policy["prediction_and_market_context_use_isolated_workspaces"] is True
    assert policy["prediction_and_market_context_may_execute_in_parallel"] is True
    assert policy["parallel_domain_fan_in_uses_declared_artifacts_and_latest_keys_only"] is True
    assert policy["parallel_domain_fan_in_is_deterministic"] is True


def test_seed_paths_are_contract_derived():
    services = {
        "a": {"inputs": ["in/a.json"], "artifacts": ["out/a.json"]},
        "b": {"inputs": ["in/b.json"], "artifacts": ["out/b.json"]},
    }
    assert runtime._domain_seed_paths(["a", "b"], services) == [
        "in/a.json",
        "in/b.json",
        "incremental_reuse_state.json",
        "latest.json",
        "out/a.json",
        "out/b.json",
    ]


def test_current_compiled_parallel_waves_have_disjoint_declared_write_sets():
    services = runtime.legacy._load_registry()["services"]
    domains = runtime._load_domains()["domains"]

    def write_set(domain_name: str) -> tuple[set[str], set[str], set[str]]:
        artifacts: set[str] = set()
        latest_keys: set[str] = set()
        latest_file_keys: set[str] = set()
        for capability in domains[domain_name]["capabilities"]:
            spec = services[capability]
            artifacts.update(str(x) for x in spec.get("artifacts") or [])
            latest_keys.update(str(x) for x in spec.get("latest_keys") or [])
            latest_file_keys.update(str(x) for x in spec.get("latest_file_keys") or [])
        return artifacts, latest_keys, latest_file_keys

    for wave in _safe_parallel_waves():
        declared = [write_set(domain_name) for domain_name in wave]
        for index, left in enumerate(declared):
            for right in declared[index + 1 :]:
                assert left[0].isdisjoint(right[0])
                assert left[1].isdisjoint(right[1])
                assert left[2].isdisjoint(right[2])
