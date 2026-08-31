from __future__ import annotations

import json
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


def _semantic_timestamp(path: Path, field: str) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_utc(payload.get(field))


def reuse_service(
    name: str,
    spec: dict[str, Any],
    canonical: Path,
    profile_cfg: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Reuse one capability only when its registry-owned semantic timestamp is fresh.

    Filesystem mtimes are intentionally ignored because runtime hydration rewrites
    cached artifacts and therefore cannot preserve source-generation freshness.
    A non-positive TTL disables age-based reuse completely. Missing or malformed
    freshness metadata fails closed to a normal capability refresh.
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
    paths = [canonical / artifact for artifact in artifacts]
    if any(not path.exists() or not path.is_file() for path in paths):
        return None

    freshness_artifact = str(reuse_cfg.get("freshness_artifact") or "").strip()
    freshness_field = str(reuse_cfg.get("freshness_field") or "generated_at").strip()
    if not freshness_artifact or freshness_artifact not in artifacts or not freshness_field:
        return None

    freshness_path = canonical / freshness_artifact
    generated_at = _semantic_timestamp(freshness_path, freshness_field)
    if generated_at is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    age_seconds = max(0.0, (current - generated_at).total_seconds())
    if age_seconds > max_age_seconds:
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
    }
