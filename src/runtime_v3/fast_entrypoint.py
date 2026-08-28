from __future__ import annotations

"""Correctness-preserving low-latency adapter for FAST/LIVE.

The canonical orchestrator remains the reference implementation used by
FULL/DEEP.  FAST/LIVE patch only two runtime mechanics:

1. reuse age is based on an artifact's own logical `generated_at`, never the
   filesystem mtime produced by GitHub hydration;
2. registry-declared multi-command logical services may execute through one
   bundle process, while artifact ownership, validation and promotion remain
   owned by the canonical orchestrator.

No football formula or decision rule is changed here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_v3 import orchestrator as base

_ORIGINAL_RUN_SERVICE = base._run_service


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
    for key in ("generated_at", "updated_at", "captured_at", "observed_at"):
        dt = _parse_ts(payload.get(key))
        if dt is not None:
            return dt
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
    artifacts = [str(name) for name in spec.get("artifacts") or []]
    if not artifacts:
        return None
    paths = [canonical / name for name in artifacts]
    if not all(path.exists() and path.is_file() for path in paths):
        return None

    # The first declared artifact is the service's canonical freshness clock.
    # Hydration mtime is intentionally ignored because `git show > file`
    # makes old content look new on disk.
    logical_time = _logical_generated_at(paths[0])
    if logical_time is None:
        return None
    age_seconds = max(0.0, (datetime.now(timezone.utc) - logical_time).total_seconds())
    if age_seconds > max_age:
        return None

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
        "reuse_time_source": f"{artifacts[0]}:generated_at",
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
    if bundle:
        result["command_bundle"] = str(bundle)
        result["bundled_command_count"] = len(spec.get("commands") or [])
    return result


def install() -> None:
    base._reuse_service = _logical_reuse_service
    base._run_service = _bundled_run_service


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
