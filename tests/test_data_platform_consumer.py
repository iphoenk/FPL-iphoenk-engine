from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.consumer import assess_snapshot
from src.runtime_v6.publish_integrity import validate_publish_tree


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_snapshot(
    root: Path,
    generated_at: str,
    *,
    overall: str = "GREEN",
    integrity: str = "PASS",
    scheduled_cycle: bool = True,
    event_name: str = "schedule",
    schedule_kind: str = "primary",
) -> None:
    paths = {
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
        "publish_integrity": "data/v6/health/publish_integrity.json",
    }
    runtime_control = {
        "health": "GREEN",
        "event_name": event_name,
        "schedule_kind": schedule_kind,
        "run_id": "12345",
        "scheduled_cycle": scheduled_cycle,
        "duplicate_scheduled_cycle": False,
    }
    manifest = {
        "source_count": 1,
        "source_ids": ["official_fpl"],
        "generated_at": generated_at,
        "overall": overall,
        "critical_failures": [],
        "control_failures": [],
        "runtime_control": runtime_control,
        "paths": paths,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "production_ingestion_schedule_only": True,
        },
    }

    _write_json(root / "manifest.json", manifest)
    _write_json(root / "current" / "official_fpl.json", {"source_id": "official_fpl"})
    _write_json(root / "health" / "source_health.json", {})
    _write_json(root / "health" / "runtime_control.json", runtime_control)
    _write_json(root / "normalized" / "canonical_players.json", {"player_count": 1})
    _write_json(root / "normalized" / "canonical_teams.json", {})
    _write_json(root / "normalized" / "canonical_fixtures.json", {})
    _write_json(root / "evidence" / "lineage.json", {})
    _write_json(root / "evidence" / "latest_index.json", {})
    _write_json(
        root / "evidence" / "resolved_registry.json",
        {"source_count": 1, "sources": [{"id": "official_fpl"}]},
    )
    _write_json(
        root / "evidence" / "player_identity_map.json",
        {
            "canonical_player_count": 1,
            "governance": {"fuzzy_name_matching_allowed": False},
        },
    )

    publish_integrity = validate_publish_tree(root)
    assert publish_integrity["status"] == "PASS"
    assert publish_integrity["resolved_registry_exact"] is True
    publish_integrity["status"] = integrity
    _write_json(root / "health" / "publish_integrity.json", publish_integrity)


def test_fresh_green_snapshot_is_usable(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:00:00+00:00")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["direct_fallback_eligible"] is False
    assert result["stored_tree_sha256"] == result["recomputed_tree_sha256"]
    assert result["governance"]["consumer_recomputes_publish_integrity"] is True
    assert result["governance"]["consumer_requires_exact_resolved_registry"] is True
    assert result["governance"]["consumer_requires_scheduled_runtime_provenance"] is True


def test_static_green_snapshot_becomes_stale_at_read_time(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T07:14:41+00:00")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["manifest_overall"] == "GREEN"
    assert result["state"] == "STALE"
    assert result["usable"] is False
    assert result["direct_fallback_eligible"] is True
    assert result["governance"]["consumer_does_not_trust_static_green_without_freshness"] is True


def test_publish_integrity_failure_is_invalid_even_when_fresh(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:40:00+00:00", integrity="FAIL")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
    )

    assert result["state"] == "INVALID"
    assert result["usable"] is False
    assert "PUBLISH_INTEGRITY_NOT_PASS" in result["failures"]


def test_tampered_tree_is_invalid_even_if_stored_integrity_still_says_pass(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:40:00+00:00")
    _write_json(root / "current" / "official_fpl.json", {"source_id": "official_fpl", "tampered": True})

    result = assess_snapshot(root, now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "PUBLISH_TREE_DIGEST_MISMATCH" in result["failures"]


def test_registry_identity_divergence_is_invalid_even_with_matching_source_count(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:40:00+00:00")
    _write_json(
        root / "evidence" / "resolved_registry.json",
        {"source_count": 1, "sources": [{"id": "rogue_source"}]},
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "RECOMPUTED_PUBLISH_INTEGRITY_NOT_PASS" in result["failures"]
    assert "RECOMPUTED_RESOLVED_REGISTRY_NOT_EXACT" in result["failures"]


def test_manual_or_non_scheduled_snapshot_is_invalid(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-04T10:40:00+00:00",
        scheduled_cycle=False,
        event_name="workflow_dispatch",
        schedule_kind="manual",
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "NON_SCHEDULED_RUNTIME_SNAPSHOT" in result["failures"]
    assert "INVALID_RUNTIME_EVENT_PROVENANCE" in result["failures"]
    assert "INVALID_RUNTIME_SCHEDULE_KIND" in result["failures"]


def test_missing_runtime_snapshot_requires_direct_fallback(tmp_path: Path):
    result = assess_snapshot(tmp_path / "missing")

    assert result["state"] == "INVALID"
    assert result["direct_fallback_eligible"] is True
    assert result["failures"] == ["MISSING_MANIFEST"]
