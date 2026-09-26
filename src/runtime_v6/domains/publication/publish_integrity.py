from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from .authority_contract import (
    AuthorityContractError,
    FORBIDDEN_DOWNSTREAM_AUTHORITIES,
    validate_artifact_descriptor,
)
from .operational_reliability import refresh_operational_reliability
from .store import CANDIDATE_FREEZE, HEALTH, OUT, read_json, write_json

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

_FREEZE_RELATIVE_PATH = "health/candidate_freeze.lock"
_PUBLISH_INTEGRITY_RELATIVE_PATH = "health/publish_integrity.json"

# Public V6 may retain only post-disclosure/reproducible personal-adjacent facts.
# Current/manual/authenticated owner state belongs exclusively to the private plane.
_PUBLIC_PERSONAL_ALLOWED_RELATIVE_PATHS = {
    "personal/memberships.json",
    "personal/submitted_picks.json",
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


def _declared_or_collection_count(payload: dict[str, Any], count_key: str, collection_key: str) -> int:
    raw = payload.get(count_key)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    collection = payload.get(collection_key)
    return len(collection) if isinstance(collection, (list, dict)) else 0


def _identity_count_invariants(
    identity: dict[str, Any],
    canonical_players: dict[str, Any],
    canonical_teams: dict[str, Any],
    canonical_fixtures: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    bridges = dict(identity.get("entity_bridges") or {})
    team_bridge = dict(bridges.get("team") or {})
    fixture_bridge = dict(bridges.get("fixture") or {})

    canonical_counts = {
        "player": _declared_or_collection_count(canonical_players, "player_count", "players"),
        "team": _declared_or_collection_count(canonical_teams, "team_count", "teams"),
        "fixture": _declared_or_collection_count(canonical_fixtures, "fixture_count", "fixtures"),
    }
    identity_counts = {
        "player": int(identity.get("canonical_player_count") or 0),
        "team": int(team_bridge.get("canonical_team_count") or 0),
        "fixture": int(fixture_bridge.get("canonical_fixture_count") or 0),
    }
    mapping_counts = {
        "player": len(identity.get("mappings") or {}),
        "team": len(team_bridge.get("mappings") or {}),
        "fixture": len(fixture_bridge.get("mappings") or {}),
    }

    report: dict[str, dict[str, Any]] = {}
    for entity in ("player", "team", "fixture"):
        canonical_count = canonical_counts[entity]
        identity_count = identity_counts[entity]
        mapping_count = mapping_counts[entity]
        count_consistent = identity_count == canonical_count
        mapping_consistent = mapping_count == identity_count
        report[entity] = {
            "canonical_count": canonical_count,
            "identity_count": identity_count,
            "mapping_count": mapping_count,
            "count_consistent": count_consistent,
            "mapping_consistent": mapping_consistent,
            "consistent": count_consistent and mapping_consistent,
        }
        if not count_consistent:
            errors.append(f"identity_map_canonical_{entity}_count_mismatch")
        if not mapping_consistent:
            errors.append(f"identity_map_{entity}_mapping_count_mismatch")
    return report, errors


def _candidate_files(root: Path) -> list[Path]:
    excluded = {
        root / _FREEZE_RELATIVE_PATH,
        root / _PUBLISH_INTEGRITY_RELATIVE_PATH,
    }
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path not in excluded
        and not path.name.endswith(".tmp")
    )


def _candidate_tree_digest(root: Path) -> tuple[str, int]:
    aggregate = hashlib.sha256()
    files = _candidate_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(_sha256_file(path).encode("ascii"))
        aggregate.update(b"\n")
    return aggregate.hexdigest(), len(files)


def _current_run_id() -> str:
    return str(os.environ.get("GITHUB_RUN_ID") or "local")


def _current_run_attempt() -> str:
    return str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")


def _prepare_candidate_metadata(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path) or {}
    if not manifest:
        raise RuntimeError("candidate_prepare_manifest_missing_or_invalid")
    governance = dict(manifest.get("governance") or {})
    governance["candidate_freeze_required"] = True
    governance["post_freeze_mutation_fail_closed"] = True
    governance["publish_validator_is_read_only_after_freeze"] = True
    manifest["governance"] = governance
    paths = dict(manifest.get("paths") or {})
    paths["candidate_freeze"] = f"data/v6/{_FREEZE_RELATIVE_PATH}"
    manifest["paths"] = paths
    write_json(manifest_path, manifest)
    return manifest


def prepare_and_freeze_candidate(root: Path = OUT) -> dict[str, Any]:
    refresh_operational_reliability(
        manifest_path=root / "manifest.json",
        ledger_path=root / "health" / "operational_slots.json",
    )
    pruned = _prune_legacy_analytical_artifacts(root)
    manifest = _prepare_candidate_metadata(root)
    catalog = refresh_artifact_catalog(root)

    candidate_tree_sha256, artifact_count = _candidate_tree_digest(root)
    manifest_sha256 = _sha256_file(root / "manifest.json")
    resolved_registry_path = _resolve_runtime_path(
        root,
        (manifest.get("paths") or {}).get("resolved_registry") or "data/v6/evidence/resolved_registry.json",
    )
    resolved_registry = read_json(resolved_registry_path) or {}
    registry_fingerprint = _sha256_file(resolved_registry_path) if resolved_registry_path.is_file() else None
    control = dict(manifest.get("runtime_control") or {})
    logical_slot = (
        control.get("expected_cycle_at")
        or os.environ.get("V6_MASTER_LOGICAL_SLOT")
        or os.environ.get("V6_PREFETCH_LOGICAL_SLOT")
    )
    observed_at = control.get("cycle_observed_at") or manifest.get("generated_at")
    run_id = _current_run_id()
    run_attempt = _current_run_attempt()
    candidate_generation_id = f"{run_id}:{run_attempt}:{candidate_tree_sha256[:16]}"
    freeze = {
        "schema_version": 1,
        "candidate_state": "FROZEN",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "logical_slot": logical_slot,
        "observed_at": observed_at,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "candidate_generation_id": candidate_generation_id,
        "publication_generation_id": None,
        "manifest_input_sha256": manifest_sha256,
        "candidate_tree_sha256": candidate_tree_sha256,
        "artifact_count": artifact_count,
        "registry_fingerprint": registry_fingerprint,
        "registry_epoch": resolved_registry.get("registry_epoch") or resolved_registry.get("epoch"),
        "registry_generated_at": resolved_registry.get("generated_at"),
        "pruned_legacy_analytical_artifacts": pruned,
        "artifact_catalog_record_count": catalog.get("record_count"),
        "artifact_catalog_sha256": catalog.get("catalog_sha256"),
        "governance": {
            "post_freeze_mutation_fail_closed": True,
            "validator_read_only": True,
            "failed_candidate_must_not_be_promoted": True,
        },
    }
    write_json(root / _FREEZE_RELATIVE_PATH, freeze)
    return freeze


def validate_publish_tree(root: Path = OUT) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path) or {}
    errors: list[str] = []
    if not manifest:
        errors.append("manifest_missing_or_invalid")
        return {
            "schema_version": 4,
            "status": "FAIL",
            "errors": errors,
            "source_count": 0,
            "checked_file_count": 0,
            "semantic_checked_file_count": 0,
            "tree_sha256": None,
        }

    personal_root = root / "personal"
    if personal_root.exists():
        for path in sorted(personal_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative not in _PUBLIC_PERSONAL_ALLOWED_RELATIVE_PATHS:
                errors.append(
                    f"private_personal_artifact_in_public_tree:{relative}"
                )

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
    canonical_teams_path = _resolve_runtime_path(
        root,
        paths.get("canonical_teams") or "data/v6/normalized/canonical_teams.json",
    )
    canonical_fixtures_path = _resolve_runtime_path(
        root,
        paths.get("canonical_fixtures") or "data/v6/normalized/canonical_fixtures.json",
    )
    canonical_players = read_json(canonical_players_path) or {}
    canonical_teams = read_json(canonical_teams_path) or {}
    canonical_fixtures = read_json(canonical_fixtures_path) or {}
    identity_counts: dict[str, dict[str, Any]] = {}
    if identity and canonical_players and canonical_teams and canonical_fixtures:
        identity_counts, identity_errors = _identity_count_invariants(
            identity,
            canonical_players,
            canonical_teams,
            canonical_fixtures,
        )
        errors.extend(identity_errors)
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
    identity_map_consistent = bool(identity_counts) and all(
        row.get("consistent") is True for row in identity_counts.values()
    )
    return {
        "schema_version": 4,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_count": len(source_ids),
        "checked_file_count": len(files),
        "semantic_checked_file_count": semantic_checked,
        "tree_sha256": aggregate.hexdigest(),
        "current_source_files_exact": actual_current == expected_current,
        "resolved_registry_exact": resolved_registry_exact,
        "identity_map_consistent": identity_map_consistent,
        "identity_counts": identity_counts,
        "artifact_catalog_required": artifact_catalog_required,
        "artifact_catalog_valid": bool(catalog_validation.get("valid")),
        "artifact_catalog_checked_count": int(catalog_validation.get("checked") or 0),
        "semantic_authority_enforced": True,
        "canonical_mini_league_analytics_forbidden": True,
        "public_personal_allowlist_enforced": True,
    }


def validate_frozen_candidate(root: Path = OUT) -> dict[str, Any]:
    freeze = read_json(root / _FREEZE_RELATIVE_PATH) or {}
    report = validate_publish_tree(root)
    errors = list(report.get("errors") or [])
    candidate_tree_sha256, artifact_count = _candidate_tree_digest(root)

    if freeze.get("candidate_state") != "FROZEN":
        errors.append("candidate_freeze_missing_or_invalid")
    else:
        if freeze.get("candidate_tree_sha256") != candidate_tree_sha256:
            errors.append("candidate_tree_changed_after_freeze")
        if int(freeze.get("artifact_count") or -1) != artifact_count:
            errors.append("candidate_artifact_count_changed_after_freeze")
        frozen_run_id = str(freeze.get("run_id") or "")
        current_run_id = _current_run_id()
        if frozen_run_id and current_run_id != "local" and frozen_run_id != current_run_id:
            errors.append("candidate_freeze_run_id_mismatch")

    report.update(
        {
            "schema_version": 5,
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            "first_error": errors[0] if errors else None,
            "check_name": "publish_tree_integrity",
            "failed_path": None,
            "candidate_frozen": freeze.get("candidate_state") == "FROZEN",
            "candidate_state": freeze.get("candidate_state"),
            "frozen_at": freeze.get("frozen_at"),
            "logical_slot": freeze.get("logical_slot"),
            "observed_at": freeze.get("observed_at"),
            "run_id": freeze.get("run_id"),
            "run_attempt": freeze.get("run_attempt"),
            "candidate_generation_id": freeze.get("candidate_generation_id"),
            "publication_generation_id": None,
            "manifest_input_sha256": freeze.get("manifest_input_sha256"),
            "candidate_tree_sha256": candidate_tree_sha256,
            "frozen_candidate_tree_sha256": freeze.get("candidate_tree_sha256"),
            "candidate_artifact_count": artifact_count,
            "registry_fingerprint": freeze.get("registry_fingerprint"),
            "registry_epoch": freeze.get("registry_epoch"),
            "freeze_verified": (
                freeze.get("candidate_state") == "FROZEN"
                and freeze.get("candidate_tree_sha256") == candidate_tree_sha256
                and int(freeze.get("artifact_count") or -1) == artifact_count
            ),
            "validator_read_only_after_freeze": True,
            "post_freeze_mutation_fail_closed": True,
            "pruned_legacy_analytical_artifacts": freeze.get("pruned_legacy_analytical_artifacts") or [],
            "artifact_catalog_record_count": freeze.get("artifact_catalog_record_count"),
            "artifact_catalog_sha256": freeze.get("artifact_catalog_sha256"),
        }
    )
    return report


def _write_validation_report(report: dict[str, Any], root: Path = OUT) -> None:
    write_json(root / _PUBLISH_INTEGRITY_RELATIVE_PATH, report)


def main() -> int:
    parser = argparse.ArgumentParser(description="V6 publish candidate lifecycle")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "prepare", "validate"])
    args = parser.parse_args()

    if args.command in {"run", "prepare"}:
        freeze = prepare_and_freeze_candidate(OUT)
        print(json.dumps({"phase": "FROZEN", **freeze}, ensure_ascii=False))
        if args.command == "prepare":
            return 0

    report = validate_frozen_candidate(OUT)
    _write_validation_report(report, OUT)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
