from datetime import datetime, timedelta, timezone

from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.v4_checkpoint_governance import govern_checkpoint
from src.engines.v4_decision_arbitration import resolve_decision
from src.services.raw_snapshot_service import detect_phase


DEADLINE_0030_WIB = "2026-08-28T17:30:00Z"


def test_scheduled_checkpoints_are_registry_driven():
    cases = {
        "2026-08-26T04:30:00+07:00": "DEEP_REVIEW_0430",
        "2026-08-26T12:30:00+07:00": "MIDDAY_TACTICAL_1230",
        "2026-08-26T21:30:00+07:00": "NIGHT_TACTICAL_PRICE_2130",
    }
    for as_of, expected in cases.items():
        context = resolve_checkpoint("daily", "2026-09-12T10:00:00Z", as_of=as_of, simulated=True)
        assert context["policy_id"] == expected
        assert context["is_simulation"] is True
        assert context["visible_output_authorized"] is True
        assert context["report_scope"]


def test_non_visible_hourly_checkpoint_is_internal_only():
    context = resolve_checkpoint("daily", "2026-09-12T10:00:00Z", as_of="2026-08-26T10:30:00+07:00")
    assert context["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert context["visible_output_authorized"] is False
    assert context["is_master_hourly_checkpoint"] is True


def test_2130_is_final_review_for_early_morning_deadline():
    context = resolve_checkpoint("daily", DEADLINE_0030_WIB, as_of="2026-08-28T21:30:00+07:00", simulated=True)
    assert context["policy_id"] == "FINAL_DEADLINE_REVIEW"
    assert context["is_final_review"] is True
    assert context["minutes_to_deadline"] == 180
    assert context["max_snapshot_age_minutes"] == 15
    assert context["full_visible_report_required"] is True
    assert context["deadline_report_continues_after_final_review"] is True


def test_deadline_day_continues_after_final_review_and_overrides_match_mode():
    post_final = resolve_checkpoint("daily", DEADLINE_0030_WIB, is_live=True, as_of="2026-08-28T22:30:00+07:00")
    assert post_final["policy_id"] == "DEADLINE_MONITOR"
    assert post_final["post_final_emergency_only"] is False
    assert post_final["deadline_day_active"] is True
    assert post_final["visible_output_authorized"] is True
    assert post_final["no_material_change_must_still_report"] is True


def test_live_mode_requires_explicit_actual_live_state_outside_deadline_day():
    not_live = resolve_checkpoint("daily", "2026-09-12T10:00:00Z", is_live=False, as_of="2026-08-29T19:30:00+07:00")
    assert not_live["policy_id"] == "INTERNAL_HOURLY_SILENT"
    live = resolve_checkpoint("daily", "2026-09-12T10:00:00Z", is_live=True, as_of="2026-08-29T19:30:00+07:00")
    assert live["policy_id"] == "MATCHDAY_LIVE"
    assert live["recommended_refresh_minutes"] == 1
    assert live["visible_output_authorized"] is True


def test_post_deadline_reconciliation_has_top_transition_authority():
    context = resolve_checkpoint("daily", "2026-09-05T10:00:00Z", is_live=True, as_of="2026-08-29T00:31:00+07:00", post_deadline_reconciliation=True)
    assert context["policy_id"] == "POST_DEADLINE_RECONCILIATION"
    assert context["post_deadline_reconciliation"] is True
    assert context["visible_output_authorized"] is False


def test_detect_phase_requires_started_unfinished_fixture_for_match_mode():
    bootstrap = {
        "events": [
            {"id": 2, "is_current": True, "is_next": False, "finished": False, "deadline_time": "2026-08-28T17:30:00Z"},
            {"id": 3, "is_current": False, "is_next": True, "finished": False, "deadline_time": "2026-09-05T10:00:00Z"},
        ]
    }
    now = datetime(2026, 8, 29, 13, 30, tzinfo=timezone.utc)
    idle = detect_phase(bootstrap, [{"id": 20, "event": 2, "started": True, "finished": True}], now)
    assert idle["is_live_match"] is False
    assert idle["active_live_fixture_count"] == 0
    live = detect_phase(
        bootstrap,
        [
            {"id": 20, "event": 2, "started": True, "finished": True},
            {"id": 21, "event": 2, "started": True, "finished": False},
            {"id": 31, "event": 3, "started": True, "finished": False},
        ],
        now,
    )
    assert live["is_live_match"] is True
    assert live["active_live_fixture_count"] == 1
    assert live["active_live_fixture_ids"] == [21]


def _governance_inputs(simulated=False, age_minutes=0, health_overall="AMBER", material=False):
    now = datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc)
    generated = (now - timedelta(minutes=age_minutes)).isoformat()
    latest = {
        "generated_at": generated,
        "official_snapshot_at": generated,
        "squad_authority": "LOCKED_PRE_DEADLINE",
        "phase": {"planning_gw": 2, "is_live_match": False},
        "checkpoint_context": {
            "policy_id": "NIGHT_TACTICAL_PRICE_2130",
            "is_simulation": simulated,
            "is_final_review": False,
            "post_final_emergency_only": False,
            "max_snapshot_age_minutes": 60,
            "report_scope": ["locked_15", "lineup_watch"],
        },
    }
    health = {
        "overall": health_overall,
        "go_allowed": health_overall == "GREEN",
        "gate0": {"pass": True},
        "critical_partial": ["DSS-09"] if health_overall == "AMBER" else [],
        "critical_warmup": [],
    }
    sanity = {
        "final_verdict": "MATERIAL_UPGRADE" if material else "KEEP_15",
        "raw_package_verdict": "MATERIAL_UPGRADE" if material else "KEEP_15",
        "recommended_package": {
            "material_eligible": material,
            "evidence_confidence": .82 if material else 0,
            "replacements": 1 if material else 0,
            "out": [],
            "in": [],
        },
    }
    lineup = {
        "authority": "USER_OVERRIDE",
        "status": "MANUAL_DRAFT_ADJUSTABLE",
        "formation": "3-4-3",
        "formation_state": "DECIDED",
        "captain": {"name": "A"},
        "vice_captain": {"name": "B"},
        "chip_context": {"active_chip": "WILDCARD"},
        "gk_selection": {"status": "DECIDED"},
        "bench_governance": {"status": "DECIDED"},
        "captaincy_governance": {"status": "DECIDED"},
    }
    locked = {"wildcard_active": True, "target_gw": 2, "players": [{"element": n} for n in range(15)]}
    return now, latest, health, sanity, lineup, locked


def _canonical(now, latest, sanity, lineup, locked):
    return resolve_decision(
        sanity,
        lineup,
        latest,
        {"squad": locked["players"], "free_transfers": None},
        {"confirmed_changes": []},
        {"owned": [], "watchlist": []},
        now=now,
    )


def test_governance_never_authorizes_simulation_and_keeps_lineup_open():
    now, latest, health, sanity, lineup, locked = _governance_inputs(simulated=True)
    out = govern_checkpoint(latest, health, sanity, lineup, locked, now=now, canonical=_canonical(now, latest, sanity, lineup, locked))
    assert out["action_state"] == "HOLD"
    assert "SIMULATED_AS_OF" in out["execution_gate"]["blockers"]
    assert out["decision"]["execution_authorized"] is False
    assert out["squad"]["composition_status"] == "LOCKED_15"
    assert out["lineup"]["status"] == "ADJUSTABLE"
    assert out["decision"]["engine_is_advisory"] is True
    assert out["decision"]["user_decision_is_final_authority"] is True


def test_governance_stale_and_material_candidate_use_new_canonical_action_semantics():
    now, latest, health, sanity, lineup, locked = _governance_inputs(age_minutes=91)
    stale = govern_checkpoint(latest, health, sanity, lineup, locked, now=now, canonical=_canonical(now, latest, sanity, lineup, locked))
    assert stale["action_state"] == "HOLD"
    assert "SNAPSHOT_STALE" in stale["execution_gate"]["blockers"]

    now, latest, health, sanity, lineup, locked = _governance_inputs(health_overall="GREEN", material=True)
    review = govern_checkpoint(latest, health, sanity, lineup, locked, now=now, canonical=_canonical(now, latest, sanity, lineup, locked))
    assert review["action_state"] == "REVIEW"
    assert review["decision"]["candidate_state"] == "MATERIAL_UPGRADE_NON_ACTIONABLE"
    assert review["decision"]["execution_authorized"] is False

    lineup["status"] = "FINAL_LOCKED"
    final = govern_checkpoint(latest, health, sanity, lineup, locked, now=now, canonical=_canonical(now, latest, sanity, lineup, locked))
    assert final["action_state"] == "REVIEW"
    assert final["decision"]["execution_authorized"] is False
    assert final["lineup"]["status"] == "FINAL_LOCKED"


def test_governance_material_recommendation_during_critical_warmup_is_review_not_change():
    now, latest, health, sanity, lineup, locked = _governance_inputs(health_overall="GREEN", material=True)
    health.update({
        "prediction_health": "AMBER",
        "decision_engine": "PROVISIONAL",
        "go_allowed": False,
        "critical_warmup": ["DSS-44", "DSS-X12"],
    })
    out = govern_checkpoint(latest, health, sanity, lineup, locked, now=now, canonical=_canonical(now, latest, sanity, lineup, locked))
    assert out["action_state"] == "REVIEW"
    assert out["decision"]["execution_authorized"] is False
    assert out["readiness"]["critical_warmup"] == ["DSS-44", "DSS-X12"]
    assert "CRITICAL_PREDICTION_WARMUP" in out["execution_gate"]["blockers"]


def test_governance_uses_scorecard_target_gw_authority_not_stale_wc_flag():
    now, latest, health, sanity, lineup, locked = _governance_inputs(health_overall="GREEN")
    latest["squad_authority"] = "OFFICIAL_SUBMITTED"
    latest["phase"]["planning_gw"] = 3
    lineup["chip_context"] = {"active_chip": "NONE"}
    scorecard = {
        "planning_gw": {
            "status": "PROJECTION",
            "gw": 3,
            "active_chip": "NONE",
            "squad_basis": {
                "planning_gw": 3,
                "baseline_gw": 2,
                "override_applied": False,
                "override_target_gw": 2,
                "effective_authority": "OFFICIAL_SUBMITTED",
                "authority_source": "OFFICIAL_FPL_PICKS",
            },
        }
    }
    canonical = _canonical(now, latest, sanity, lineup, locked)
    out = govern_checkpoint(latest, health, sanity, lineup, locked, scorecard=scorecard, now=now, canonical=canonical)
    assert out["squad"]["authority_ok"] is True
    assert out["squad"]["expected_authority"] == "OFFICIAL_SUBMITTED"
    assert out["squad"]["baseline_gw"] == 2
    assert out["squad"]["wildcard_active"] is False
    assert out["squad"]["composition_status"] == "SUBMITTED_OR_CURRENT"
    assert "SQUAD_AUTHORITY_MISMATCH" not in out["execution_gate"]["blockers"]
