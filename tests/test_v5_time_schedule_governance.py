from src.v5.reporting import build_report
from src.v5.schedule_governance import resolve_schedule
from src.v5.services.truth import _match_state


def _context(deadline: str, *, phase: str = "PRE_DEADLINE", scoring_gw: int | None = 2) -> dict:
    return {
        "deadline_time": deadline,
        "phase": phase,
        "scoring_gw": scoring_gw,
        "is_live_event": phase == "LIVE",
    }


def test_normal_hourly_evaluation_is_silent_except_governed_times():
    deadline = "2026-09-05T11:30:00Z"
    silent = resolve_schedule(_context(deadline), now="2026-09-04T10:30:00+07:00")
    assert silent["hourly_checkpoint"] is True
    assert silent["active_mode"] == "INTERNAL_ONLY"
    assert silent["visible_authorized"] is False

    deep = resolve_schedule(_context(deadline), now="2026-09-04T04:30:00+07:00")
    assert deep["active_mode"] == "NORMAL_DEEP_REVIEW"
    assert deep["visible_authorized"] is True
    assert deep["force_full_report"] is True
    assert deep["report_payload"] == "data/deep_review_payload.json"
    assert deep["price_radar_required"] is True


def test_deadline_day_emits_full_every_30_and_final_review_does_not_terminate_it():
    deadline = "2026-08-28T17:30:00Z"  # 00:30 WIB
    before_final = resolve_schedule(_context(deadline), now="2026-08-28T20:30:00+07:00")
    assert before_final["active_mode"] == "DEADLINE_DAY"
    assert before_final["force_full_report"] is True

    final = resolve_schedule(_context(deadline), now="2026-08-28T21:30:00+07:00")
    assert final["active_mode"] == "DEADLINE_DAY_FINAL_REVIEW"
    assert final["final_review_due"] is True

    after_final = resolve_schedule(_context(deadline), now="2026-08-28T22:30:00+07:00")
    assert after_final["active_mode"] == "DEADLINE_DAY"
    assert after_final["visible_authorized"] is True
    assert after_final["force_full_report"] is True


def test_evening_deadline_final_review_can_fire_off_half_hour_checkpoint():
    deadline = "2026-08-29T11:30:00Z"  # 18:30 WIB
    final = resolve_schedule(_context(deadline), now="2026-08-29T17:00:00+07:00")
    assert final["hourly_checkpoint"] is False
    assert final["final_review_due"] is True
    assert final["active_mode"] == "DEADLINE_DAY_FINAL_REVIEW"
    assert final["visible_authorized"] is True


def test_deadline_boundary_emits_once_then_transitions_to_reconciliation():
    deadline = "2026-08-28T17:30:00Z"
    boundary = resolve_schedule(_context(deadline), now="2026-08-29T00:30:00+07:00")
    assert boundary["deadline_boundary"] is True
    assert boundary["active_mode"] == "DEADLINE_DAY"
    assert boundary["transition_after_emit"] == "POST_DEADLINE_RECONCILIATION"

    post = resolve_schedule(
        _context(deadline, phase="POST_DEADLINE"),
        now="2026-08-29T00:31:00+07:00",
        official_deadline_time=deadline,
    )
    assert post["deadline_day_active"] is False
    assert post["post_deadline_reconciliation_required"] is True


def test_collision_priority_merges_lower_modes_without_duplicate_report():
    deadline = "2026-08-28T17:30:00Z"
    collision = resolve_schedule(
        _context(deadline, phase="LIVE"),
        now="2026-08-28T21:30:00+07:00",
        live_match_active=True,
    )
    assert collision["active_mode"] == "DEADLINE_DAY_FINAL_REVIEW"
    assert "MATCH_MODE" in collision["merged_lower_priority_modes"]
    assert "NORMAL_NIGHT_TACTICAL_PRICE" in collision["merged_lower_priority_modes"]


def test_match_mode_requires_official_current_gw_match_actively_live():
    context = _context("2026-09-05T11:30:00Z", phase="LIVE", scoring_gw=2)
    no_match = resolve_schedule(context, now="2026-08-29T19:30:00+07:00", live_match_active=False)
    assert no_match["active_mode"] == "INTERNAL_ONLY"

    live = resolve_schedule(context, now="2026-08-29T19:30:00+07:00", live_match_active=True)
    assert live["active_mode"] == "MATCH_MODE"
    assert live["visible_authorized"] is True


def test_official_fixture_match_state_only_counts_started_unfinished_current_gw():
    fixtures = [
        {"id": 1, "event": 2, "started": True, "finished": False, "team_h": 1, "team_a": 2},
        {"id": 2, "event": 2, "started": True, "finished": True, "team_h": 3, "team_a": 4},
        {"id": 3, "event": 3, "started": True, "finished": False, "team_h": 5, "team_a": 6},
    ]
    state = _match_state(fixtures, 2)
    assert state["authority"] == "OFFICIAL_FPL_FIXTURES"
    assert state["live_match_active"] is True
    assert state["live_fixture_count"] == 1
    assert state["live_fixtures"][0]["id"] == 1


def test_deadline_source_sweep_is_fresh_and_never_fabricates_missing_sources():
    deadline = "2026-08-28T17:30:00Z"
    source_label = "FPL Live / LiveFPL"
    schedule = resolve_schedule(
        _context(deadline),
        now="2026-08-28T22:30:00+07:00",
        source_observations={source_label: {"status": "AVAILABLE"}},
    )
    assert schedule["fresh_source_sweep_required"] is True
    assert schedule["source_statuses"][source_label] == "AVAILABLE"
    assert schedule["source_statuses"]["Official FPL website"] == "UNAVAILABLE"


def test_deadline_direct_official_refresh_rules():
    deadline = "2026-08-28T17:30:00Z"
    stale = resolve_schedule(
        _context(deadline),
        now="2026-08-28T22:30:00+07:00",
        runtime_age_minutes=31,
    )
    assert stale["direct_official_refresh_required"] is True
    assert "RUNTIME_BRIDGE_OLDER_THAN_30_MINUTES" in stale["direct_official_refresh_reasons"]
    assert stale["direct_official_native_fact_authority"] == "DIRECT_OFFICIAL_FPL"

    material = resolve_schedule(
        _context(deadline),
        now="2026-08-28T22:30:00+07:00",
        runtime_age_minutes=5,
        material_native_state_may_have_changed=True,
    )
    assert material["direct_official_refresh_required"] is True
    assert "MATERIAL_NATIVE_STATE_MAY_HAVE_CHANGED" in material["direct_official_refresh_reasons"]


def _minimal_report_payload(schedule: dict, previous_state: dict) -> dict:
    return {
        "truth": {"team": {"authority": "user_lock", "owned_ids": list(range(1, 16))}},
        "decision": {
            "selected_package_id": "HOLD",
            "selected_package": {},
            "decision_trace": {"confidence": "HIGH"},
            "lineup": {
                "formation": "3-5-2",
                "starters": [{"element": x} for x in range(1, 12)],
                "bench": [{"element": x} for x in range(12, 16)],
                "captain": {"element": 1, "start_probability": 0.95, "expected_minutes": 88, "dnp_probability": 0.02},
                "vice_captain": {"element": 2},
                "captain_safe_pool": [
                    {"element": 1, "captain_score": 8.0},
                    {"element": 2, "captain_score": 7.0},
                ],
                "chip_context": {"active_chip": None},
                "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0},
            },
            "dss": {},
        },
        "prediction": {},
        "price": {"alerts": {"alerts": []}},
        "governance": {"overall": "GREEN", "go_allowed": True},
        "watchlist": {"status": "READY", "candidate_count": 20, "positions": {}},
        "previous_report_state": previous_state,
        "schedule_decision": schedule,
    }


def test_deadline_unchanged_report_remains_full_and_carries_no_material_change_message():
    deadline = "2026-08-28T17:30:00Z"
    schedule = resolve_schedule(_context(deadline), now="2026-08-28T22:30:00+07:00")
    first = build_report(_minimal_report_payload(schedule, {}))
    second = build_report(_minimal_report_payload(schedule, first["report_state"]))
    assert second["user_report"]["report_mode"] == "FULL_DECISION"
    assert second["user_report"]["emission"]["state"] == "VISIBLE"
    assert second["user_report"]["checkpoint_message"] == "NO MATERIAL CHANGE SINCE PREVIOUS CHECKPOINT"


def test_non_visible_checkpoint_is_marked_silent_without_suppressing_internal_artifact():
    schedule = resolve_schedule(
        _context("2026-09-05T11:30:00Z"),
        now="2026-09-04T10:30:00+07:00",
    )
    report = build_report(_minimal_report_payload(schedule, {}))
    assert report["user_report"]["emission"]["state"] == "SILENT"
    assert report["user_report"]["emission"]["mode"] == "INTERNAL_ONLY"
