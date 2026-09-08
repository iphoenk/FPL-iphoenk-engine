from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.consumer import assess_snapshot
from src.runtime_v6.publish_integrity import validate_publish_tree
from src.runtime_v6.registry import ZERO_AUTHORITY_KEYS
from src.runtime_v6.runtime_control import CHATGPT_SCHEDULER_AUTHORITY


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
    runtime_control_health: str = "GREEN",
    runtime_control_overrides: dict | None = None,
    control_failures: list[str] | None = None,
    operational_summary: dict | None = None,
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
        "operational_slots": "data/v6/health/operational_slots.json",
        "publish_integrity": "data/v6/health/publish_integrity.json",
    }
    runtime_control = {
        "health": runtime_control_health,
        "event_name": event_name,
        "schedule_kind": schedule_kind,
        "run_id": "12345",
        "scheduled_cycle": scheduled_cycle,
        "duplicate_scheduled_cycle": False,
        "out_of_order_scheduled_cycle": False,
        "master_orchestrated": master_orchestrated,
    }
    if authoritative_runtime_snapshot is not None:
        runtime_control["authoritative_runtime_snapshot"] = authoritative_runtime_snapshot
    if counts_as_completed_operational_slot is not None:
        runtime_control["counts_as_completed_operational_slot"] = counts_as_completed_operational_slot
    runtime_control.update(runtime_control_overrides or {})

    manifest = {
        "source_count": 1,
        "source_ids": ["official_fpl"],
        "generated_at": generated_at,
        "overall": overall,
        "critical_failures": [],
        "control_failures": list(control_failures or []),
        "runtime_control": runtime_control,
        "paths": paths,
        "governance": {
            "data_only": True,
            **{key: "NONE" for key in ZERO_AUTHORITY_KEYS},
            "production_ingestion_schedule_only": True,
        },
    }

    default_operational_summary = {
        "health": "GREEN",
        "maturity": "ESTABLISHED",
        "missing_operational_slots": 0,
        "consecutive_successful_slots": 6,
        "required_consecutive_successes": 6,
    }

    _write_json(root / "manifest.json", manifest)
    _write_json(root / "current" / "official_fpl.json", {"source_id": "official_fpl"})
    _write_json(root / "health" / "source_health.json", {})
    _write_json(root / "health" / "runtime_control.json", runtime_control)
    _write_json(
        root / "health" / "operational_slots.json",
        {
            "schema_version": 3,
            "slots": [],
            "summary": dict(operational_summary or default_operational_summary),
        },
    )
    _write_json(root / "normalized" / "canonical_players.json", {"player_count": 1})
    _write_json(root / "normalized" / "canonical_teams.json", {"team_count": 0, "teams": []})
    _write_json(root / "normalized" / "canonical_fixtures.json", {"fixture_count": 0, "fixtures": []})
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
            "mappings": {"1": {"official_fpl_element_id": 1}},
            "entity_bridges": {
                "team": {"canonical_team_count": 0, "mappings": {}},
                "fixture": {"canonical_fixture_count": 0, "mappings": {}},
            },
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
    assert result["scheduler_reliability_health"] == "GREEN"
    assert result["scheduler_reliability_maturity"] == "ESTABLISHED"
    assert result["scheduler_missing_operational_slots"] == 0
    assert result["scheduler_reliability_degraded"] is False
    assert result["governance"]["consumer_recomputes_publish_integrity"] is True
    assert result["governance"]["consumer_requires_exact_resolved_registry"] is True
    assert result["governance"]["consumer_requires_authoritative_operational_provenance"] is True
    assert result["governance"]["consumer_accepts_natural_and_master_orchestrated_authority"] is True
    assert result["governance"]["natural_scheduler_evidence_is_checked_separately"] is True
    assert result["governance"]["consumer_requires_full_zero_authority_contract"] is True
    assert result["governance"]["fallback_must_not_read_other_engine_artifacts"] is True
    assert result["governance"]["scheduler_reliability_comes_from_operational_ledger"] is True


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


def test_chatgpt_scheduler_snapshot_is_authoritative_runtime_data(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T04:09:00+00:00",
        event_name="issue_comment",
        schedule_kind="chatgpt_scheduler",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=True,
        runtime_control_overrides={
            "chatgpt_scheduler": True,
            "chatgpt_scheduler_proof": True,
            "logical_slot_source": "CHATGPT_COMMAND",
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 4, 15, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["runtime_schedule_kind"] == "chatgpt_scheduler"
    assert result["scheduler_reliability_health"] == "GREEN"
    assert result["scheduler_required_consecutive_successful_slots"] == 6
    assert result["scheduler_reliability_degraded"] is False
    assert result["failures"] == []
    assert result["governance"]["consumer_accepts_chatgpt_scheduler_authority"] is True


def test_chatgpt_scheduler_requires_explicit_proof_fields(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T04:09:00+00:00",
        event_name="issue_comment",
        schedule_kind="chatgpt_scheduler",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=True,
        runtime_control_overrides={
            "chatgpt_scheduler": True,
            "chatgpt_scheduler_proof": False,
            "logical_slot_source": "CHATGPT_COMMAND",
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 4, 15, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "INVALID_CHATGPT_SCHEDULER_PROVENANCE" in result["failures"]


def test_recovered_fresh_snapshot_remains_usable_when_scheduler_reliability_is_red(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T04:09:00+00:00",
        event_name="issue_comment",
        schedule_kind="chatgpt_scheduler",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=True,
        runtime_control_health="RED",
        runtime_control_overrides={
            "chatgpt_scheduler": True,
            "chatgpt_scheduler_proof": True,
            "logical_slot_source": "CHATGPT_COMMAND",
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
            "missed_cycle": True,
            "missed_cycle_count": 1,
        },
        control_failures=["MISSED_CHATGPT_SCHEDULER_SLOT"],
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 4, 15, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["runtime_control_health"] == "RED"
    assert result["scheduler_reliability_health"] == "GREEN"
    assert result["scheduler_reliability_degraded"] is True
    assert result["scheduler_reliability_warnings"] == ["MISSED_CHATGPT_SCHEDULER_SLOT"]
    assert result["failures"] == []
    assert result["governance"]["scheduler_reliability_is_observability_not_data_validity"] is True


def test_report_prefetch_does_not_hide_operational_scheduler_gap(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T06:33:00+00:00",
        scheduled_cycle=False,
        event_name="issue_comment",
        schedule_kind="report_prefetch",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=False,
        runtime_control_health="GREEN",
        runtime_control_overrides={
            "report_prefetch": True,
            "counts_as_completed_report_slot": True,
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
            "last_chatgpt_scheduler_cycle_at": "2026-09-08T06:00:00+00:00",
        },
        operational_summary={
            "health": "AMBER",
            "maturity": "WARMING_UP",
            "tracked_operational_slots": 4,
            "fulfilled_operational_slots": 3,
            "missing_operational_slots": 1,
            "consecutive_successful_slots": 1,
            "required_consecutive_successes": 6,
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 6, 36, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["runtime_control_health"] == "GREEN"
    assert result["runtime_schedule_kind"] == "report_prefetch"
    assert result["scheduler_reliability_health"] == "AMBER"
    assert result["scheduler_reliability_maturity"] == "WARMING_UP"
    assert result["scheduler_missing_operational_slots"] == 1
    assert result["scheduler_consecutive_successful_slots"] == 1
    assert result["scheduler_required_consecutive_successful_slots"] == 6
    assert result["scheduler_reliability_degraded"] is True
    assert result["scheduler_reliability_warnings"] == ["OPERATIONAL_LEDGER_MISSING_SLOTS"]
    assert result["failures"] == []
    assert result["governance"]["report_prefetch_cannot_hide_core_scheduler_reliability"] is True


def test_warming_up_ledger_is_visible_without_becoming_data_failure(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T06:33:00+00:00",
        operational_summary={
            "health": "AMBER",
            "maturity": "WARMING_UP",
            "missing_operational_slots": 0,
            "consecutive_successful_slots": 2,
            "required_consecutive_successes": 6,
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 6, 36, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["scheduler_reliability_health"] == "AMBER"
    assert result["scheduler_required_consecutive_successful_slots"] == 6
    assert result["scheduler_reliability_degraded"] is True
    assert result["scheduler_reliability_warnings"] == []
    assert result["failures"] == []


def test_unknown_control_failure_still_fails_closed(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-04T10:40:00+00:00",
        control_failures=["UNKNOWN_RUNTIME_CONTROL_FAILURE"],
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "CONTROL:UNKNOWN_RUNTIME_CONTROL_FAILURE" in result["failures"]


def test_duplicate_chatgpt_cycle_still_fails_closed(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T04:09:00+00:00",
        event_name="issue_comment",
        schedule_kind="chatgpt_scheduler",
        authoritative_runtime_snapshot=True,
        counts_as_completed_operational_slot=True,
        runtime_control_overrides={
            "chatgpt_scheduler": True,
            "chatgpt_scheduler_proof": True,
            "logical_slot_source": "CHATGPT_COMMAND",
            "scheduler_authority": CHATGPT_SCHEDULER_AUTHORITY,
            "duplicate_scheduled_cycle": True,
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 4, 15, tzinfo=timezone.utc))

    assert result["state"] == "INVALID"
    assert "DUPLICATE_SCHEDULED_CYCLE" in result["failures"]


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



def test_consumer_recomputes_stale_scheduler_proof_without_invalidating_fresh_data(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(
        root,
        "2026-09-08T12:40:00+00:00",
        operational_summary={
            "health": "GREEN",
            "maturity": "ESTABLISHED",
            "missing_operational_slots": 0,
            "consecutive_successful_slots": 6,
            "required_consecutive_successes": 6,
            "last_chatgpt_scheduler_proof_at": "2026-09-08T10:31:00+00:00",
        },
    )

    result = assess_snapshot(root, now=datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc))

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["scheduler_proof_freshness"] == "STALE"
    assert result["scheduler_proof_health"] == "RED"
    assert result["scheduler_proof_age_seconds"] == 8940.0
    assert "CHATGPT_SCHEDULER_PROOF_STALE" in result["scheduler_reliability_warnings"]
    assert result["scheduler_reliability_degraded"] is True
    assert result["failures"] == []
    assert result["governance"]["scheduler_proof_age_is_recomputed_at_consumer_read_time"] is True
