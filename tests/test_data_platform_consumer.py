from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.consumer import assess_snapshot
from src.runtime_v6.publish_integrity import validate_publish_tree
from src.runtime_v6.registry import ZERO_AUTHORITY_KEYS


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
    authoritative_runtime_snapshot: bool | None = None,
    counts_as_completed_operational_slot: bool | None = None,
    master_orchestrated: bool = False,
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
        "master_orchestrated": master_orchestrated,
    }
    if authoritative_runtime_snapshot is not None:
        runtime_control["authoritative_runtime_snapshot"] = authoritative_runtime_snapshot
    if counts_as_completed_operational_slot is not None:
        runtime_control["counts_as_completed_operational_slot"] = counts_as_completed_operational_slot

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
            **{key: "NONE" for key in ZERO_AUTHORITY_KEYS},
            "production_ingestion_schedule_only": True,
        },
    }

    _write_json(root / "manifest.json", manifest)
    _write_json(root / "current" / "official_fpl.json", {"source_id": "official_fpl"})
    _write_json(root / "health" / "source_health.json", {})
    _write_json(root / "health" / "runtime_control.json", runtime_control)
    _write_json(root / "health" / "operational_slots.json", {"schema_version": 1, "slots": [], "summary": {"health": "AMBER", "maturity": "WARMING_UP"}})
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
    assert result["fallback_scope"] is None
    assert result["engine_artifact_fallback_allowed"] is False
    assert result["stored_tree_sha256"] == result["recomputed_tree_sha256"]
    assert result["governance"]["consumer_recomputes_publish_integrity"] is True
    assert result["governance"]["consumer_requires_exact_resolved_registry"] is True
    assert result["governance"]["consumer_requires_authoritative_operational_provenance"] is True
    assert result["governance"]["consumer_accepts_natural_and_master_orchestrated_authority"] is True
    assert result["governance"]["natural_scheduler_evidence_is_checked_separately"] is True
    assert result["governance"]["consumer_requires_full_zero_authority_contract"] is True
    assert result["governance"]["fallback_must_not_read_other_engine_artifacts"] is True


def test_master_orchestrated_snapshot_is_authoritative_without_natural_schedule_flag(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-04T10:40:00+00:00",
        scheduled_cycle=False,
        event_name="issue_comment",
        schedule_kind="master_orchestrated",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=True,
        master_orchestrated=True,
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["runtime_schedule_kind"] == "master_orchestrated"
    assert result["authoritative_runtime_snapshot"] is True
    assert result["failures"] == []


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
    assert result["fallback_scope"] == "EXTERNAL_SOURCES_ONLY"
    assert result["engine_artifact_fallback_allowed"] is False
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
    assert "INVALID_RUNTIME_SCHEDULE_KIND" in result["failures"]
    assert "NON_AUTHORITATIVE_RUNTIME_SNAPSHOT" in result["failures"]
    assert "NON_OPERATIONAL_RUNTIME_SNAPSHOT" in result["failures"]


def test_missing_runtime_snapshot_requires_direct_fallback(tmp_path: Path):
    result = assess_snapshot(tmp_path / "missing")

    assert result["state"] == "INVALID"
    assert result["direct_fallback_eligible"] is True
    assert result["fallback_scope"] == "EXTERNAL_SOURCES_ONLY"
    assert result["engine_artifact_fallback_allowed"] is False
    assert result["failures"] == ["MISSING_MANIFEST"]
