from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .prefetch_contract import artifact_meta
from .store import EVIDENCE, OUT, write_json

CATALOG_RELATIVE_PATH = "evidence/artifact_catalog.json"
PUBLISH_INTEGRITY_RELATIVE_PATH = "health/publish_integrity.json"


def _catalog_digest(artifacts: list[dict[str, Any]]) -> str:
    raw = json.dumps(artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _iter_catalogued_files(root: Path) -> list[Path]:
    excluded = {
        root / CATALOG_RELATIVE_PATH,
        root / PUBLISH_INTEGRITY_RELATIVE_PATH,
    }
    return sorted(
        path
        for path in root.rglob("*.json")
        if path.is_file() and path not in excluded and not path.name.endswith(".tmp")
    )


def build_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in _iter_catalogued_files(root):
        relative = path.relative_to(root).as_posix()
        meta = artifact_meta(root, relative)
        meta["producer_sha"] = os.getenv("GITHUB_SHA")
        artifacts.append(meta)

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "canonical": True,
        "semantic_class": "CONTROL_TELEMETRY",
        "authority": "V6_DATA_PLATFORM",
        "generated_at": generated_at,
        "effective_at": generated_at,
        "normalization_version": "v6-artifact-catalog-1",
        "primary_keys": ["path"],
        "record_count": len(artifacts),
        "catalog_sha256": _catalog_digest(artifacts),
        "producer_sha": os.getenv("GITHUB_SHA"),
        "excluded_paths": [
            f"data/v6/{CATALOG_RELATIVE_PATH}",
            f"data/v6/{PUBLISH_INTEGRITY_RELATIVE_PATH}",
        ],
        "artifacts": artifacts,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "catalog_is_non_recursive": True,
            "publish_integrity_is_excluded_to_avoid_digest_cycle": True,
        },
    }


def refresh_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    catalog = build_artifact_catalog(root)
    target = root / CATALOG_RELATIVE_PATH
    write_json(target, catalog)
    return catalog


def validate_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    path = root / CATALOG_RELATIVE_PATH
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"valid": False, "errors": ["artifact_catalog_missing_or_invalid"], "checked": 0}
    errors: list[str] = []
    artifacts = list(catalog.get("artifacts") or [])
    if int(catalog.get("record_count") or -1) != len(artifacts):
        errors.append("artifact_catalog_record_count_mismatch")
    if catalog.get("catalog_sha256") != _catalog_digest(artifacts):
        errors.append("artifact_catalog_digest_mismatch")

    expected_paths = {path.relative_to(root).as_posix() for path in _iter_catalogued_files(root)}
    catalog_paths: set[str] = set()
    for meta in artifacts:
        if not isinstance(meta, dict):
            errors.append("artifact_catalog_non_object_entry")
            continue
        configured = str(meta.get("path") or "")
        relative = configured.removeprefix("data/v6/")
        if not relative:
            errors.append("artifact_catalog_entry_missing_path")
            continue
        if relative in catalog_paths:
            errors.append(f"artifact_catalog_duplicate_path:{relative}")
            continue
        catalog_paths.add(relative)
        artifact_path = root / relative
        if not artifact_path.is_file():
            errors.append(f"artifact_catalog_missing_file:{relative}")
            continue
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != meta.get("sha256"):
            errors.append(f"artifact_catalog_sha_mismatch:{relative}")
        if artifact_path.stat().st_size != meta.get("bytes"):
            errors.append(f"artifact_catalog_size_mismatch:{relative}")

    missing = sorted(expected_paths - catalog_paths)
    extra = sorted(catalog_paths - expected_paths)
    if missing:
        errors.append(f"artifact_catalog_missing_paths:{','.join(missing)}")
    if extra:
        errors.append(f"artifact_catalog_extra_paths:{','.join(extra)}")
    return {"valid": not errors, "errors": errors, "checked": len(artifacts)}


def main() -> int:
    catalog = refresh_artifact_catalog(OUT)
    report = validate_artifact_catalog(OUT)
    print(json.dumps({"catalog": catalog, "validation": report}, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
