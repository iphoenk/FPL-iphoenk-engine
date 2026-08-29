from __future__ import annotations

from pathlib import Path


ORCHESTRATOR = Path("src/runtime_v3/domain_orchestrator.py")
TEST = Path("tests/test_runtime_compiled_wave_parallelism.py")


def main() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    text = text.replace('_PARALLEL_ISOLATED_DOMAINS = ("prediction", "market_context")\n', '')

    helper_marker = "\ndef _reuse_diagnostic_summary("
    helper = '''

def _parallel_wave_isolation_safe(
    wave: tuple[str, ...],
    domain_registry: dict[str, Any],
    services: dict[str, Any],
) -> bool:
    """Only parallelize compiled waves whose capability outputs cannot collide."""
    if len(wave) < 2:
        return False
    artifacts_seen: set[str] = set()
    latest_keys_seen: set[str] = set()
    latest_file_keys_seen: set[str] = set()
    for domain_name in wave:
        domain_spec = domain_registry["domains"].get(domain_name) or {}
        capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
        if not capabilities:
            return False
        if any(not bool((services.get(capability) or {}).get("isolated", False)) for capability in capabilities):
            return False
        artifacts = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("artifacts") or [])
        }
        latest_keys = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("latest_keys") or [])
        }
        latest_file_keys = {
            str(value)
            for capability in capabilities
            for value in (services[capability].get("latest_file_keys") or [])
        }
        if artifacts_seen & artifacts or latest_keys_seen & latest_keys or latest_file_keys_seen & latest_file_keys:
            return False
        artifacts_seen.update(artifacts)
        latest_keys_seen.update(latest_keys)
        latest_file_keys_seen.update(latest_file_keys)
    return True
'''
    if helper_marker not in text:
        raise RuntimeError("helper insertion marker missing")
    text = text.replace(helper_marker, helper + helper_marker, 1)

    start = '        pending = list(compiled_plan["domain_order"])\n        while pending:\n'
    end = '        total_ms = (time.perf_counter() - wall_started) * 1000.0\n'
    start_idx = text.find(start)
    end_idx = text.find(end, start_idx)
    if start_idx < 0 or end_idx < 0:
        raise RuntimeError("scheduler replacement markers missing")

    scheduler = '''        pending = list(compiled_plan["domain_order"])
        parallel_waves = [
            tuple(str(domain) for domain in wave)
            for wave in compiled_plan["domain_waves"]
            if len(wave) > 1
            and _parallel_wave_isolation_safe(
                tuple(str(domain) for domain in wave),
                domain_registry,
                services,
            )
        ]
        parallel_wave_domains = {domain for wave in parallel_waves for domain in wave}
        while pending:
            ready_wave = next(
                (
                    wave
                    for wave in parallel_waves
                    if all(
                        domain in pending
                        and set(domain_registry["domains"][domain].get("depends_on") or []).issubset(completed_domains)
                        for domain in wave
                    )
                ),
                None,
            )
            if ready_wave is not None:
                workspaces: dict[str, Path] = {}
                capabilities_by_domain: dict[str, list[str]] = {}
                for domain_name in ready_wave:
                    domain_spec = domain_registry["domains"][domain_name]
                    capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
                    domain_set = set(capabilities)
                    for capability in capabilities:
                        spec = services[capability]
                        external_deps = {str(dep) for dep in spec.get("depends_on") or []} - domain_set
                        missing = sorted(external_deps - completed_capabilities)
                        if missing:
                            raise RuntimeError(
                                f"parallel domain ordering violates capability dependency: {domain_name}:{capability} missing={missing}"
                            )
                    capabilities_by_domain[domain_name] = capabilities
                    workspaces[domain_name] = _seed_isolated_domain(domain_name, capabilities, services, temp_root)

                wave_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=len(ready_wave), thread_name_prefix="v3-domain") as pool:
                    futures = {
                        domain_name: pool.submit(
                            _run_domain_process,
                            domain_name,
                            mode=mode,
                            stats=stats,
                            deep_stats=deep_stats,
                            profile_name=profile_name,
                            cache_dir=cache_dir,
                            cache_ttl=cache_ttl,
                            timeout=timeout,
                            data_dir=workspaces[domain_name],
                        )
                        for domain_name in ready_wave
                    }
                    payloads = {domain_name: futures[domain_name].result() for domain_name in ready_wave}
                wave_wall_ms = round((time.perf_counter() - wave_started) * 1000.0, 3)

                for domain_name in ready_wave:
                    fan_in = _promote_isolated_domain(
                        domain_name,
                        capabilities_by_domain[domain_name],
                        services,
                        workspaces[domain_name],
                    )
                    fan_in["parallel_wave_wall_ms"] = wave_wall_ms
                    if len(ready_wave) == 2:
                        fan_in["parallel_pair_wall_ms"] = wave_wall_ms
                    _accept_domain_result(
                        domain_name,
                        payloads[domain_name],
                        capabilities_by_domain[domain_name],
                        services,
                        capability_results,
                        completed_capabilities,
                        domain_results,
                        phase=str(domain_registry["domains"][domain_name]["phase"]),
                        fan_in=fan_in,
                    )
                    completed_domains.add(domain_name)
                    pending.remove(domain_name)
                parallel_pairs_executed.append(list(ready_wave))
                continue

            progressed = False
            for domain_name in list(pending):
                if domain_name in parallel_wave_domains:
                    continue
                domain_spec = domain_registry["domains"][domain_name]
                if not set(domain_spec.get("depends_on") or []).issubset(completed_domains):
                    continue
                capabilities = [str(value) for value in domain_spec.get("capabilities") or []]
                domain_set = set(capabilities)
                for capability in capabilities:
                    spec = services[capability]
                    external_deps = {str(dep) for dep in spec.get("depends_on") or []} - domain_set
                    missing = sorted(external_deps - completed_capabilities)
                    if missing:
                        raise RuntimeError(
                            f"domain ordering violates capability dependency: {domain_name}:{capability} missing={missing}"
                        )

                domain_payload = _run_domain_process(
                    domain_name,
                    mode=mode,
                    stats=stats,
                    deep_stats=deep_stats,
                    profile_name=profile_name,
                    cache_dir=cache_dir,
                    cache_ttl=cache_ttl,
                    timeout=timeout,
                )
                _accept_domain_result(
                    domain_name,
                    domain_payload,
                    capabilities,
                    services,
                    capability_results,
                    completed_capabilities,
                    domain_results,
                    phase=str(domain_spec["phase"]),
                )
                completed_domains.add(domain_name)
                pending.remove(domain_name)
                progressed = True
            if not progressed:
                raise RuntimeError(f"execution domain DAG stalled: {pending}")

'''
    text = text[:start_idx] + scheduler + text[end_idx:]

    old_perf = '''            "isolated_parallel_domains": list(_PARALLEL_ISOLATED_DOMAINS),
            "parallel_pairs_executed": parallel_pairs_executed,
            "deterministic_fan_in": True,
'''
    new_perf = '''            "isolated_parallel_domains": sorted(parallel_wave_domains),
            "parallel_pairs_executed": parallel_pairs_executed,
            "compiled_parallel_waves": [list(wave) for wave in parallel_waves],
            "parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE",
            "deterministic_fan_in": True,
'''
    if old_perf not in text:
        raise RuntimeError("performance metadata marker missing")
    text = text.replace(old_perf, new_perf, 1)

    old_latest = '''            "isolated_parallel_domains": list(_PARALLEL_ISOLATED_DOMAINS),
            "deterministic_fan_in": True,
'''
    new_latest = '''            "isolated_parallel_domains": sorted(parallel_wave_domains),
            "compiled_parallel_waves": [list(wave) for wave in parallel_waves],
            "parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE",
            "deterministic_fan_in": True,
'''
    if old_latest not in text:
        raise RuntimeError("latest metadata marker missing")
    text = text.replace(old_latest, new_latest, 1)
    ORCHESTRATOR.write_text(text, encoding="utf-8")

    TEST.write_text('''from __future__ import annotations

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
    assert ("market_context", "prediction") in safe
    assert ("squad_decision", "prediction_validation") in safe


def test_scheduler_has_no_hardcoded_single_parallel_pair() -> None:
    source = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")
    assert "_PARALLEL_ISOLATED_DOMAINS" not in source
    assert '"parallel_wave_scheduler": "COMPILED_ISOLATION_SAFE"' in source
    assert 'compiled_plan["domain_waves"]' in source
''', encoding="utf-8")


if __name__ == "__main__":
    main()
