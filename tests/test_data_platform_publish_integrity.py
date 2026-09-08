from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.publish_integrity import validate_publish_tree


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _good_tree(root: Path) -> None:
    source_ids = ["official_fpl", "official_price_predictor"]
    manifest = {
        "source_count": len(source_ids),
        "source_ids": source_ids,
        "paths": {
            "current_sources": "data/v6/current/",
            "health": "data/v6/health/source_health.json",
            "canonical_players": "data/v6/normalized/canonical_players.json",
            "canonical_teams": "data/v6/normalized/canonical_teams.json",
            "canonical_fixtures": "data/v6/normalized/canonical_fixtures.json",
            "lineage": "data/v6/evidence/lineage.json",
            "evidence_index": "data/v6/evidence/latest_index.json",
            "resolved_registry": "data/v6/evidence/resolved_registry.json",
            "player_identity_map": "data/v6/evidence/player_identity_map.json",
            "runtime_control": "data/v6/health/runtime_control.json",
            "operational_slots": "data/v6/health/operational_slots.json",
            "publish_integrity": "data/v6/health/publish_integrity.json",
        },
    }
    _write(root / "manifest.json", manifest)
    for source_id in source_ids:
        _write(root / "current" / f"{source_id}.json", {"source_id": source_id})
    _write(root / "health" / "source_health.json", {"overall": "GREEN"})
    _write(root / "health" / "runtime_control.json", {"health": "GREEN"})
    _write(root / "health" / "operational_slots.json", {"schema_version": 1, "slots": [], "summary": {"health": "AMBER", "maturity": "WARMING_UP"}})
    _write(root / "normalized" / "canonical_players.json", {"player_count": 0, "players": []})
    _write(root / "normalized" / "canonical_teams.json", {"team_count": 0, "teams": []})
    _write(root / "normalized" / "canonical_fixtures.json", {"fixture_count": 0, "fixtures": []})
    _write(root / "evidence" / "lineage.json", {"groups": {}})
    _write(root / "evidence" / "latest_index.json", {"sources": {}})
    _write(
        root / "evidence" / "resolved_registry.json",
        {"source_count": len(source_ids), "sources": [{"id": source_id} for source_id in source_ids]},
    )
    _write(
        root / "evidence" / "player_identity_map.json",
        {
            "canonical_player_count": 0,
            "governance": {"fuzzy_name_matching_allowed": False},
            "mappings": {},
            "entity_bridges": {
                "team": {"canonical_team_count": 0, "mappings": {}},
                "fixture": {"canonical_fixture_count": 0, "mappings": {}},
            },
        },
    )


def test_publish_integrity_passes_for_exact_runtime_tree(tmp_path: Path):
    _good_tree(tmp_path)

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "PASS"
    assert report["errors"] == []
    assert report["current_source_files_exact"] is True
    assert report["resolved_registry_exact"] is True
    assert report["identity_map_consistent"] is True
    assert set(report["identity_counts"]) == {"player", "team", "fixture"}
    assert all(row["consistent"] is True for row in report["identity_counts"].values())
    assert report["tree_sha256"]


def test_publish_integrity_fails_when_runtime_source_is_missing(tmp_path: Path):
    _good_tree(tmp_path)
    (tmp_path / "current" / "official_price_predictor.json").unlink()

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert any(error.startswith("current_sources_missing:") for error in report["errors"])


def test_publish_integrity_fails_on_unregistered_runtime_source_file(tmp_path: Path):
    _good_tree(tmp_path)
    _write(tmp_path / "current" / "rogue_source.json", {"source_id": "rogue_source"})

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert any(error.startswith("current_sources_extra:") for error in report["errors"])


def test_publish_integrity_fails_on_source_identity_mismatch(tmp_path: Path):
    _good_tree(tmp_path)
    _write(tmp_path / "current" / "official_fpl.json", {"source_id": "wrong"})

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "source_identity_mismatch:official_fpl" in report["errors"]


def test_publish_integrity_fails_when_required_artifact_is_missing(tmp_path: Path):
    _good_tree(tmp_path)
    (tmp_path / "evidence" / "resolved_registry.json").unlink()

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "required_artifact_missing:resolved_registry" in report["errors"]


def test_publish_integrity_fails_when_resolved_registry_ids_diverge(tmp_path: Path):
    _good_tree(tmp_path)
    _write(
        tmp_path / "evidence" / "resolved_registry.json",
        {
            "source_count": 2,
            "sources": [{"id": "official_fpl"}, {"id": "rogue_source"}],
        },
    )

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "resolved_registry_source_ids_mismatch" in report["errors"]
    assert report["resolved_registry_exact"] is False


def test_publish_integrity_fails_when_player_identity_count_diverges(tmp_path: Path):
    _good_tree(tmp_path)
    _write(root := tmp_path / "normalized" / "canonical_players.json", {"player_count": 2, "players": []})
    assert root.exists()

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "identity_map_canonical_player_count_mismatch" in report["errors"]
    assert report["identity_counts"]["player"]["consistent"] is False


def test_publish_integrity_fails_when_team_identity_count_diverges(tmp_path: Path):
    _good_tree(tmp_path)
    _write(tmp_path / "normalized" / "canonical_teams.json", {"team_count": 1, "teams": [{"official_fpl_team_id": 1}]})

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "identity_map_canonical_team_count_mismatch" in report["errors"]
    assert report["identity_counts"]["team"]["consistent"] is False


def test_publish_integrity_fails_when_fixture_identity_count_diverges(tmp_path: Path):
    _good_tree(tmp_path)
    _write(tmp_path / "normalized" / "canonical_fixtures.json", {"fixture_count": 1, "fixtures": [{"official_fpl_fixture_id": 1}]})

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "identity_map_canonical_fixture_count_mismatch" in report["errors"]
    assert report["identity_counts"]["fixture"]["consistent"] is False


def test_publish_integrity_fails_when_identity_mapping_cardinality_diverges(tmp_path: Path):
    _good_tree(tmp_path)
    _write(
        tmp_path / "evidence" / "player_identity_map.json",
        {
            "canonical_player_count": 1,
            "governance": {"fuzzy_name_matching_allowed": False},
            "mappings": {},
            "entity_bridges": {
                "team": {"canonical_team_count": 0, "mappings": {}},
                "fixture": {"canonical_fixture_count": 0, "mappings": {}},
            },
        },
    )
    _write(
        tmp_path / "normalized" / "canonical_players.json",
        {"player_count": 1, "players": [{"official_fpl_element_id": 1}]},
    )

    report = validate_publish_tree(tmp_path)

    assert report["status"] == "FAIL"
    assert "identity_map_player_mapping_count_mismatch" in report["errors"]
    assert report["identity_counts"]["player"]["mapping_consistent"] is False
