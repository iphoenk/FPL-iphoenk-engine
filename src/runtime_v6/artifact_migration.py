from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_provenance import build_artifact_meta, source_snapshot_ids_for_payload
from .http_client import utc_now
from .store import OUT, read_json, write_json

CANONICAL_AUTHORITY = "official_fpl"
CANONICAL_SEMANTIC_CLASS = "NORMALIZED_FACT"
CANONICAL_NORMALIZATION_VERSION = "V6_CANONICAL_FPL_1"


@dataclass(frozen=True)
class CanonicalArtifactSpec:
    relative_path: str
    count_key: str
    collection_key: str
    official_collection: str
    primary_key: str


_CANONICAL_ARTIFACTS = (
    CanonicalArtifactSpec(
        "normalized/canonical_players.json",
        "player_count",
        "players",
        "elements",
        "official_fpl_element_id",
    ),
    CanonicalArtifactSpec(
        "normalized/canonical_teams.json",
        "team_count",
        "teams",
        "teams",
        "official_fpl_team_id",
    ),
    CanonicalArtifactSpec(
        "normalized/canonical_fixtures.json",
        "fixture_count",
        "fixtures",
        "fixtures",
        "official_fpl_fixture_id",
    ),
)


def _declared_count(payload: dict[str, Any], count_key: str, collection_key: str) -> int | None:
    value = payload.get(count_key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    rows = payload.get(collection_key)
    return len(rows) if isinstance(rows, list) else None


def _official_rows(official: dict[str, Any], collection: str) -> list[Any] | None:
    official_payload = official.get("official") or {}
    if collection == "fixtures":
        rows = official_payload.get("fixtures")
    else:
        rows = (official_payload.get("bootstrap") or {}).get(collection)
    return rows if isinstance(rows, list) else None


def migrate_legacy_canonical_provenance(root: Path = OUT) -> dict[str, Any]:
    """Upgrade hydrated pre-contract canonical artifacts without fabricating lineage.

    Migration is deliberately narrow: only the three Official-FPL canonical datasets
    are eligible, their row counts must still match the immutable hydrated Official FPL
    snapshot, and that snapshot must expose digest-qualified source identities.
    """
    official_path = root / "current" / "official_fpl.json"
    official = read_json(official_path) or {}
    errors: list[str] = []
    migrated: list[str] = []
    already_complete: list[str] = []

    snapshot_ids = source_snapshot_ids_for_payload(official)
    effective_at = official.get("checked_at") or official.get("effective_at")
    if not official:
        errors.append("legacy_provenance_migration:official_fpl_snapshot_missing")
    if not snapshot_ids:
        errors.append("legacy_provenance_migration:official_fpl_immutable_snapshot_ids_missing")
    if not effective_at:
        errors.append("legacy_provenance_migration:official_fpl_effective_at_missing")
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "migrated": migrated,
            "already_complete": already_complete,
        }

    for spec in _CANONICAL_ARTIFACTS:
        path = root / spec.relative_path
        payload = read_json(path) or {}
        if not payload:
            errors.append(f"legacy_provenance_migration:artifact_missing:{spec.relative_path}")
            continue

        meta = build_artifact_meta(root, spec.relative_path)
        if meta.get("provenance_status") == "COMPLETE":
            already_complete.append(spec.relative_path)
            continue

        if payload.get("canonical") is False:
            errors.append(f"legacy_provenance_migration:noncanonical_artifact:{spec.relative_path}")
            continue
        authority = payload.get("authority")
        if authority not in (None, "", CANONICAL_AUTHORITY):
            errors.append(f"legacy_provenance_migration:authority_mismatch:{spec.relative_path}")
            continue

        canonical_count = _declared_count(payload, spec.count_key, spec.collection_key)
        official_rows = _official_rows(official, spec.official_collection)
        if canonical_count is None or official_rows is None or canonical_count != len(official_rows):
            errors.append(f"legacy_provenance_migration:count_mismatch:{spec.relative_path}")
            continue

        upgraded = dict(payload)
        upgraded["canonical"] = True
        upgraded["authority"] = CANONICAL_AUTHORITY
        upgraded["semantic_class"] = CANONICAL_SEMANTIC_CLASS
        upgraded["generated_at"] = upgraded.get("generated_at") or utc_now()
        upgraded["effective_at"] = effective_at
        upgraded["normalization_version"] = CANONICAL_NORMALIZATION_VERSION
        upgraded["primary_keys"] = [spec.primary_key]
        upgraded["source_snapshot_ids"] = snapshot_ids
        upgraded["provenance_migration"] = {
            "contract": "V6_ARTIFACT_PROVENANCE_1",
            "mode": "HYDRATED_LEGACY_CANONICAL_METADATA_ONLY",
            "row_data_changed": False,
            "source": "data/v6/current/official_fpl.json",
        }
        write_json(path, upgraded)

        upgraded_meta = build_artifact_meta(root, spec.relative_path)
        if upgraded_meta.get("provenance_status") != "COMPLETE":
            errors.append(f"legacy_provenance_migration:postcondition_failed:{spec.relative_path}")
            continue
        migrated.append(spec.relative_path)

    return {
        "valid": not errors,
        "errors": errors,
        "migrated": migrated,
        "already_complete": already_complete,
        "immutable_source_snapshot_count": len(snapshot_ids),
        "effective_at": effective_at,
    }
