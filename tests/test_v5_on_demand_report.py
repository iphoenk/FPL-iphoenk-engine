from __future__ import annotations

import json
from pathlib import Path

import src.v5.on_demand_report as on_demand
from src.v5.reporting import build_report


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_on_demand_packager_keeps_production_authority_and_full_lineup(tmp_path, monkeypatch):
    src = tmp_path / "source"
    out = tmp_path / "out"
    trigger = tmp_path / "trigger.json"
    _write(trigger, {"request_id": "req-1", "requested_at": "2026-08-27T02:00:00+00:00", "requested_by": "chat"})
    _write(src / "latest.json", {"engine_version": "3.17.1", "generated_at": "2026-08-27T02:00:05+00:00", "phase": {"phase": "PRE_DEADLINE", "planning_gw": 2}})
    _write(src / "user_report.json", {
        "decision": {"overall": "REVIEW", "squad": "HOLD", "starting_xi": "OPEN", "captaincy": "LEAN", "chip": "HOLD", "price": "HOLD", "confidence": "LOW"},
        "owned_squad": {"count": 15, "facts": [{"name": f"P{i}"} for i in range(15)]},
        "captaincy": {"confidence": "MEDIUM", "facts": {"model_candidate": "P1", "vice_candidate": "P2"}},
        "chip": {"facts": {"active_chip": "wildcard"}},
        "price_radar": {"owned": [{"name": "P3", "urgency": "HIGH"}]},
        "external_watchlist": {"status": "READY", "count": 20},
    })
    _write(src / "lineup_decision.json", {
        "formation": "3-4-3",
        "squad_authority": "pre_deadline_wc",
        "starting_xi": [{"name": f"XI{i}"} for i in range(11)],
        "bench": {
            "gk": {"name": "B0"},
            "order": [{"name": "B1"}, {"name": "B2"}, {"name": "B3"}],
        },
        "captain": {"name": "XI1"},
        "vice_captain": {"name": "XI2"},
    })
    _write(src / "decision_brief.json", {"status": "READY"})
    _write(src / "framework_health.json", {"overall": "GREEN", "go_allowed": True})
    _write(src / "dss_watchlist_summary.json", {"status": "READY", "count": 20})
    monkeypatch.setattr(on_demand, "load_json_config", lambda _: {
        "model_id": "on_demand_report_router_v1",
        "authority_strategy": "CURRENT_PRODUCTION_MAIN",
        "production_source_branch": "main",
        "freshness_target_minutes": 5,
    })

    payload = on_demand.build(str(src), str(out), str(trigger), "abc123")

    assert payload["authority"]["engine_track"] == "V3_PRODUCTION"
    assert payload["authority"]["production_authoritative"] is True
    assert payload["authority"]["v5_beta_overlay_used"] is False
    assert payload["quick_view"]["owned_count"] == 15
    assert len(payload["quick_view"]["starting_xi"]) == 11
    assert payload["quick_view"]["bench"] == ["B0", "B1", "B2", "B3"]
    assert payload["quick_view"]["captain"] == "XI1"
    assert payload["quick_view"]["watchlist_count"] == 20
    assert (out / "latest.json").exists()
    assert (out / "reports" / "req-1.json").exists()


def test_force_full_report_disables_compact_delta():
    squad = [{"element": i, "name": f"P{i}"} for i in range(1, 16)]
    starters = [{"element": i, "name": f"P{i}", "captain_score": 5 - i / 100, "start_probability": 0.9, "expected_minutes": 80, "dnp_probability": 0.05} for i in range(1, 12)]
    lineup = {
        "formation": "3-5-2",
        "starters": starters,
        "bench": squad[11:],
        "captain": starters[0],
        "vice_captain": starters[1],
        "captain_safe_pool": starters[:2],
        "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0},
    }
    current_state = {
        "squad": "HOLD",
        "starting_xi": list(range(1, 12)),
        "formation": "3-5-2",
        "captain": 1,
        "vice_captain": 2,
        "chip": None,
        "price": [],
        "critical_health": {"overall": "GREEN", "go_allowed": True},
    }
    report = build_report({
        "truth": {"team": {"authority": "user_lock", "squad": squad, "owned_ids": list(range(1, 16))}},
        "decision": {"selected_package_id": "HOLD", "decision_trace": {"confidence": "HIGH"}, "lineup": lineup},
        "prediction": {},
        "price": {"alerts": {"alerts": []}},
        "governance": {"overall": "GREEN", "go_allowed": True},
        "watchlist": {"status": "READY", "candidate_count": 20, "positions": {}},
        "previous_report_state": {"state": current_state},
        "force_full_report": True,
        "report_request": {"type": "ON_DEMAND"},
    })

    user = report["user_report"]
    assert user["report_mode"] == "FULL_DECISION"
    assert len(user["starting_xi"]["starting_xi"]) == 11
    assert user["request_context"]["type"] == "ON_DEMAND"
