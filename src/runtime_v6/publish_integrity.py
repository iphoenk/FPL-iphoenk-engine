from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .store import HEALTH, OUT, read_json, write_json

_REQUIRED_PATH_KEYS = {
    "current_sources",
    "health",
    "canonical_players",
    "canonical_teams",
    "canonical_fixtures",
    "lineage",
    "evidence_index",
    "resolved_registry",
    "player_identity_map",
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

    resolved_path = _resolve_runtime_path(
        root,
        paths.get("resolved_registry") or "data/v6/evidence/resolved_registry.json",
    )
    resolved = read_json(resolved_path) or {}
    if resolved:
        resolved_sources = list(resolved.get("sources") or [])
        resolved_source_ids = [str(source.get("id")) for source in resolved_sources]
        if int(resolved.get("source_count") or 0) != len(source_ids):
            errors.append("resolved_registry_source_count_mismatch")
        if resolved_source_ids != source_ids:
            errors.append("resolved_registry_source_ids_mismatch")
        if len(set(resolved_source_ids)) != len(resolved_source_ids):
            errors.append("resolved_registry_duplicate_source_ids")

    identity_path = _resolve_runtime_path(
        root,
        paths.get("player_identity_map") or "data/v6/evidence/player_identity_map.json",
    )
    identity = read_json(identity_path) or {}
    canonical_players_path = _resolve_runtime_path(
        root,
        paths.get("canonical_players") or "data/v6/normalized/canonical_players.json",
    )
    canonical_players = read_json(canonical_players_path) or {}
    identity_count = int(identity.get("canonical_player_count") or 0)
    canonical_count = int(canonical_players.get("player_count") or 0)
    if identity and canonical_players and identity_count != canonical_count:
        errors.append("identity_map_canonical_player_count_mismatch")
    if identity and (identity.get("governance") or {}).get("fuzzy_name_matching_allowed") is not False:
        errors.append("identity_map_fuzzy_matching_policy_invalid")

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path != root / "health" / "publish_integrity.json"
        and not path.name.endswith(".tmp")
    )
    aggregate = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(_sha256_file(path).encode("ascii"))
        aggregate.update(b"\n")

    resolved_registry_exact = bool(resolved) and [
        str(source.get("id")) for source in resolved.get("sources") or []
    ] == source_ids
    return {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_count": len(source_ids),
        "checked_file_count": len(files),
        "tree_sha256": aggregate.hexdigest(),
        "current_source_files_exact": actual_current == expected_current,
        "resolved_registry_exact": resolved_registry_exact,
        "identity_map_consistent": identity_count == canonical_count if identity and canonical_players else False,
    }


def main() -> int:
    report = validate_publish_tree(OUT)
    write_json(HEALTH / "publish_integrity.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
