from __future__ import annotations

import pytest

from src.engines.decision_arbitration import arbitrate_decisions, assert_decision_consistency


def _user(*, chip: str | None = None, overall: str = "REVIEW", squad: str = "HOLD") -> dict:
    return {
        "decision": {"overall": overall, "squad": squad},
        "starting_xi": {"facts": {"formation": "3-4-3"}},
        "captaincy": {
            "model": {
                "captain": {"name": "Haaland"},
                "vice": {"name": "Bruno"},
            }
        },
        "chip": {"facts": {"active_chip": chip}},
    }


def _lineup(*, chip: str | None = None) -> dict:
    return {
        "formation": "3-4-3",
        "captain": {"name": "Haaland"},
        "vice_captain": {"name": "Bruno"},
        "chip_context": {"active_chip": chip},
    }


def _comparator(level: str = "REVIEW") -> dict:
    return {
        "top_comparisons": [
            {
                "actionability": {"level": level, "reason": "governed reason"},
                "reason": "governed reason",
            }
        ]
    }


def test_consistent_top_and_lower_decisions_pass():
    result = arbitrate_decisions(_user(), _lineup(), _comparator())
    assert result["status"] == "CONSISTENT"
    assert result["contradiction_count"] == 0
    assert_decision_consistency(result)


def test_stale_chip_mismatch_is_hard_inconsistency():
    result = arbitrate_decisions(_user(chip="wildcard"), _lineup(chip=None), _comparator())
    assert result["status"] == "INCONSISTENT"
    assert any(row["field"] == "active_chip" for row in result["contradictions"])
    with pytest.raises(RuntimeError, match="contradictory output"):
        assert_decision_consistency(result)


def test_actionable_change_cannot_hide_below_hold():
    result = arbitrate_decisions(_user(squad="HOLD"), _lineup(), _comparator("ACTIONABLE_CHANGE"))
    assert result["status"] == "INCONSISTENT"
    assert result["checks"]["no_actionable_change_hidden_under_hold"] is False


def test_explicit_review_divergence_preserves_visibility_instead_of_silent_consistency():
    result = arbitrate_decisions(
        _user(overall="REVIEW_DIVERGENCE", squad="HOLD"),
        _lineup(),
        _comparator("ACTIONABLE_CHANGE"),
    )
    assert result["status"] == "REVIEW_DIVERGENCE"
    assert result["explicit_review_divergence"] is True
    assert result["contradiction_count"] == 1


def test_lower_recommendation_requires_actionability_and_reason():
    result = arbitrate_decisions(_user(), _lineup(), {"top_comparisons": [{}]})
    assert result["status"] == "INCONSISTENT"
    assert result["checks"]["lower_recommendations_have_actionability_and_reason"] is False
