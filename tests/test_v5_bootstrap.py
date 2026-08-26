from datetime import datetime, timezone

import pytest

from src.models.projection import project_points
from src.rules import GOAL_POINTS, RULESET_ID
from src.v5.acceptance import run_bootstrap_acceptance
from src.v5.contracts import Confidence, DecisionTrace, EvidenceRef
from src.v5.finance import affordability_cost, resolve_sell_value, sell_cost
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
