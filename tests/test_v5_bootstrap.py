from src.models.projection import project_points
from src.rules import GOAL_POINTS, RULESET_ID
from src.v5.acceptance import run_bootstrap_acceptance
from src.v5.contracts import Confidence, DecisionTrace, EvidenceRef


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
