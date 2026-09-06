from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .store import OUT, write_json

CATALOG_RELATIVE_PATH = Path("evidence/artifact_catalog.json")
_PUBLISH_INTEGRITY_RELATIVE_PATH = Path("health/publish_integrity.json")


def _sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def _read_payload(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _payload_digests(value: Any, out: set[str], *, limit: int = 64) -> None:
    if len(out) >= limit:
        return
    if isinstance(value, dict):
        digest = value.get("payload_digest")
        if isinstance(digest, str) and digest:
            out.add(digest)
        for child in value.values():
            _payload_digests(child, out, limit=limit)
            if len(out) >= limit:
                break
    elif isinstance(value, list):
        for child in value:
            _payload_digests(child, out, limit=limit)
            if len(out) >= limit:
                break


def _record_count(payload: dict[str, Any]) -> int | None:
    for key in (
        "player_count",
        "team_count",
        "fixture_count",
        "source_count",
        "manager_count",
        "collected_manager_count",
        "record_count",
    ):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    for key in ("players", "teams", "fixtures", "managers", "elements", "sources", "reconciliations", "artifacts"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    entries = payload.get("entries")
    if isinstance(entries, dict):
        return len(entries)
    data = payload.get("data")
    if isinstance(data, dict):
        return len(data)
    return None


def _primary_keys(relative: str) -> list[str]:
    if relative.startswith("current/"):
        return ["request_id"]
    if relative.endswith("canonical_players.json"):
        return ["canonical_player_id"]
    if relative.endswith("canonical_teams.json"):
        return ["canonical_team_id"]
    if relative.endswith("canonical_fixtures.json"):
        return ["canonical_fixture_id"]
    if relative.endswith("player_identity_map.json"):
        return ["official_fpl_element_id", "source_id"]
    if relative.endswith("standings.json") or relative.endswith("managers.json"):
        return ["entry_id"]
    if relative.endswith("manager_picks.json") or "_manager_picks.json" in relative:
        return ["league_id", "gw", "entry_id", "element_id"]
    if relative.endswith("event_points.json") or relative.endswith("live_state.json"):
        return ["gw", "element_id"]
    if relative.endswith("entry_history.json"):
        return ["entry_id", "gw"]
    if relative.endswith("manager_history.json"):
        return ["entry_id", "gw"]
    return []


def _freshness_class(payload: dict[str, Any], relative: str) -> str:
    if payload.get("immutable_completed_gw_facts") is True:
        return "IMMUTABLE_HISTORICAL"
    if payload.get("fresh_for_target_report") is True:
        return "FRESH"
    if payload.get("fresh_for_target_report") is False:
        return "STALE"
    health = str(payload.get("health") or payload.get("overall") or "").upper()
    state = str(payload.get("effective_state") or "").upper()
    if health == "GREEN" or state.startswith("LIVE") or state == "SCHEDULED_CACHE":
        return "FRESH_OR_CURRENT"
    if health in {"AMBER", "PARTIAL", "STALE"} or "STALE" in state or "PARTIAL" in state:
        return "DEGRADED"
    if "/history/" in f"/{relative}" and payload.get("gw_semantics") == "COMPLETED_GW":
        return "IMMUTABLE_HISTORICAL"
    return "UNCLASSIFIED"


def _artifact_entry(root: Path, path: Path, producer_commit_sha: str | None) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    payload = _read_payload(path)
    digests: set[str] = set()
    if payload is not None:
        _payload_digests(payload, digests)
    generated_at = None
    effective_at = None
    schema_version = None
    authority = None
    semantic_class = None
    normalization_version = None
    canonical = None
    if payload is not None:
        generated_at = payload.get("generated_at") or payload.get("checked_at") or payload.get("requested_at")
        effective_at = payload.get("effective_at") or payload.get("checked_at") or generated_at
        schema_version = payload.get("schema_version")
        authority = payload.get("authority")
        semantic_class = payload.get("semantic_class") or payload.get("artifact_class")
        normalization_version = payload.get("normalization_version")
        canonical = payload.get("canonical") is not False

    return {
        "artifact_id": relative,
        "path": f"data/v6/{relative}",
        "schema_version": schema_version,
        "producer_commit_sha": producer_commit_sha,
        "source_snapshot_ids": sorted(digests),
        "generated_at": generated_at,
        "effective_at": effective_at,
        "record_count": _record_count(payload or {}),
        "primary_keys": _primary_keys(relative),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
        "freshness_class": _freshness_class(payload or {}, relative),
        "authority": authority,
        "semantic_class": semantic_class,
        "normalization_version": normalization_version,
        "canonical": canonical,
    }


def build_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    producer_commit_sha = (os.getenv("GITHUB_SHA") or "").strip() or None
    excluded = {
        CATALOG_RELATIVE_PATH.as_posix(),
        _PUBLISH_INTEGRITY_RELATIVE_PATH.as_posix(),
    }
    files = sorted(
        path
        for path in root.rglob("*.json")
        if path.is_file()
        and path.relative_to(root).as_posix() not in excluded
        and not path.name.endswith(".tmp")
    )
    artifacts = [_artifact_entry(root, path, producer_commit_sha) for path in files]
    return {
        "schema_version": 1,
        "artifact_class": "V6_ARTIFACT_CATALOG",
        "semantic_class": "CONTROL_TELEMETRY",
        "canonical": True,
        "producer_commit_sha": producer_commit_sha,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "excluded_self_paths": [
            f"data/v6/{CATALOG_RELATIVE_PATH.as_posix()}",
            f"data/v6/{_PUBLISH_INTEGRITY_RELATIVE_PATH.as_posix()}",
        ],
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "catalog_describes_exact_atomic_artifacts": True,
            "catalog_does_not_create_analytical_authority": True,
        },
    }


def write_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    catalog = build_artifact_catalog(root)
    write_json(root / CATALOG_RELATIVE_PATH, catalog)
    return catalog
