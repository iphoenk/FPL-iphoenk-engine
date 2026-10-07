from __future__ import annotations

from src.engines.v12_final_delivery_barrier import (
    _deep_semantic_population_failures,
)


def _report(*sections):
    return {"sections": list(sections)}


def _section(section_id, state="COMPLETE", content=None):
    return {
        "section_id": section_id,
        "state": state,
        "content": dict(content or {}),
    }


def test_s04_cannot_claim_complete_no_news_without_report_time_injury_evidence():
    report = _report(
        _section(
            "S04",
            content={
                "news_summary": "NO MATERIAL NEW EXTERNAL NEWS",
                "report_time_evidence_contract_bound": False,
                "injury_availability_evidence": {"state": "UNAVAILABLE"},
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert "S04_COMPLETE_WITHOUT_REPORT_TIME_INJURY_EVIDENCE" in failures
    assert "S04_NO_NEWS_WITHOUT_REPORT_TIME_EVIDENCE" in failures


def test_s15_cannot_be_complete_when_injury_intelligence_is_degraded():
    report = _report(
        _section(
            "S15",
            content={
                "evidence_quality": {
                    "injury / availability intelligence": {
                        "state": "DEGRADED",
                    }
                }
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert "S15_COMPLETE_MASKS_INJURY_EVIDENCE_DEGRADATION" in failures


def test_s17_cannot_be_complete_when_report_time_injury_source_is_unbound():
    report = _report(
        _section(
            "S17",
            content={
                "source_health": {
                    "report_time_injury_evidence": "UNAVAILABLE",
                },
                "injury_availability_evidence": {
                    "report_time_evidence_contract_bound": False,
                },
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert "S17_COMPLETE_MASKS_INJURY_SOURCE_DEGRADATION" in failures


def test_balanced_close_captain_cannot_be_locked():
    report = _report(
        _section(
            "S08",
            content={
                "football_frontier_classification": "CLOSE",
                "decision_state": "LOCK",
                "risk_posture": "BALANCED",
                "competitive_context": {
                    "tie_break_status": "PRESERVE_FOOTBALL_LEADER_BALANCED",
                },
                "captain_profiles": [],
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert "S08_BALANCED_CLOSE_CAPTAIN_FALSE_LOCK" in failures
    assert "S08_BALANCED_CLOSE_MEAN_LEADER_AUTO_PRESERVED" in failures


def test_gk_attacking_probability_must_be_position_irrelevant_not_visible():
    report = _report(
        _section(
            "S16",
            content={
                "rows": [
                    {
                        "element_id": 572,
                        "position": "GK",
                        "probabilities": {
                            "p_goal": 0.02,
                            "p_assist": 0.01,
                            "p_return": 0.03,
                            "p_haul": 0.11,
                            "p_blank": 0.41,
                        },
                        "probability_evidence": {
                            "event_probabilities_available": True,
                            "point_distribution_available": True,
                            "unsupported_fields": [],
                            "position_irrelevant_fields": [],
                            "binding_failures": [],
                        },
                    }
                ],
                "semantic_binding_failures": [],
                "genuine_probability_unavailable": [],
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert any(
        failure.startswith("S16_GK_ATTACKING_PROBABILITY_UNSUPPORTED=572")
        for failure in failures
    )


def test_gk_position_irrelevant_attack_fields_do_not_false_degrade_valid_pmf():
    report = _report(
        _section(
            "S16",
            content={
                "rows": [
                    {
                        "element_id": 572,
                        "position": "GK",
                        "probabilities": {
                            "p_goal": None,
                            "p_assist": None,
                            "p_return": None,
                            "p_haul": 0.11,
                            "p_blank": 0.41,
                        },
                        "probability_evidence": {
                            "event_probabilities_available": True,
                            "point_distribution_available": True,
                            "unsupported_fields": [
                                "p_goal",
                                "p_assist",
                                "p_return",
                            ],
                            "position_irrelevant_fields": [
                                "p_goal",
                                "p_assist",
                                "p_return",
                            ],
                            "binding_failures": [],
                        },
                    }
                ],
                "semantic_binding_failures": [],
                "genuine_probability_unavailable": [],
            },
        ),
    )
    failures = _deep_semantic_population_failures(report, "")
    assert not any("S16_GK_ATTACKING_PROBABILITY" in failure for failure in failures)
