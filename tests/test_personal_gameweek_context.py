import json
from pathlib import Path

from src.engines.personal_gameweek_context import build_history_context, build_planning_context
from src.engines.team_state_service import projection_baseline_authority

ROOT = Path(__file__).resolve().parents[1]


def _team():
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {
        "projection_baseline": {
            "planning_gw": 2,
            "baseline_gw": 1,
            "default_rule": "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD",
            "effective_authority": "LOCKED_PRE_DEADLINE",
            "authority_source": "USER_LOCKED_SCREENSHOT_WC_DRAFT",
        },
        "team_value_ledger": [
            {"element": i + 1, "name": f"P{i+1}", "position": position}
            for i, position in enumerate(positions)
        ],
    }


def _projections():
    return {
        "planning_gw": 2,
        "players": [
            {"element": i, "name": f"P{i}", "position": position, "xpts_by_gw": [{"gw": 2, "mean": float(i)}]}
            for i, position in enumerate(["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3, start=1)
        ],
    }


def _lineup():
    xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    return {
        "planning_gw": 2,
        "formation": "3-4-3",
        "starting_xi": [{"element": i} for i in xi],
        "captain": {"element": 15, "name": "P15"},
        "vice_captain": {"element": 14, "name": "P14"},
        "bench": {"gk": {"element": 2}, "order": [{"element": 6}, {"element": 7}, {"element": 12}]},
        "chip_context": {"active_chip": "wildcard"},
    }


def test_targeted_wc_lock_applies_only_to_exact_planning_gw():
    lock = {"wildcard_active": True, "planning_override_active": True, "target_gw": 2, "authority_source": "SCREENSHOT"}
    active = projection_baseline_authority(lock, {"planning_gw": 2, "submitted_gw": 1})
    assert active["override_applied"] is True
    assert active["effective_authority"] == "LOCKED_PRE_DEADLINE"
    assert active["baseline_gw"] == 1

    stale = projection_baseline_authority(lock, {"planning_gw": 3, "submitted_gw": 2})
    assert stale["override_applied"] is False
    assert stale["stale_override_rejected"] is True
    assert stale["effective_authority"] == "OFFICIAL_SUBMITTED"

    post_deadline = projection_baseline_authority(lock, {"planning_gw": 2, "submitted_gw": 2})
    assert post_deadline["override_applied"] is False
    assert post_deadline["post_deadline_official_reclaims_authority"] is True


def test_active_planning_override_without_target_gw_fails_closed():
    try:
        projection_baseline_authority({"wildcard_active": True}, {"planning_gw": 2, "submitted_gw": 1})
    except RuntimeError as exc:
        assert "target_gw" in str(exc)
    else:
        raise AssertionError("active untargeted override must fail closed")


def test_planning_projection_uses_engine_by_default_and_labels_estimate():
    out = build_planning_context(_team(), _projections(), _lineup(), manual={"status": "INACTIVE", "gw": 2})
    assert out["status"] == "PROJECTION"
    assert out["decision_authority"] == "ENGINE_RECOMMENDATION"
    assert out["formation"] == "3-4-3"
    assert out["active_chip"] == "WILDCARD"
    assert out["estimated_points"] == out["xi_xpts"] + 15.0
    assert out["scoring_guardrails"]["estimate_not_actual"] is True
    assert out["baseline"]["baseline_gw"] == 1


def test_user_override_is_effective_but_engine_recommendation_remains_visible():
    manual = {
        "status": "ACTIVE",
        "gw": 2,
        "source": "USER_FEELING_OVERRIDE",
        "starting_xi": [1, 3, 4, 5, 6, 8, 9, 10, 11, 14, 15],
        "captain": 14,
        "vice_captain": 15,
        "bench_gk": 2,
        "bench_order": [7, 12, 13],
        "active_chip": "NONE",
    }
    out = build_planning_context(_team(), _projections(), _lineup(), manual=manual)
    assert out["decision_authority"] == "USER_OVERRIDE"
    assert out["user_override_active"] is True
    assert out["formation"] == "4-4-2"
    assert out["captain"]["name"] == "P14"
    assert out["engine_recommendation"]["formation"] == "3-4-3"
    assert out["comparison"]["engine_can_warn_but_not_overwrite_user"] is True


def test_finished_gw_history_keeps_actual_truth_separate_from_forecast():
    starting = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    order = starting + bench
    positions = {element: index + 1 for index, element in enumerate(order)}
    official_detail = {
        "historical_entry": {
            "gameweeks": {
                "1": {
                    "gw": 1,
                    "status": "PUBLIC_OFFICIAL_SUBMITTED_TEAM",
                    "history": {"points": 71, "event_transfers_cost": 0, "points_on_bench": 9, "overall_rank": 12345, "rank": 23456},
                    "submitted": {
                        "active_chip": "bboost",
                        "picks": [
                            {
                                "element": i,
                                "position": positions[i],
                                "multiplier": 1 if i in starting else 0,
                                "is_captain": i == 15,
                                "is_vice_captain": i == 14,
                            }
                            for i in range(1, 16)
                        ],
                    },
                }
            }
        }
    }
    element_types = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3
    snapshot = {
        "bootstrap": {
            "elements": [
                {"id": i, "web_name": f"P{i}", "element_type": element_types[i-1], "team": 1}
                for i in range(1, 16)
            ],
            "teams": [{"id": 1, "name": "Club"}],
        }
    }
    rows = build_history_context(official_detail, snapshot)
    assert rows[0]["gw"] == 1
    assert rows[0]["actual_points"] == 71
    assert rows[0]["chip"] == "BENCH_BOOST"
    assert rows[0]["formation"] == "3-4-3"
    assert rows[0]["captain"]["name"] == "P15"
    assert len(rows[0]["submitted_squad"]) == 15
    assert rows[0]["forecast_capture"] == "NOT_RECONSTRUCTED"


def test_report_materializer_declares_official_snapshot_as_input():
    registry = json.loads((ROOT / "config" / "v3_service_registry.json").read_text(encoding="utf-8"))
    report_inputs = ((registry.get("services") or {}).get("report_materializer") or {}).get("inputs") or []
    assert "official_snapshot.json" in report_inputs


def test_wc_screenshot_lock_is_scoped_to_gw2():
    lock = json.loads((ROOT / "config" / "locked_squad.json").read_text(encoding="utf-8"))
    assert lock.get("target_gw") == 2
    assert lock.get("authority_source") == "USER_LOCKED_SCREENSHOT_WC_DRAFT"
    assert lock.get("planning_override_active") is True
