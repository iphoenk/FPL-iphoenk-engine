from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from .authority_contract import (
    AuthorityContractError,
    FORBIDDEN_DOWNSTREAM_AUTHORITIES,
    validate_artifact_descriptor,
)
from .store import HEALTH, OUT, read_json, write_json

_BASE_REQUIRED_PATH_KEYS = {
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
    "operational_slots",
    "publish_integrity",
}

_FORBIDDEN_CANONICAL_MINI_LEAGUE_AGGREGATES = {
    "ownership_percent",
    "mini_league_effective_ownership_percent",
    "managers_owned_count",
    "starts_count",
    "bench_count",
    "captain_count",
    "vice_count",
    "manager_multiplier_points",
    "manager_multiplier_points_semantics",
    "gap_to_first",
    "squad_overlap",
    "xi_overlap",
    "concentration_hhi",
    "rank_probability",
    "rival_leverage",
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


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _semantic_errors(path: Path, root: Path, payload: dict[str, Any]) -> list[str]:
    relative = path.relative_to(root).as_posix()
    errors: list[str] = []
    try:
        validate_artifact_descriptor(payload)
    except AuthorityContractError as exc:
        errors.append(f"semantic_contract:{relative}:{exc}")

    canonical = payload.get("canonical") is not False
    governance = dict(payload.get("governance") or {})
    if canonical:
        for authority in FORBIDDEN_DOWNSTREAM_AUTHORITIES:
            candidates = {
                authority,
                f"{authority}_authority",
            }
            for key in candidates:
                if key in governance and str(governance.get(key)).upper() != "NONE":
                    errors.append(f"forbidden_governance_authority:{relative}:{key}")
        if relative.startswith("mini_leagues/"):
            forbidden = sorted(_walk_keys(payload) & _FORBIDDEN_CANONICAL_MINI_LEAGUE_AGGREGATES)
            if forbidden:
                errors.append(
                    f"forbidden_canonical_mini_league_analytics:{relative}:{','.join(forbidden)}"
                )
    return errors


def _prune_legacy_analytical_artifacts(root: Path) -> list[str]:
    removed: list[str] = []
    patterns = (
        "mini_leagues/**/gw_*_exposure.json",
        "mini_leagues/**/history/gw_*/exposure.json",
        "mini_leagues/**/history/gw_*/standings_or_points.json",
        "mini_leagues/**/history/gw_*/transitions.json",
        "mini_leagues/**/history/longitudinal/player_ownership_history.json",
        "mini_leagues/**/history/longitudinal/captain_history.json",
        "mini_leagues/**/history/longitudinal/squad_overlap_history.json",
        "mini_leagues/**/history/longitudinal/transitions.json",
    )
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            path.unlink()
            removed.append(relative)
    return sorted(set(removed))


def validate_publish_tree(root: Path = OUT) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path) or {}
    errors: list[str] = []
    if not manifest:
        errors.append("manifest_missing_or_invalid")
        return {
            "schema_version": 3,
            "status": "FAIL",
            "errors": errors,
            "source_count": 0,
            "checked_file_count": 0,
            "semantic_checked_file_count": 0,
            "tree_sha256": None,
        }

    source_ids = [str(source_id) for source_id in manifest.get("source_ids") or []]
    if int(manifest.get("source_count") or 0) != len(source_ids):
        errors.append("manifest_source_count_mismatch")
    if len(set(source_ids)) != len(source_ids):
        errors.append("duplicate_manifest_source_ids")

    paths = dict(manifest.get("paths") or {})
    governance = dict(manifest.get("governance") or {})
    artifact_catalog_required = governance.get("artifact_catalog_required") is True
    required_path_keys = set(_BASE_REQUIRED_PATH_KEYS)
    if artifact_catalog_required:
        required_path_keys.update({"artifact_catalog", "verified_crosswalks"})
    missing_path_keys = sorted(required_path_keys - set(paths))
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

    for key in required_path_keys:
        if key in {"current_sources", "publish_integrity"}:
            continue
        configured = paths.get(key)
        if not configured:
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

    catalog_validation = {"valid": True, "errors": [], "checked": 0}
    if artifact_catalog_required:
        catalog_validation = validate_artifact_catalog(root)
        if not catalog_validation.get("valid"):
            errors.extend(str(error) for error in catalog_validation.get("errors") or [])

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path != root / "health" / "publish_integrity.json"
        and not path.name.endswith(".tmp")
    )
    semantic_checked = 0
    aggregate = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(_sha256_file(path).encode("ascii"))
        aggregate.update(b"\n")
        if path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            errors.append(f"invalid_json_artifact:{relative}")
            continue
        if isinstance(payload, dict):
            semantic_checked += 1
            errors.extend(_semantic_errors(path, root, payload))

    resolved_registry_exact = bool(resolved) and [
        str(source.get("id")) for source in resolved.get("sources") or []
    ] == source_ids
    return {
        "schema_version": 3,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_count": len(source_ids),
        "checked_file_count": len(files),
        "semantic_checked_file_count": semantic_checked,
        "tree_sha256": aggregate.hexdigest(),
        "current_source_files_exact": actual_current == expected_current,
        "resolved_registry_exact": resolved_registry_exact,
        "identity_map_consistent": identity_count == canonical_count if identity and canonical_players else False,
        "artifact_catalog_required": artifact_catalog_required,
        "artifact_catalog_valid": bool(catalog_validation.get("valid")),
        "artifact_catalog_checked_count": int(catalog_validation.get("checked") or 0),
        "semantic_authority_enforced": True,
        "canonical_mini_league_analytics_forbidden": True,
    }


def main() -> int:
    pruned = _prune_legacy_analytical_artifacts(OUT)
    catalog = refresh_artifact_catalog(OUT)
    report = validate_publish_tree(OUT)
    report["pruned_legacy_analytical_artifacts"] = pruned
    report["artifact_catalog_record_count"] = catalog.get("record_count")
    report["artifact_catalog_sha256"] = catalog.get("catalog_sha256")
    write_json(HEALTH / "publish_integrity.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
