from datetime import datetime

import pytest

from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.v4_checkpoint_governance import govern_checkpoint


def _govern(context: dict, now: str) -> dict:
    latest = {
        "generated_at": now,
        "squad_authority": "OFFICIAL_SUBMITTED",
        "checkpoint_context": context,
    }
    health = {
        "overall": "GREEN",
        "pipeline_health": "GREEN",
        "prediction_health": "GREEN",
        "decision_engine": "READY",
        "go_allowed": False,
        "gate0": {"pass": True},
        "critical_partial": [],
        "critical_warmup": [],
        "capability_coverage": {},
    }
    sanity = {"final_verdict": "KEEP_15", "raw_package_verdict": "KEEP_15"}
    lineup = {
        "status": "MANUAL_DRAFT_ADJUSTABLE",
        "formation": "3-5-2",
        "captain": {"name": "Captain"},
        "vice_captain": {"name": "Vice"},
        "chip_context": {"active_chip": "NONE"},
    }
    locked = {"wildcard_active": False, "players": [{"element": i} for i in range(15)]}
    return govern_checkpoint(latest, health, sanity, lineup, locked, now=now)


def test_silent_checkpoint_consumes_policy_as_zero_visible_reports():
    now = "2026-08-29T17:00:00+07:00"
    context = resolve_checkpoint(
        "daily",
        "2026-08-29T12:30:00Z",
        is_live=False,
        as_of=now,
    )
    out = _govern(context, now)
    assert context["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert out["emission"]["authorized"] is False
    assert out["emission"]["visible_report_count"] == 0
    assert out["emission"]["max_visible_reports"] == 1


def test_deadline_no_change_contract_forces_one_full_visible_report():
    now = "2026-08-29T16:30:00+07:00"
    context = resolve_checkpoint(
        "daily",
        "2026-08-29T11:30:00Z",
        is_live=False,
        as_of=now,
    )
    out = _govern(context, now)
    emission = out["emission"]
    assert context["policy_id"] == "DEADLINE_MONITOR"
    assert emission["authorized"] is True
    assert emission["visible_report_count"] == 1
    assert emission["full_report_required"] is True
    assert emission["must_report_when_no_material_change"] is True
    assert emission["suppression_allowed"] is False
    assert emission["fresh_source_sweep_required"] is True
    assert emission["price_radar_required"] is True


def test_night_live_collision_is_consumed_as_one_merged_report():
    now = "2026-08-29T21:30:00+07:00"
    context = resolve_checkpoint(
        "daily",
        "2026-09-05T10:00:00Z",
        is_live=True,
        as_of=now,
    )
    out = _govern(context, now)
    emission = out["emission"]
    assert context["policy_id"] == "MATCHDAY_LIVE"
    assert context["absorbed_policy_ids"] == ["NIGHT_TACTICAL_PRICE_2130"]
    assert emission["visible_report_count"] == 1
    assert emission["single_consolidated_report"] is True
    assert emission["absorbed_policy_ids"] == ["NIGHT_TACTICAL_PRICE_2130"]
    assert emission["collision_merged"] is True
    assert emission["report_scope"] == list(dict.fromkeys(context["report_scope"]))


def test_final_review_live_collision_still_emits_exactly_one_full_report():
    now = "2026-08-29T17:00:00+07:00"
    context = resolve_checkpoint(
        "daily",
        "2026-08-29T11:30:00Z",
        is_live=True,
        as_of=now,
    )
    out = _govern(context, now)
    emission = out["emission"]
    assert context["policy_id"] == "FINAL_DEADLINE_REVIEW"
    assert "MATCHDAY_LIVE" in context["absorbed_policy_ids"]
    assert emission["visible_report_count"] == 1
    assert emission["full_report_required"] is True
    assert emission["must_report_when_no_material_change"] is True


def test_legacy_post_final_emergency_flag_is_fail_closed_not_second_timing_authority():
    now = "2026-08-29T21:30:00+07:00"
    context = resolve_checkpoint(
        "daily",
        "2026-09-05T10:00:00Z",
        as_of=now,
    )
    context["post_final_emergency_only"] = True
    with pytest.raises(RuntimeError, match="sole timing authority"):
        _govern(context, now)
