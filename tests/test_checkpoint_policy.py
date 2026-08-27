from datetime import datetime, timedelta, timezone

from src.engines.checkpoint_policy import resolve_checkpoint
from src.engines.v4_checkpoint_governance import govern_checkpoint


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
        assert context["report_scope"]


def test_2130_is_final_review_for_early_morning_deadline():
    context = resolve_checkpoint(
        "deadline",
        DEADLINE_0030_WIB,
        as_of="2026-08-28T21:30:00+07:00",
        simulated=True,
    )
    assert context["policy_id"] == "FINAL_DEADLINE_REVIEW"
    assert context["is_final_review"] is True
    assert context["minutes_to_deadline"] == 180
    assert context["max_snapshot_age_minutes"] == 15


def test_post_final_and_live_take_precedence():
    post_final = resolve_checkpoint(
        "deadline",
        DEADLINE_0030_WIB,
        as_of="2026-08-28T22:00:00+07:00",
    )
    assert post_final["policy_id"] == "POST_FINAL_EMERGENCY_ONLY"
    assert post_final["post_final_emergency_only"] is True

    live = resolve_checkpoint(
        "live",
        DEADLINE_0030_WIB,
        is_live=True,
        as_of="2026-08-28T21:30:00+07:00",
    )
    assert live["policy_id"] == "MATCHDAY_LIVE"
    assert live["recommended_refresh_minutes"] == 1


def _governance_inputs(simulated=False, age_minutes=0, health_overall="AMBER", material=False):
    now = datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc)
    latest = {
        "generated_at": (now - timedelta(minutes=age_minutes)).isoformat(),
        "squad_authority": "LOCKED_PRE_DEADLINE",
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
    }
    sanity = {
        "final_verdict": "MATERIAL_UPGRADE" if material else "KEEP_15",
        "raw_package_verdict": "MATERIAL_UPGRADE" if material else "KEEP_15",
        "recommended_package": {
            "material_eligible": material,
            "replacements": 1 if material else 0,
            "out": [],
            "in": [],
        },
    }
    lineup = {"formation": "3-4-3", "captain": {"name": "A"}, "vice_captain": {"name": "B"}}
    locked = {"wildcard_active": True, "players": [{"element": n} for n in range(15)]}
    return now, latest, health, sanity, lineup, locked


def test_governance_never_authorizes_simulation_and_keeps_lineup_open():
    now, latest, health, sanity, lineup, locked = _governance_inputs(simulated=True)
    out = govern_checkpoint(latest, health, sanity, lineup, locked, now=now)
    assert out["action_state"] == "SIMULATION_ONLY"
    assert out["decision"]["execution_authorized"] is False
    assert out["squad"]["composition_status"] == "LOCKED_15"
    assert out["lineup"]["status"] == "ADJUSTABLE"


def test_governance_blocks_stale_and_only_goes_on_green_material_evidence():
    now, latest, health, sanity, lineup, locked = _governance_inputs(age_minutes=61)
    stale = govern_checkpoint(latest, health, sanity, lineup, locked, now=now)
    assert stale["action_state"] == "REFRESH_REQUIRED"

    now, latest, health, sanity, lineup, locked = _governance_inputs(health_overall="GREEN", material=True)
    go = govern_checkpoint(latest, health, sanity, lineup, locked, now=now)
    assert go["action_state"] == "GO"
    assert go["decision"]["execution_authorized"] is True


def test_governance_holds_material_recommendation_during_critical_warmup():
    now, latest, health, sanity, lineup, locked = _governance_inputs(health_overall="GREEN", material=True)
    health.update({
        "prediction_health": "AMBER",
        "decision_engine": "PROVISIONAL",
        "go_allowed": False,
        "critical_warmup": ["DSS-44", "DSS-X12"],
    })
    out = govern_checkpoint(latest, health, sanity, lineup, locked, now=now)
    assert out["action_state"] == "HOLD"
    assert out["decision"]["execution_authorized"] is False
    assert out["readiness"]["critical_warmup"] == ["DSS-44", "DSS-X12"]
    assert "CRITICAL_PREDICTION_WARMUP" in out["readiness"]["reasons"]
