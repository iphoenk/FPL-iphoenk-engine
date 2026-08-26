from datetime import datetime, timezone

import pytest

from src.models.projection import project_points
from src.rules import GOAL_POINTS, RULESET_ID
from src.v5.acceptance import run_bootstrap_acceptance
from src.v5.authenticated_official import safe_finance, summarize_authenticated_payloads
from src.v5.contracts import Confidence, DecisionTrace, EvidenceRef
from src.v5.finance import affordability_cost, resolve_sell_value, sell_cost
from src.v5.official_auth import AuthMaterial, AuthPolicyError, allowed_routes, expected_team_id, safe_get
from src.v5.price_trajectory import classify, risk_direction, trajectory_eta, urgency
from src.v5.source_authority import primary_authority as source_primary_authority
from src.v5.state import Phase, primary_authority as phase_primary_authority, resolve_phase


def test_v5_bootstrap_acceptance_passes():
    report = run_bootstrap_acceptance()
    assert report.passed, report.as_dict()


def test_v5_rules_registry_has_2026_27_goalkeeper_goal_points():
    assert RULESET_ID == "FPL_2026_27"
    assert GOAL_POINTS[1] == 10


def test_projection_consumes_goalkeeper_goal_rule():
    player = {"element_type": 1, "status": "a", "minutes": 90, "starts": 1, "saves": 0}
    advanced = {
        "start_probability": 1.0,
        "xg_per90": 1.0,
        "xa_per90": 0.0,
        "clean_sheet_probability": 0.0,
        "bonus_per90": 0.0,
    }
    result = project_points(player, advanced, fixture_difficulty=5.0)
    assert result["components"]["attack"] == 10.0
    assert result["ruleset_id"] == RULESET_ID


def test_decision_trace_requires_evidence_and_constraints():
    trace = DecisionTrace(
        decision_type="START",
        action="START element 1",
        subject_element_ids=(1,),
        score=5.2,
        confidence=Confidence.MEDIUM,
        reasons_for=("strong xMins",),
        reasons_against=(),
        evidence=(EvidenceRef(source="Official FPL", field="status", authority="native"),),
        constraints_checked=("legal_formation",),
        projection_model="interpretable_projection_v5_bootstrap",
        ruleset_id=RULESET_ID,
    )
    trace.validate()


def test_source_authority_prefers_user_lock_pre_deadline():
    assert source_primary_authority("pre_deadline_locked_squad").name == "user_lock"
    assert source_primary_authority("player_identity").name == "official_public"


def test_phase_authority_changes_across_gameweek_lifecycle():
    deadline = "2026-08-29T10:00:00Z"
    assert resolve_phase(deadline_time=deadline, now="2026-08-29T09:59:59Z") is Phase.PRE_DEADLINE
    assert resolve_phase(deadline_time=deadline, now="2026-08-29T10:00:01Z") is Phase.POST_DEADLINE
    assert resolve_phase(deadline_time=deadline, now="2026-08-29T10:00:01Z", live_started=True) is Phase.LIVE
    assert resolve_phase(deadline_time=deadline, now=datetime.now(timezone.utc), finished=True) is Phase.POST_GW
    assert phase_primary_authority(Phase.PRE_DEADLINE, "squad") == "user_lock"
    assert phase_primary_authority(Phase.POST_DEADLINE, "squad") == "official_public"
    assert phase_primary_authority(Phase.LIVE, "scoring") == "official_public_event_live"
    assert phase_primary_authority(Phase.POST_GW, "scoring") == "official_final_history"


def test_finance_uses_official_half_profit_rule():
    assert sell_cost(50, 45) == 47
    assert sell_cost(44, 45) == 44


def test_finance_prefers_authenticated_exact_sell_value():
    resolved = resolve_sell_value(
        element_id=1,
        now_cost=50,
        authenticated_selling_price=48,
        authenticated_purchase_price=45,
    )
    assert resolved.sell_cost == 48
    assert resolved.source == "authenticated_selling_price"
    assert resolved.exact is True


def test_finance_unknown_purchase_cost_fails_closed():
    resolved = resolve_sell_value(element_id=1, now_cost=50)
    assert resolved.sell_cost is None
    assert resolved.purchase_cost is None
    with pytest.raises(RuntimeError):
        affordability_cost(owned=True, now_cost=50, sell_value=None)


def test_authenticated_official_routes_are_registry_driven_and_allowlisted():
    team_id = expected_team_id()
    routes = allowed_routes()
    assert routes["my_team"] == f"my-team/{team_id}/"
    assert routes["transfers_latest"] == f"entry/{team_id}/transfers-latest/"
    with pytest.raises(AuthPolicyError):
        safe_get("arbitrary", AuthMaterial(mode="test", headers={}))


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


def test_price_trajectory_thresholds_are_registry_driven():
    meta = classify(net_transfers=30000, ownership_pct=5.0, estimated_owners=100000)
    assert meta["actionable"] is True
    assert meta["confidence"] == "HIGH"
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    eta, predicted = trajectory_eta(now, 90.0, 2.0)
    assert eta == 5.0
    assert predicted is not None
    assert risk_direction(-80.0, 1.0) == "FALL"
    assert urgency(95.0, None, now) == "CRITICAL"
