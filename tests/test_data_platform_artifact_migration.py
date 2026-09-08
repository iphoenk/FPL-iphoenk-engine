from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from src.runtime_v6.artifact_migration import migrate_legacy_canonical_provenance

DIGEST = "c" * 64


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _official() -> dict:
    return {
        "schema_version": 4,
        "source_id": "official_fpl",
        "checked_at": "2026-09-08T06:34:00+00:00",
        "current_run_action": "FETCHED",
        "availability": "AVAILABLE",
        "attempts": [
            {"request_id": "bootstrap", "status": "AVAILABLE", "sha256": DIGEST},
        ],
        "official": {
            "bootstrap": {
                "elements": [{"id": 1}],
                "teams": [{"id": 1}],
            },
            "fixtures": [{"id": 10}],
        },
    }


def _legacy_canonical(root: Path) -> None:
    _write(
        root,
        "normalized/canonical_players.json",
        {
            "schema_version": 2,
            "generated_at": "2026-09-08T06:34:01+00:00",
            "authority": "official_fpl",
            "player_count": 1,
            "players": [{"official_fpl_element_id": 1}],
        },
    )
    _write(
        root,
        "normalized/canonical_teams.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-08T06:34:01+00:00",
            "authority": "official_fpl",
            "team_count": 1,
            "teams": [{"official_fpl_team_id": 1}],
        },
    )
    _write(
        root,
        "normalized/canonical_fixtures.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-08T06:34:01+00:00",
            "authority": "official_fpl",
            "fixture_count": 1,
            "fixtures": [{"official_fpl_fixture_id": 10}],
        },
    )


def test_hydrated_legacy_canonical_provenance_migrates_metadata_only(tmp_path: Path) -> None:
    _write(tmp_path, "current/official_fpl.json", _official())
    _legacy_canonical(tmp_path)
    before = json.loads((tmp_path / "normalized/canonical_players.json").read_text())["players"]

    result = migrate_legacy_canonical_provenance(tmp_path)

    assert result["valid"] is True
    assert len(result["migrated"]) == 3
    assert result["immutable_source_snapshot_count"] == 1
    players = json.loads((tmp_path / "normalized/canonical_players.json").read_text())
    assert players["players"] == before
    assert players["schema_version"] == 2
    assert players["effective_at"] == "2026-09-08T06:34:00+00:00"
    assert players["normalization_version"] == "V6_CANONICAL_FPL_1"
    assert players["primary_keys"] == ["official_fpl_element_id"]
    assert players["source_snapshot_ids"] == [f"official_fpl:bootstrap:{DIGEST}"]
    assert players["provenance_migration"]["row_data_changed"] is False


def test_migration_is_idempotent_and_does_not_rewrite_complete_artifacts(tmp_path: Path) -> None:
    _write(tmp_path, "current/official_fpl.json", _official())
    _legacy_canonical(tmp_path)
    first = migrate_legacy_canonical_provenance(tmp_path)
    bytes_after_first = (tmp_path / "normalized/canonical_players.json").read_bytes()
    second = migrate_legacy_canonical_provenance(tmp_path)

    assert first["valid"] is True
    assert second["valid"] is True
    assert second["mode"] == "NOT_REQUIRED"
    assert len(second["already_complete"]) == 3
    assert (tmp_path / "normalized/canonical_players.json").read_bytes() == bytes_after_first


def test_migration_fails_closed_on_count_mismatch(tmp_path: Path) -> None:
    _write(tmp_path, "current/official_fpl.json", _official())
    _legacy_canonical(tmp_path)
    players_path = tmp_path / "normalized/canonical_players.json"
    players = json.loads(players_path.read_text())
    players["player_count"] = 2
    players_path.write_text(json.dumps(players), encoding="utf-8")

    result = migrate_legacy_canonical_provenance(tmp_path)

    assert result["valid"] is False
    assert "legacy_provenance_migration:count_mismatch:normalized/canonical_players.json" in result["errors"]
    unchanged = json.loads(players_path.read_text())
    assert "source_snapshot_ids" not in unchanged


def test_migration_fails_closed_without_immutable_official_digest(tmp_path: Path) -> None:
    official = _official()
    official["attempts"] = []
    _write(tmp_path, "current/official_fpl.json", official)
    _legacy_canonical(tmp_path)

    result = migrate_legacy_canonical_provenance(tmp_path)

    assert result["valid"] is False
    assert "legacy_provenance_migration:official_fpl_immutable_snapshot_ids_missing" in result["errors"]


def test_catalog_refresh_applies_migration_before_fail_closed_validation(tmp_path: Path) -> None:
    _write(tmp_path, "current/official_fpl.json", _official())
    _legacy_canonical(tmp_path)

    catalog = refresh_artifact_catalog(tmp_path)
    report = validate_artifact_catalog(tmp_path)

    assert catalog["legacy_provenance_migration"]["valid"] is True
    assert len(catalog["legacy_provenance_migration"]["migrated"]) == 3
    assert catalog["completeness"]["status"] == "PASS"
    assert report["valid"] is True
    assert report["provenance_complete"] is True
    assert report["legacy_provenance_migration_valid"] is True
