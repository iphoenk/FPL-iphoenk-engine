from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_v3.artifact_contracts import validate_artifact


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _json_path(payload: Any, path: Any) -> Any:
    current = payload
    for part in path or []:
        if isinstance(current, dict):
            current = current.get(str(part))
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (TypeError, ValueError, IndexError):
                return None
        else:
            return None
    return current


def _semantic_timestamp(path: Path, field: str) -> datetime | None:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    return _parse_utc(payload.get(field))


def _json_array_to_keyed_object_field_match(guard: dict[str, Any], canonical: Path) -> bool:
    source_artifact = str(guard.get("source_artifact") or "").strip()
    cached_artifact = str(guard.get("cached_artifact") or "").strip()
    source_key = str(guard.get("source_key") or "").strip()
    field_map = guard.get("field_map") or {}
    if not source_artifact or not cached_artifact or not source_key or not isinstance(field_map, dict) or not field_map:
        return False

    source_payload = _read_json(canonical / source_artifact)
    cached_payload = _read_json(canonical / cached_artifact)
    source_rows = _json_path(source_payload, guard.get("source_path") or [])
    cached_rows = _json_path(cached_payload, guard.get("cached_path") or [])
    if not isinstance(source_rows, list) or not isinstance(cached_rows, dict):
        return False

    source_index: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, dict) or row.get(source_key) in {None, ""}:
            return False
        key = str(row.get(source_key))
        if key in source_index:
            return False
        source_index[key] = row

    if set(source_index) != {str(key) for key in cached_rows}:
        return False

    for key, source_row in source_index.items():
        cached_row = cached_rows.get(key)
        if not isinstance(cached_row, dict):
            return False
        for source_field, cached_field in field_map.items():
            if source_row.get(str(source_field)) != cached_row.get(str(cached_field)):
                return False
    return True


def _semantic_reuse_guards_pass(reuse_cfg: dict[str, Any], canonical: Path) -> bool:
    guards = reuse_cfg.get("semantic_guards") or []
    if not isinstance(guards, list):
        return False
    for guard in guards:
        if not isinstance(guard, dict):
            return False
        guard_type = str(guard.get("type") or "").strip()
        if guard_type == "JSON_ARRAY_TO_KEYED_OBJECT_FIELD_MATCH_V1":
            if not _json_array_to_keyed_object_field_match(guard, canonical):
                return False
        else:
            return False
    return True


def _restore_workspace_retry_artifact(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.warm-retry-{os.getpid()}.tmp")
    try:
        shutil.copy2(source, staging)
        os.replace(staging, target)
    finally:
        if staging.exists():
            staging.unlink()


def reuse_service(
    name: str,
    spec: dict[str, Any],
    canonical: Path,
    profile_cfg: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Reuse one capability only when semantic freshness and declared guards pass.

    Filesystem mtimes are intentionally ignored because runtime hydration rewrites
    cached artifacts and therefore cannot preserve source-generation freshness.
    A non-positive TTL disables age-based reuse completely. Missing or malformed
    freshness metadata fails closed to a normal capability refresh.

    Optional registry-owned semantic guards may additionally bind a cached
    capability to current authoritative evidence. Unknown or malformed guards
    fail closed rather than silently reusing semantically stale artifacts.

    A profile may declare one workspace-local retry mirror for its freshness
    artifact. This is only a same-working-directory recovery primitive: the mirror
    must still be semantically fresh, is restored atomically into the canonical
    artifact path, and remains subject to normal artifact validation. Publication
    and hydration policy decide whether that mirror can cross a production job.
    """
    reuse_cfg = (profile_cfg.get("reuse_services") or {}).get(name)
    if not isinstance(reuse_cfg, dict):
        return None
    try:
        max_age_seconds = float(reuse_cfg.get("max_age_seconds") or 0)
    except (TypeError, ValueError):
        return None
    if max_age_seconds <= 0:
        return None

    artifacts = [str(value) for value in spec.get("artifacts") or []]
    if not artifacts:
        return None

    freshness_artifact = str(reuse_cfg.get("freshness_artifact") or "").strip()
    freshness_field = str(reuse_cfg.get("freshness_field") or "generated_at").strip()
    if not freshness_artifact or freshness_artifact not in artifacts or not freshness_field:
        return None

    freshness_path = canonical / freshness_artifact
    semantic_path = freshness_path
    retry_artifact = str(reuse_cfg.get("workspace_retry_artifact") or "").strip()
    restored_from_retry = False
    if not freshness_path.is_file():
        if not retry_artifact:
            return None
        retry_path = canonical / retry_artifact
        if not retry_path.is_file():
            return None
        semantic_path = retry_path
        restored_from_retry = True

    generated_at = _semantic_timestamp(semantic_path, freshness_field)
    if generated_at is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    age_seconds = max(0.0, (current - generated_at).total_seconds())
    if age_seconds > max_age_seconds:
        return None

    if restored_from_retry:
        _restore_workspace_retry_artifact(semantic_path, freshness_path)

    paths = [canonical / artifact for artifact in artifacts]
    if any(not path.exists() or not path.is_file() for path in paths):
        return None

    if not _semantic_reuse_guards_pass(reuse_cfg, canonical):
        return None

    validations = [validate_artifact(path, artifact) for path, artifact in zip(paths, artifacts)]
    return {
        "service": name,
        "status": "REUSED",
        "reused": True,
        "elapsed_ms": 0.0,
        "artifacts": artifacts,
        "artifact_validation": validations,
        "reuse_mode": "AGE_TTL",
        "reuse_freshness_source": "SEMANTIC_TIMESTAMP",
        "reuse_freshness_artifact": freshness_artifact,
        "reuse_freshness_field": freshness_field,
        "reuse_freshness_timestamp": generated_at.isoformat(),
        "reuse_age_seconds": round(age_seconds, 3),
        "reuse_max_age_seconds": max_age_seconds,
        "semantic_guard_count": len(reuse_cfg.get("semantic_guards") or []),
        "workspace_retry_restored": restored_from_retry,
        "workspace_retry_artifact": retry_artifact if restored_from_retry else None,
    }
