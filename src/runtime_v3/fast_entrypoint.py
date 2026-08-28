from __future__ import annotations

"""Correctness-preserving low-latency adapter for FAST/LIVE.

The canonical orchestrator remains the reference implementation used by
FULL/DEEP. FAST/LIVE patch runtime mechanics only:

1. logical-age reuse reads an artifact's own logical timestamp, never hydration
   filesystem mtime;
2. semantic reuse requires an exact current input-signature match against the
   separately validated reuse manifest plus unchanged output hashes;
3. multi-command logical services may execute through one bundle process while
   artifact ownership, validation and promotion remain canonical.

No football formula or decision rule is changed here.
"""

from pathlib import Path
from typing import Any

from src.runtime_v3 import orchestrator as base
from src.runtime_v3.reuse_manifest import (
    artifact_age_seconds as _artifact_age_seconds,
    file_sha256,
    input_signature as _input_signature,
    load_manifest,
    logical_generated_at as _logical_generated_at,
    reuse_artifacts as _reuse_artifacts,
)
from src.version import ENGINE_VERSION, SCHEMA_VERSION

_ORIGINAL_RUN_SERVICE = base._run_service
_PREVIOUS_MANIFEST: dict[str, Any] = {}


def _logical_reuse_service(
    service_name: str,
    spec: dict[str, Any],
    canonical: Path,
    profile_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    reuse_cfg = (profile_cfg.get("reuse_services") or {}).get(service_name)
    if not isinstance(reuse_cfg, dict):
        return None
    max_age = float(reuse_cfg.get("max_age_seconds") or 0)
    if max_age <= 0:
        return None
    artifacts = _reuse_artifacts(spec, reuse_cfg)
    if not artifacts:
        return None
    paths = [canonical / name for name in artifacts]
    if not all(path.exists() and path.is_file() for path in paths):
        return None

    age_result = _artifact_age_seconds(paths)
    if age_result is None:
        return None
    age_seconds, time_source = age_result
    if age_seconds > max_age:
        return None

    mode = str(reuse_cfg.get("mode") or "logical_age")
    signature: str | None = None
    manifest_row: dict[str, Any] = {}
    if mode == "semantic_signature":
        if (
            str(_PREVIOUS_MANIFEST.get("engine_version") or "") != ENGINE_VERSION
            or int(_PREVIOUS_MANIFEST.get("engine_schema_version") or -1) != SCHEMA_VERSION
        ):
            return None
        signature = _input_signature(service_name, reuse_cfg, canonical)
        manifest_row = ((_PREVIOUS_MANIFEST.get("services") or {}).get(service_name) or {})
        if not signature or manifest_row.get("input_signature") != signature:
            return None
        expected_hashes = manifest_row.get("artifact_sha256") or {}
        if set(expected_hashes) != set(artifacts):
            return None
        for name, path in zip(artifacts, paths):
            if expected_hashes.get(name) != file_sha256(path):
                return None
    elif mode != "logical_age":
        raise RuntimeError(f"unsupported FAST reuse mode for {service_name}: {mode}")

    started = base.time.perf_counter()
    validations = [base.validate_artifact(path, name) for path, name in zip(paths, artifacts)]
    return {
        "service": service_name,
        "status": "REUSED",
        "isolated": False,
        "data_dir": str(canonical),
        "elapsed_ms": round((base.time.perf_counter() - started) * 1000.0, 3),
        "queue_wait_ms": 0.0,
        "seed_input_ms": 0.0,
        "seed_input_bytes": 0,
        "validation_ms": 0.0,
        "promotion_ms": 0.0,
        "promoted_output_bytes": 0,
        "reuse_age_seconds": round(age_seconds, 3),
        "reuse_max_age_seconds": max_age,
        "reuse_time_source": time_source,
        "reuse_mode": mode,
        "input_signature": signature,
        "manifest_hash_verified": mode == "semantic_signature",
        "artifact_validation": validations,
        "commands": [],
    }


def _bundled_run_service(
    service_name: str,
    spec: dict[str, Any],
    *,
    canonical: Path,
    services_root: Path,
    cache_dir: Path,
    context: dict[str, str],
    timeout: int,
    submitted_at: float,
) -> dict[str, Any]:
    profiles = base._load_profiles().get("profiles") or {}
    profile_cfg = profiles.get(str(context.get("profile") or "")) or {}
    reuse_cfg = (profile_cfg.get("reuse_services") or {}).get(service_name) or {}
    signature = _input_signature(service_name, reuse_cfg, canonical) if reuse_cfg.get("mode") == "semantic_signature" else None
    bundle = (profile_cfg.get("command_bundles") or {}).get(service_name)
    effective = spec
    if bundle:
        effective = dict(spec)
        effective["commands"] = [{"module": str(bundle), "args": []}]
    result = _ORIGINAL_RUN_SERVICE(
        service_name,
        effective,
        canonical=canonical,
        services_root=services_root,
        cache_dir=cache_dir,
        context=context,
        timeout=timeout,
        submitted_at=submitted_at,
    )
    if signature:
        result["input_signature"] = signature
        result["reuse_mode"] = "semantic_signature"
    if bundle:
        result["command_bundle"] = str(bundle)
        result["bundled_command_count"] = len(spec.get("commands") or [])
    return result


def install() -> None:
    global _PREVIOUS_MANIFEST
    _PREVIOUS_MANIFEST = load_manifest()
    base._reuse_service = _logical_reuse_service
    base._run_service = _bundled_run_service


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
