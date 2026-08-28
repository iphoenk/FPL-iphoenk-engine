from __future__ import annotations

"""Correctness-preserving low-latency adapter for FAST/LIVE.

The canonical orchestrator remains the reference implementation used by
FULL/DEEP. FAST/LIVE patch runtime mechanics only:

1. logical-age reuse reads an artifact's own `generated_at`, never hydration
   filesystem mtime;
2. semantic reuse is allowed only when the current canonical input signature
   exactly matches the signature recorded by a prior run of the same engine
   version;
3. multi-command logical services may execute through one bundle process while
   artifact ownership, validation and promotion remain canonical.

No football formula or decision rule is changed here.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_v3 import orchestrator as base
from src.version import ENGINE_VERSION, SCHEMA_VERSION

_ORIGINAL_RUN_SERVICE = base._run_service
_PREVIOUS_PERFORMANCE: dict[str, Any] = {}
_VOLATILE_SIGNATURE_KEYS = {
    "generated_at",
    "fetched_at",
    "age_minutes",
    "elapsed_ms",
    "latency_ms",
    "performance_ms",
    "queue_wait_ms",
    "seed_input_ms",
    "promotion_ms",
    "validation_ms",
}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _logical_generated_at(path: Path) -> datetime | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("generated_at", "updated_at", "captured_at", "observed_at", "p0_overlay_generated_at", "lineup_overlay_generated_at", "decision_quality_overlay_generated_at"):
        dt = _parse_ts(payload.get(key))
        if dt is not None:
            return dt
    return None


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_SIGNATURE_KEYS
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _semantic_file_bytes(path: Path) -> bytes | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.read_bytes()
    normalized = _canonicalize(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _input_signature(service_name: str, reuse_cfg: dict[str, Any], canonical: Path) -> str | None:
    inputs = [str(value) for value in reuse_cfg.get("signature_inputs") or []]
    configs = [str(value) for value in reuse_cfg.get("signature_config_files") or []]
    if not inputs and not configs:
        return None
    digest = hashlib.sha256()
    digest.update(f"{ENGINE_VERSION}|{SCHEMA_VERSION}|{service_name}".encode("utf-8"))
    for rel in inputs:
        raw = _semantic_file_bytes(canonical / rel)
        if raw is None:
            return None
        digest.update(b"\nINPUT:")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\n")
        digest.update(raw)
    for rel in configs:
        path = base.ROOT / rel
        if not path.exists() or not path.is_file():
            return None
        digest.update(b"\nCONFIG:")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _reuse_artifacts(spec: dict[str, Any], reuse_cfg: dict[str, Any]) -> list[str]:
    override = [str(name) for name in reuse_cfg.get("artifacts") or []]
    return override or [str(name) for name in spec.get("artifacts") or []]


def _artifact_age_seconds(paths: list[Path]) -> tuple[float, str] | None:
    for path in paths:
        logical_time = _logical_generated_at(path)
        if logical_time is not None:
            age = max(0.0, (datetime.now(timezone.utc) - logical_time).total_seconds())
            return age, f"{path.name}:logical_generated_at"
    return None


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
    if mode == "semantic_signature":
        if str(_PREVIOUS_PERFORMANCE.get("engine_version") or "") != ENGINE_VERSION:
            return None
        signature = _input_signature(service_name, reuse_cfg, canonical)
        previous = ((_PREVIOUS_PERFORMANCE.get("services") or {}).get(service_name) or {})
        if not signature or previous.get("input_signature") != signature:
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
    global _PREVIOUS_PERFORMANCE
    _PREVIOUS_PERFORMANCE = base.read_json(base.PERFORMANCE_PATH, {})
    base._reuse_service = _logical_reuse_service
    base._run_service = _bundled_run_service


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
