from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .store import HEALTH, MANIFEST, OUT, read_json, write_json

_REQUIRED_PATH_KEYS = {
    "current_sources",
    "health",
    "canonical_players",
    "canonical_teams",
    "canonical_fixtures",
    "lineage",
    "evidence_index",
    "resolved_registry",
    "runtime_control",
    "publish_integrity",
}


def _resolve_runtime_path(root: Path, configured: str) -> Path:
    value = str(configured)
    prefix = "data/v6/"
    if value.startswith(prefix):
        value = value[len(prefix):]
    return root / value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_publish_tree(root: Path = OUT) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path) or {}
    errors: list[str] = []
    if not manifest:
        errors.append("manifest_missing_or_invalid")
        return {
            "schema_version": 1,
            "status": "FAIL",
            "errors": errors,
            "source_count": 0,
            "checked_file_count": 0,
            "tree_sha256": None,
        }

    source_ids = [str(source_id) for source_id in manifest.get("source_ids") or []]
    if int(manifest.get("source_count") or 0) != len(source_ids):
        errors.append("manifest_source_count_mismatch")
    if len(set(source_ids)) != len(source_ids):
        errors.append("duplicate_manifest_source_ids")

    paths = dict(manifest.get("paths") or {})
    missing_path_keys = sorted(_REQUIRED_PATH_KEYS - set(paths))
    if missing_path_keys:
        errors.append(f"manifest_paths_missing:{','.join(missing_path_keys)}")

    current_dir = _resolve_runtime_path(root, paths.get("current_sources") or "data/v6/current/")
    expected_current = {f"{source_id}.json" for source_id in source_ids}
    actual_current = {path.name for path in current_dir.glob("*.json")} if current_dir.exists() else set()
    if actual_current != expected_current:
        missing = sorted(expected_current - actual_current)
        extra = sorted(actual_current - expected_current)
        if missing:
            errors.append(f"current_sources_missing:{','.join(missing)}")
        if extra:
            errors.append(f"current_sources_extra:{','.join(extra)}")

    for source_id in source_ids:
        payload = read_json(current_dir / f"{source_id}.json")
        if not payload:
            continue
        if str(payload.get("source_id")) != source_id:
            errors.append(f"source_identity_mismatch:{source_id}")

    for key, configured in paths.items():
        if key in {"current_sources", "publish_integrity"}:
            continue
        path = _resolve_runtime_path(root, configured)
        if not path.is_file():
            errors.append(f"required_artifact_missing:{key}")

    resolved_path = _resolve_runtime_path(root, paths.get("resolved_registry") or "data/v6/evidence/resolved_registry.json")
    resolved = read_json(resolved_path) or {}
    if resolved and int(resolved.get("source_count") or 0) != len(source_ids):
        errors.append("resolved_registry_source_count_mismatch")

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path != root / "health" / "publish_integrity.json" and not path.name.endswith(".tmp")
    )
    aggregate = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(_sha256_file(path).encode("ascii"))
        aggregate.update(b"\n")

    return {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_count": len(source_ids),
        "checked_file_count": len(files),
        "tree_sha256": aggregate.hexdigest(),
        "current_source_files_exact": actual_current == expected_current,
    }


def main() -> int:
    report = validate_publish_tree(OUT)
    write_json(HEALTH / "publish_integrity.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
