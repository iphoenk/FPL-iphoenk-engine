from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'pattern not found in {path}: {old[:120]!r}')
    if text.count(old) != 1:
        raise RuntimeError(f'pattern not unique in {path}: count={text.count(old)}')
    path.write_text(text.replace(old, new), encoding='utf-8')


# 1) Coalesced FAST lane in domain orchestrator.
p = ROOT / 'src/runtime_v3/domain_orchestrator.py'
replace_once(
    p,
    'from src.runtime_v3 import incremental_reuse\nfrom src.runtime_v3 import module_batch_runner\n',
    'from src.runtime_v3 import incremental_reuse\nfrom src.runtime_v3 import module_batch_runner\nfrom src.runtime_v3 import domain_process_runner\n',
)
replace_once(
    p,
    'PERFORMANCE_PATH = DATA / "runtime_performance.json"\nDOMAIN_RUNTIME_ID = "v3-domain-pipeline-v2"\n',
    'PERFORMANCE_PATH = DATA / "runtime_performance.json"\nFAST_LANE_POLICY_PATH = ROOT / "config" / "runtime" / "fast_lane_policy.json"\nDOMAIN_RUNTIME_ID = "v3-domain-pipeline-v2"\n',
)
insert_after = '''def _run_domain_process(\n    domain_name: str,\n    *,\n    mode: str,\n    stats: bool,\n    deep_stats: bool,\n    profile_name: str,\n    cache_dir: Path,\n    cache_ttl: int,\n    timeout: int,\n    data_dir: Path = DATA,\n) -> dict[str, Any]:\n'''
text = p.read_text(encoding='utf-8')
idx = text.index(insert_after)
# insert helper before next def _domain_seed_paths by textual boundary
marker = '\n\ndef _domain_seed_paths('
pos = text.index(marker, idx)
helper = '''\n\ndef _fast_lane_policy() -> dict[str, Any]:\n    payload = json.loads(FAST_LANE_POLICY_PATH.read_text(encoding="utf-8"))\n    if payload.get("registry") != "V3_FAST_LANE_POLICY_V1":\n        raise RuntimeError("unexpected V3 fast-lane policy registry")\n    return payload\n\n\ndef _run_domain_in_process(\n    domain_name: str,\n    *,\n    mode: str,\n    stats: bool,\n    deep_stats: bool,\n    profile_name: str,\n    cache_dir: Path,\n    cache_ttl: int,\n) -> dict[str, Any]:\n    started = time.perf_counter()\n    previous = {\n        key: os.environ.get(key)\n        for key in ("FPL_HTTP_CACHE_DIR", "FPL_HTTP_CACHE_TTL_SECONDS", "FPL_EXECUTION_PROFILE")\n    }\n    os.environ["FPL_HTTP_CACHE_DIR"] = str(cache_dir)\n    os.environ["FPL_HTTP_CACHE_TTL_SECONDS"] = str(cache_ttl)\n    os.environ["FPL_EXECUTION_PROFILE"] = profile_name\n    try:\n        payload = domain_process_runner.run_domain(domain_name, mode, stats, deep_stats, profile_name)\n    finally:\n        for key, value in previous.items():\n            if value is None:\n                os.environ.pop(key, None)\n            else:\n                os.environ[key] = value\n    payload["process_elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)\n    payload["execution_boundary"] = "IN_PROCESS_COALESCED"\n    return payload\n'''
text = text[:pos] + helper + text[pos:]
p.write_text(text, encoding='utf-8')

replace_once(
    p,
    '        pending = list(compiled_plan["domain_order"])\n        parallel_waves = [\n',
    '        pending = list(compiled_plan["domain_order"])\n        fast_policy = _fast_lane_policy()\n        coalesced_fast = profile_name in set(fast_policy.get("profiles") or [])\n        parallel_waves = [] if coalesced_fast else [\n',
)
replace_once(
    p,
    '''                domain_payload = _run_domain_process(\n                    domain_name,\n                    mode=mode,\n                    stats=stats,\n                    deep_stats=deep_stats,\n                    profile_name=profile_name,\n                    cache_dir=cache_dir,\n                    cache_ttl=cache_ttl,\n                    timeout=timeout,\n                )\n''',
    '''                if coalesced_fast:\n                    domain_payload = _run_domain_in_process(\n                        domain_name,\n                        mode=mode,\n                        stats=stats,\n                        deep_stats=deep_stats,\n                        profile_name=profile_name,\n                        cache_dir=cache_dir,\n                        cache_ttl=cache_ttl,\n                    )\n                else:\n                    domain_payload = _run_domain_process(\n                        domain_name,\n                        mode=mode,\n                        stats=stats,\n                        deep_stats=deep_stats,\n                        profile_name=profile_name,\n                        cache_dir=cache_dir,\n                        cache_ttl=cache_ttl,\n                        timeout=timeout,\n                    )\n''',
)
replace_once(
    p,
    '''        performance["domain_process_execution"] = {\n            "enabled": True,\n            "process_count": len(domain_results),\n            "phase_count": int(domain_registry["phase_count"]),\n            "one_process_per_execution_domain": True,\n            "business_ownership_unchanged": True,\n''',
    '''        performance["domain_process_execution"] = {\n            "enabled": not coalesced_fast,\n            "process_count": 0 if coalesced_fast else len(domain_results),\n            "phase_count": int(domain_registry["phase_count"]),\n            "one_process_per_execution_domain": not coalesced_fast,\n            "coalesced_fast_lane": coalesced_fast,\n            "execution_boundary": "IN_PROCESS_COALESCED" if coalesced_fast else "DOMAIN_PROCESS",\n            "fail_closed_after_partial_execution": bool(fast_policy.get("fail_closed_after_partial_execution", True)) if coalesced_fast else True,\n            "fallback_to_multi_process_allowed": bool(fast_policy.get("fallback_to_multi_process_allowed", False)) if coalesced_fast else True,\n            "business_ownership_unchanged": True,\n''',
)
replace_once(
    p,
    '            "one_process_per_execution_domain": True,\n            "isolated_parallel_domains": sorted(parallel_wave_domains),\n',
    '            "one_process_per_execution_domain": not coalesced_fast,\n            "coalesced_fast_lane": coalesced_fast,\n            "execution_boundary": "IN_PROCESS_COALESCED" if coalesced_fast else "DOMAIN_PROCESS",\n            "isolated_parallel_domains": sorted(parallel_wave_domains),\n',
)

# 2) Tighten FAST SLO to hard 3s.
p = ROOT / 'config/runtime/performance_slo.json'
data = json.loads(p.read_text(encoding='utf-8'))
fast = data['profiles']['fast_decision']
fast.update({
    'target_wall_ms': 3000,
    'warning_wall_ms': 2800,
    'legacy_ceiling_ms': 3000,
    'enforcement': 'HARD_CEILING',
    'consistency_requirement': '3 fresh-process candidate runs must each be <=3000ms',
})
p.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')

# 3) Add consistency acceptance step to CI.
p = ROOT / '.github/workflows/v3-ci.yml'
replace_once(
    p,
    '      - name: Benchmark unified interactive fastpath under 2s, prefer 1s\n',
    '      - name: Prove FAST decision runtime consistently under 3s\n        if: github.event_name == \'pull_request\' || github.ref == \'refs/heads/main\'\n        run: python -m src.runtime_v3.fast_consistency_acceptance\n      - name: Benchmark unified interactive fastpath under 2s, prefer 1s\n',
)

# 4) Remove temporary bootstrap artifacts from final branch.
for rel in ('.github/workflows/v3-sub3s-bootstrap.yml', 'tools/apply_v3_sub3s_hardening.py'):
    q = ROOT / rel
    if q.exists():
        q.unlink()
