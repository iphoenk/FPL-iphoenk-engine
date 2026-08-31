import json
from datetime import datetime, timezone

from src.engines.collector_gate import normal_report_mode, should_collect
from src.engines.report_user_presentation import RAW_DECISION_TOKENS, build_user_presentation, resolve_report_checkpoint
from src.runtime_v3.execution_profile_resolver import resolve_execution_profile


def _policy():
    return {
        "scheduled_report_checkpoints": {
            "enabled": True,
            "timezone": "Asia/Jakarta",
            "grace_minutes": 60,
            "history_days": 14,
            "silent_missing_forbidden": True,
            "slots": [
                {"id": "DAILY_DEEP", "time": "04:30", "label": "Review pagi 04:30 WIB"},
                {"id": "MIDDAY_CATCHUP", "time": "12:30", "label": "Catch-up 12:30 WIB"},
                {"id": "EVENING_CHECK", "time": "21:30", "label": "Review malam 21:30 WIB"},
            ],
        }
    }


def _completed(slot_id: str, local_date: str):
    return {
        "slot_id": slot_id,
        "label": slot_id,
        "local_date": local_date,
        "scheduled_local": f"{local_date}T04:30:00+07:00",
        "generated_at_utc": f"{local_date}T00:00:00+00:00",
        "generated_local": f"{local_date}T04:30:00+07:00",
        "status": "COMPLETED",
        "timeliness": "ON_TIME_WINDOW",
    }


def test_midday_checkpoint_is_recorded_without_duplicate():
    state = {"checkpoint_history": [_completed("DAILY_DEEP", "2026-08-27")]}
    now = datetime(2026, 8, 27, 5, 30, tzinfo=timezone.utc)
    checkpoint, updated = resolve_report_checkpoint(now, state, _policy())
    assert checkpoint["current"]["id"] == "MIDDAY_CATCHUP"
    assert checkpoint["completeness"] == "OK"
    assert checkpoint["missed_due"] == []
    assert len([row for row in updated["checkpoint_history"] if row["slot_id"] == "MIDDAY_CATCHUP"]) == 1

    checkpoint2, updated2 = resolve_report_checkpoint(now, updated, _policy())
    assert checkpoint2["completeness"] == "OK"
    assert len([row for row in updated2["checkpoint_history"] if row["slot_id"] == "MIDDAY_CATCHUP"]) == 1


def test_missed_checkpoint_is_explicit_not_silent():
    state = {"checkpoint_history": [_completed("DAILY_DEEP", "2026-08-27")]}
    now = datetime(2026, 8, 27, 6, 45, tzinfo=timezone.utc)
    checkpoint, _ = resolve_report_checkpoint(now, state, _policy())
    assert checkpoint["completeness"] == "ATTENTION_REQUIRED"
    assert [row["id"] for row in checkpoint["missed_due"]] == ["MIDDAY_CATCHUP"]
    assert checkpoint["recovered_late"] == []
    assert checkpoint["silent_missing_forbidden"] is True


def test_missed_checkpoint_becomes_late_recovered_only_when_execution_confirms_recovery():
    state = {"checkpoint_history": [_completed("DAILY_DEEP", "2026-08-27")]}
    now = datetime(2026, 8, 27, 6, 45, tzinfo=timezone.utc)
    checkpoint, updated = resolve_report_checkpoint(
        now,
        state,
        _policy(),
        recovered_slot_ids={"MIDDAY_CATCHUP"},
    )
    assert checkpoint["completeness"] == "RECOVERED"
    assert checkpoint["missed_due"] == []
    assert [row["id"] for row in checkpoint["recovered_late"]] == ["MIDDAY_CATCHUP"]
    assert checkpoint["current"]["kind"] == "RECOVERED_CHECKPOINT"
    records = [row for row in updated["checkpoint_history"] if row["slot_id"] == "MIDDAY_CATCHUP"]
    assert len(records) == 1
    assert records[0]["status"] == "LATE_RECOVERED"
    assert records[0]["timeliness"] == "LATE_RECOVERED"

    checkpoint2, updated2 = resolve_report_checkpoint(now, updated, _policy())
    assert checkpoint2["missed_due"] == []
    assert checkpoint2["today"][1]["state"] == "LATE_RECOVERED"
    assert len([row for row in updated2["checkpoint_history"] if row["slot_id"] == "MIDDAY_CATCHUP"]) == 1


def test_registry_driven_resolver_upgrades_routine_run_to_deep_for_missed_daily_checkpoint():
    now = datetime(2026, 8, 31, 0, 53, tzinfo=timezone.utc)
    result = resolve_execution_profile(
        visible_mode="SILENT",
        deadline_intensive=False,
        match_window=False,
        post_deadline_reconciliation=False,
        now_utc=now,
        report_state={"checkpoint_history": []},
    )
    assert result["profile"] == "deep_stats"
    assert result["mode"] == "daily"
    assert result["extra"] == "--deep-stats"
    assert result["recovery_required"] is True
    assert result["recovery_checkpoint_ids"] == ["DAILY_DEEP"]
    assert result["recovery_mode"] == "NORMAL_DEEP_REVIEW"


def test_checkpoint_recovery_never_overrides_live_or_deadline_mode():
    now = datetime(2026, 8, 31, 0, 53, tzinfo=timezone.utc)
    live = resolve_execution_profile(
        visible_mode="MATCH_MODE",
        deadline_intensive=False,
        match_window=True,
        post_deadline_reconciliation=False,
        now_utc=now,
        report_state={"checkpoint_history": []},
    )
    assert live["profile"] == "live"
    assert live["mode"] == "live"
    assert live["recovery_required"] is False
    assert live["deferred_recovery"] is True

    deadline = resolve_execution_profile(
        visible_mode="DEADLINE_DAY",
        deadline_intensive=True,
        match_window=False,
        post_deadline_reconciliation=False,
        now_utc=now,
        report_state={"checkpoint_history": []},
    )
    assert deadline["profile"] == "fast_decision"
    assert deadline["mode"] == "deadline"
    assert deadline["recovery_required"] is False
    assert deadline["deferred_recovery"] is True


def test_natural_presentation_keeps_machine_states_out_of_human_surface():
    payload = {
        "decision": {
            "overall": "REVIEW",
            "squad": "HOLD",
            "starting_xi": "OPEN",
            "captaincy": "LEAN",
            "chip": "HOLD",
            "price": "HOLD",
        },
        "gameweek_context": {
            "historical": [{"gw": 1, "actual_points": 71, "chip": "BENCH_BOOST"}],
            "planning": {
                "gw": 2,
                "status": "PROJECTION",
                "formation": "3-5-2",
                "estimated_points": 51.11,
                "active_chip": "WILDCARD",
                "captain": {"name": "Haaland"},
                "vice_captain": {"name": "De Cuyper"},
                "user_override_active": False,
                "baseline": {
                    "override_applied": True,
                    "authority_source": "USER_LOCKED_SCREENSHOT_WC_DRAFT",
                },
            },
        },
    }
    checkpoint = {"current": {"label": "Review malam 21:30 WIB"}, "missed_due": [], "recovered_late": []}
    presentation = build_user_presentation(payload, checkpoint)
    text = json.dumps(presentation, ensure_ascii=False)
    assert presentation["language"] == "id-ID"
    assert "GW1 selesai dengan 71 poin" in presentation["summary"]
    assert "51.11 poin" in presentation["summary"]
    assert "Wildcard sedang aktif" in presentation["chip"]
    assert "Haaland" in presentation["captaincy"]
    assert all(token not in text for token in RAW_DECISION_TOKENS)


def test_normal_report_slots_are_selected_inside_master_hourly_checkpoint_without_duplicate_crons():
    workflow = open(".github/workflows/v3-runtime.yml", encoding="utf-8").read()
    assert 'cron: "30 * * * *"' in workflow
    assert 'cron: "30 5 * * *"' not in workflow
    assert 'cron: "30 14 * * *"' not in workflow
    assert "execution_profile_resolver" in workflow
    assert 'profile="fast_decision"' not in workflow
    assert "persist-credentials: false" in workflow

    checkpoints = (
        (datetime(2026, 8, 27, 5, 30, tzinfo=timezone.utc), "NORMAL_MIDDAY"),
        (datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc), "NORMAL_NIGHT"),
    )
    for now, expected_mode in checkpoints:
        collect, reason = should_collect("schedule", "30 * * * *", now, None, False)
        assert collect is True
        assert reason == "hourly_primary"
        assert normal_report_mode(now, hourly_checkpoint=True) == expected_mode
