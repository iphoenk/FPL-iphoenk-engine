from __future__ import annotations

import argparse
import json

from src.runtime_v3 import domain_orchestrator, incremental_reuse
from src.runtime_v3 import orchestrator as legacy

_ORIGINAL_REUSE = legacy._reuse_service
_ORIGINAL_RUN_SERVICE = legacy._run_service
_ORIGINAL_METADATA = legacy._write_runtime_metadata


def _reuse_service(service_name, spec, canonical, profile_cfg):
    ttl = _ORIGINAL_REUSE(service_name, spec, canonical, profile_cfg)
    if ttl is not None:
        return ttl
    profile_name = str(profile_cfg.get("_profile_name") or "")
    return incremental_reuse.try_reuse(service_name, spec, profile_name)


def _run_service(service_name, spec, **kwargs):
    input_fingerprint_before = incremental_reuse.fingerprint(service_name)
    result = _ORIGINAL_RUN_SERVICE(service_name, spec, **kwargs)
    if input_fingerprint_before:
        result["input_fingerprint_before"] = input_fingerprint_before
    return result


def _write_runtime_metadata(registry, service_results, total_ms, cache_dir, profile, profile_cfg, temp_root):
    performance = _ORIGINAL_METADATA(registry, service_results, total_ms, cache_dir, profile, profile_cfg, temp_root)
    diagnostics = {}
    for name, row in service_results.items():
        if row.get("status") in {"SUCCESS", "REUSED"}:
            captured = row.get("input_fingerprint_before") or row.get("input_fingerprint")
            incremental_reuse.record(name, profile, captured)
        if name in (incremental_reuse._registry().get("services") or {}):
            diagnostics[name] = incremental_reuse.diagnose(name)
    performance["content_addressed_reuse"] = {
        "enabled": profile in {"fast_decision", "live"},
        "reused_services": sorted(
            name for name, row in service_results.items()
            if row.get("reuse_mode") == "CONTENT_ADDRESSED"
        ),
        "diagnostics": diagnostics,
    }
    return performance


def _install_hooks(profile_name: str) -> None:
    original_profile = domain_orchestrator._profile

    def patched_profile(mode, deep_stats, explicit):
        name, profile_cfg = original_profile(mode, deep_stats, explicit)
        profile_cfg = dict(profile_cfg)
        profile_cfg["_profile_name"] = name
        return name, profile_cfg

    domain_orchestrator._profile = patched_profile
    legacy._reuse_service = _reuse_service
    legacy._run_service = _run_service
    legacy._write_runtime_metadata = _write_runtime_metadata


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = False, profile: str | None = None):
    profile_name = str(profile or legacy._default_profile(mode, deep_stats))
    _install_hooks(profile_name)
    return domain_orchestrator.run(mode=mode, stats=stats, deep_stats=deep_stats, profile=profile_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "deadline", "live"], default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--profile", choices=["fast_decision", "live", "full_refresh", "deep_stats"])
    args = parser.parse_args()
    out = run(mode=args.mode, stats=args.stats, deep_stats=args.deep_stats, profile=args.profile)
    print(json.dumps({
        "incremental_wrapper": "V3_INCREMENTAL_REUSE_V1",
        "execution_profile": out.get("execution_profile"),
        "total_wall_ms": out.get("total_wall_ms"),
        "content_addressed_reuse": out.get("content_addressed_reuse"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
