from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from src.v5 import public_api
from src.v5.acceptance import run_bootstrap_acceptance
from src.v5.authenticated_official import safe_finance, summarize_authenticated_payloads
from src.v5.finance import build_squad_ledger, sell_cost
from src.v5.official_auth import AuthConfigurationError, auth_material_from_env, expected_team_id
from src.v5.price_trajectory import classify, risk_direction, trajectory_eta, urgency
from src.v5.public_api import FetchSpec


def test_bootstrap_acceptance_passes():
    report = run_bootstrap_acceptance()
    assert report.passed, report.as_dict()


def test_sell_cost_half_profit_floor():
    assert sell_cost(50, 50) == 50
    assert sell_cost(49, 50) == 49
    assert sell_cost(51, 50) == 50
    assert sell_cost(52, 50) == 51
    assert sell_cost(53, 50) == 51


def test_finance_ledger_reconstructs_transfer_spells():
    squad = [{"element": 1}, {"element": 2}]
    result = build_squad_ledger(
        squad,
        now_costs={1: 50, 2: 55},
        transfers=[
            {"event": 2, "time": "2026-08-20T10:00:00Z", "element_in": 1, "element_in_cost": 48, "element_out": 9},
        ],
        initial_purchase_costs={2: 52},
    )
    by_id = {row["element"]: row for row in result["players"]}
    assert by_id[1]["purchase_cost"] == 48
    assert by_id[1]["sell_cost"] == 49
    assert by_id[2]["purchase_cost"] == 52
    assert by_id[2]["sell_cost"] == 53
    assert result["sell_value_complete"] is True


def test_auth_material_rejects_partial_bearer_pair(monkeypatch):
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "token")
    monkeypatch.delenv("FPL_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("FPL_SESSION_B64", raising=False)
    with pytest.raises(AuthConfigurationError):
        auth_material_from_env()


def test_auth_material_rejects_mixed_session_and_bearer(monkeypatch):
    monkeypatch.setenv("FPL_SESSION_B64", base64.b64encode(b"sessionid=test-session").decode("ascii"))
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "token")
    monkeypatch.delenv("FPL_REFRESH_TOKEN", raising=False)
    with pytest.raises(AuthConfigurationError):
        auth_material_from_env()


def test_authenticated_finance_extracts_only_authoritative_squad():
    team_id = expected_team_id()
    my_team = {
        "picks": [
            {"element": 1, "purchase_price": 45, "selling_price": 47},
            {"element": 2, "purchase_price": 50, "selling_price": 50},
            {"element": 999, "purchase_price": 100, "selling_price": 100},
        ],
        "transfers": {"bank": 5, "value": 1000, "made": 0, "cost": 0},
    }
    finance = safe_finance(my_team, {1, 2})
    assert finance["coverage"]["complete"] is True
    assert finance["exact_sell_total"] == 97
    summary = summarize_authenticated_payloads(
        me={"player": {"entry": team_id}},
        my_team=my_team,
        transfers_latest=[],
        authoritative_elements={1, 2},
    )
    assert summary["state"] == "VALID"
    assert summary["raw_authenticated_payload_persisted"] is False


def test_price_trajectory_thresholds_are_registry_driven_without_false_crossing_eta():
    meta = classify(net_transfers=30000, ownership_pct=5.0, estimated_owners=100000)
    assert meta["actionable"] is True
    assert meta["confidence"] == "HIGH"
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    eta, predicted = trajectory_eta(now, 90.0, 2.0)
    assert eta is None
    assert predicted is None
    assert risk_direction(-80.0, 1.0) == "FALL"
    assert urgency(95.0, None, now) == "CRITICAL"


def test_parallel_public_api_deduplicates_identical_paths(monkeypatch):
    calls = []

    def fake_get_path(path):
        calls.append(path)
        return {"path": path}, {"status": "LIVE", "path": path}

    monkeypatch.setattr(public_api, "_get_path", fake_get_path)
    payloads, health = public_api.fetch_many(
        {
            "bootstrap_a": FetchSpec(route="bootstrap", params={}),
            "bootstrap_b": FetchSpec(route="bootstrap", params={}),
        }
    )
    assert calls == ["bootstrap-static/"]
    assert payloads["bootstrap_a"] == payloads["bootstrap_b"]
    assert health["bootstrap_a"]["deduplicated"] is True
    assert health["bootstrap_b"]["deduplicated"] is True


def _fake_squad_inputs():
    element_types = [1, 1] + [2] * 5 + [3] * 5 + [4] * 4
    elements = []
    teams = []
    for team_id in range(1, 9):
        teams.append({"id": team_id, "name": f"Team {team_id}"})
    for eid, element_type in enumerate(element_types, start=1):
        team_id = ((eid - 1) % 8) + 1
        elements.append(
            {
                "id": eid,
                "web_name": f"P{eid}",
                "first_name": f"First{eid}",
                "second_name": f"Last{eid}",
                "team": team_id,
                "element_type": element_type,
                "now_cost": 45 + eid,
                "selected_by_percent": "1.0",
                "transfers_in": 0,
                "transfers_in_event": 0,
                "transfers_out": 0,
                "transfers_out_event": 0,
                "status": "a",
            }
        )
    return {
        "elements": elements,
        "teams": teams,
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "events": [
            {
                "id": 1,
                "is_current": True,
                "is_next": False,
                "finished": False,
                "deadline_time": "2026-08-15T10:00:00Z",
            },
            {
                "id": 2,
                "is_current": False,
                "is_next": True,
                "finished": False,
                "deadline_time": "2026-08-22T10:00:00Z",
            },
        ],
    }


def test_public_entry_and_submitted_picks_remain_usable_without_auth():
    from src.v5.event_context import build_event_context
    from src.v5.identity import build_index
    from src.v5.team_service import build_team_state

    bootstrap = _fake_squad_inputs()
    identity = build_index(bootstrap)
    context = build_event_context(bootstrap, now=datetime(2026, 8, 16, tzinfo=timezone.utc))
    submitted = {
        "picks": [
            {"element": eid, "position": eid, "multiplier": 1 if eid <= 11 else 0, "is_captain": eid == 1, "is_vice_captain": eid == 2}
            for eid in range(1, 16)
        ],
        "entry_history": {"bank": 5, "value": 1000},
        "active_chip": None,
    }
    team = build_team_state(
        phase=context.phase,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=None,
        authenticated_my_team=None,
        submitted_picks=submitted,
        transfers=[],
        entry={"last_deadline_bank": 5},
        planning_gw=context.planning_gw,
        submitted_gw=context.submitted_gw,
    )
    assert len(team["owned_ids"]) == 15
    assert team["governance"]["authenticated_official_production_blocking"] is False


def test_no_auth_does_not_block_bootstrap_acceptance(monkeypatch):
    monkeypatch.delenv("FPL_SESSION_B64", raising=False)
    monkeypatch.delenv("FPL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("FPL_REFRESH_TOKEN", raising=False)
    report = run_bootstrap_acceptance()
    assert report.passed
