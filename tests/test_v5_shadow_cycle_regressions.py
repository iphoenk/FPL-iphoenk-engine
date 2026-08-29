from datetime import datetime, timezone

from src.v5.decision.watchlist import build_watchlist
from src.v5.evaluation.shadow_parity import compare
from src.v5.event_context import build_event_context


def test_between_finished_gw_and_next_deadline_is_pre_deadline():
    bootstrap = {
        "events": [
            {"id": 1, "is_current": True, "is_next": False, "finished": True, "deadline_time": "2026-08-21T17:30:00Z"},
            {"id": 2, "is_current": False, "is_next": True, "finished": False, "deadline_time": "2026-08-28T17:30:00Z"},
        ]
    }
    ctx = build_event_context(bootstrap, now=datetime(2026, 8, 26, 8, 30, tzinfo=timezone.utc))
    assert ctx.planning_gw == 2
    assert ctx.phase.value == "PRE_DEADLINE"


def test_live_scoring_gw_does_not_turn_next_planning_gw_into_live_decision_phase():
    bootstrap = {
        "events": [
            {"id": 2, "is_current": True, "is_next": False, "finished": False, "deadline_time": "2026-08-28T17:30:00Z"},
            {"id": 3, "is_current": False, "is_next": True, "finished": False, "deadline_time": "2026-09-04T17:30:00Z"},
        ]
    }
    ctx = build_event_context(bootstrap, now=datetime(2026, 8, 29, 2, 30, tzinfo=timezone.utc))
    assert ctx.current_gw == 2
    assert ctx.scoring_gw == 2
    assert ctx.planning_gw == 3
    assert ctx.is_live_event is True
    assert ctx.phase.value == "PRE_DEADLINE"


def test_shadow_parity_reads_native_v5_starters_and_fails_on_real_difference():
    v3 = {
        "starting_xi": [{"element": x} for x in range(1, 12)],
        "captain": {"element": 1},
        "ruleset_id": "FPL_2026_27",
        "squad_authority": "pre_deadline_wc",
    }
    v5 = {
        "decision_summary": {
            "lineup": {
                "starters": [{"element": x} for x in range(1, 10)] + [{"element": 20}, {"element": 21}],
                "captain": {"element": 1},
            }
        },
        "ruleset_id": "FPL_2026_27",
        "squad_authority": "user_lock",
        "framework_health": {"gate0": {"pass": True}},
    }
    result = compare(v3, v5)
    assert result["starting_xi_evidence_complete"] is True
    assert result["starting_xi_symmetric_difference"] == 4
    assert result["checks"]["starting_xi"] is False
    assert result["pass"] is False


def test_shadow_parity_uses_planning_decision_authority_not_live_scoring_authority():
    common_v3 = {
        "starting_xi": [{"element": x} for x in range(1, 12)],
        "captain": {"element": 1},
        "ruleset_id": "FPL_2026_27",
        "squad_authority": "OFFICIAL_SUBMITTED",
        "decision_squad_authority": "pre_deadline_wc",
    }
    common_lineup = {"starters": [{"element": x} for x in range(1, 12)], "captain": {"element": 1}}
    wrong = compare(common_v3, {
        "decision_summary": {"lineup": common_lineup},
        "ruleset_id": "FPL_2026_27",
        "squad_authority": "official_public",
        "decision_squad_authority": "official_public",
        "framework_health": {"gate0": {"pass": True}},
    })
    assert wrong["authority"] == {"v3": "pre_deadline_wc", "v5": "official_public"}
    assert wrong["checks"]["manual_lock"] is False
    assert wrong["pass"] is False

    aligned = compare(common_v3, {
        "decision_summary": {"lineup": common_lineup},
        "ruleset_id": "FPL_2026_27",
        "squad_authority": "user_lock",
        "decision_squad_authority": "user_lock",
        "framework_health": {"gate0": {"pass": True}},
    })
    assert aligned["checks"]["manual_lock"] is True
    assert aligned["pass"] is True


def test_watchlist_contract_returns_five_per_position_and_excludes_owned():
    positions = ["GK", "DEF", "MID", "FWD"]
    players = []
    eid = 100
    for pos in positions:
        for idx in range(7):
            players.append({
                "element": eid,
                "name": f"{pos}-{idx}",
                "position": pos,
                "team_id": (idx % 5) + 1,
                "status": "a",
                "now_cost": 45 + idx,
                "xpts_5": 15 + idx,
                "xpts_15": 45 + idx,
                "projection_confidence": "MEDIUM",
                "xmins": {
                    "start_probability": 0.7,
                    "expected_minutes": 70,
                    "dnp_probability": 0.1,
                },
            })
            eid += 1
    owned_ids = {100, 107, 114, 121}
    team = {"squad": [{"element": x} for x in owned_ids]}
    result = build_watchlist({"players": players}, team, dss={})
    assert result["status"] == "READY"
    assert result["candidate_count"] == 20
    assert all(len(result["positions"][pos]) == 5 for pos in positions)
    returned = {row["element"] for pos in positions for row in result["positions"][pos]}
    assert not (returned & owned_ids)
