from __future__ import annotations

"""Regression tests for Stage-A semantic false-pass classes.

The production occurrence 36126675342 is the motivating fixture: CI/human-facing
PASS was structurally green while auth/FT/score/economics/price semantics could
contradict their bound authority. These tests intentionally construct those
inconsistencies and require the delivery barrier to fail closed.
"""

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery


def _section(sid: str, content: dict, state: str = "COMPLETE") -> dict:
    return {"section_id": sid, "state": state, "content": content}


def _failures(*sections: dict) -> list[str]:
    return validate_deep_decision_content_delivery({"sections": list(sections)}, "")


def test_regression_36126675342_auth_expired_cannot_render_healthy():
    failures = _failures(
        _section("S17", {
            "bound_authoritative_auth_state": "AUTH_EXPIRED",
            "personal_auth": "HEALTHY",
        })
    )
    assert "S17_AUTH_CONTRADICTION" in failures


def test_unknown_ft_cannot_emit_save_or_roll_ft():
    failures = _failures(
        _section("S14B", {
            "ft_state": "UNKNOWN",
            "planning_rows": [{"planned_move": "SAVE FT"}],
        })
    )
    assert "S14B_FT_CLAIM_WITHOUT_AUTHORITY" in failures


def test_finance_degraded_route_cannot_be_executable():
    failures = _failures(
        _section("S14", {
            "execution_economics_status": "DEGRADED",
            "package_routes": [
                {"route": "HOLD", "moves": {"out": [], "in": []}},
                {
                    "route": "R1",
                    "moves": {"out": [{"element": 1}], "in": [{"element": 2}]},
                    "executable": True,
                },
            ],
        })
    )
    assert "S14_EXECUTABLE_WITHOUT_FINANCE=R1" in failures


def test_ambiguous_xi_score_mismatch_fails_closed():
    failures = _failures(
        _section("S06", {
            "projected_xi_score": 49.78,
            "selected_formation_projection": 55.01,
        })
    )
    assert "S06_AMBIGUOUS_SCORE_SEMANTICS" in failures


def test_explicitly_distinct_xi_score_semantics_are_allowed():
    failures = _failures(
        _section("S06", {
            "projected_xi_score": 49.78,
            "selected_formation_projection": 55.01,
            "score_semantics": "XI_BASE_XPTS_VS_CAPTAIN_ADJUSTED_XPTS",
        })
    )
    assert "S06_AMBIGUOUS_SCORE_SEMANTICS" not in failures


def test_stale_price_row_cannot_be_marked_current():
    failures = _failures(
        _section("S10", {
            "rows": [{"element_id": 1, "freshness": "STALE", "current": True}],
        })
    )
    assert "S10_STALE_PRICE_MARKED_CURRENT=1" in failures


def test_rank20_requires_terminal_date_state():
    failures = _failures(
        _section("S12", {
            "rows": [{
                "element_id": 1,
                "direction": "RISE",
                "estimate_source": "predictor",
                "rank": 1,
            }],
        })
    )
    assert "S12_TERMINAL_DATE_STATE_MISSING=1" in failures
