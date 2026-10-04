from __future__ import annotations

from src.engines.v12_captain_frontier import decide_captain_vice
from src.engines.v12_final_delivery_barrier import _deep_semantic_population_failures
from src.engines.v12_integrated_report_runner import _stage3_math_proof
from src.engines.v12_report_orchestration import (
    WATCHLIST_POSITION_FORMULAE,
    build_actionable_price_radar,
    build_visible_mathematical_decision_stack,
    build_watchlist20,
)


def _captain_candidate(
    element: int,
    *,
    position: str,
    pmf: dict[str, float] | None,
    expected: float,
    p_blank: float | None,
    p_haul: float | None,
) -> dict:
    distribution = {
        "expected_points": expected,
        "quantiles": {"Q50": expected, "Q75": expected, "Q90": expected},
        "p_fpl_blank": p_blank,
        "p_haul_10_plus": p_haul,
        "status": "READY_COMPLETE_POSITION_SPECIFIC",
        "distribution_completeness": "COMPLETE_FOR_SUPPORTED_FACTUAL_EVENTS",
    }
    if pmf is not None:
        distribution["probabilities"] = pmf
    return {
        "element_id": element,
        "player": f"P{element}",
        "position": position,
        "expected_points": expected,
        "p_start": 0.95,
        "xmins": 85.0,
        "p_dnp": 0.02,
        "point_distribution": distribution,
    }


def test_captain_full_pmf_populates_blank_haul_and_allows_gk_clear_dominance() -> None:
    gk = _captain_candidate(
        1,
        position="GK",
        pmf={"12": 1.0},
        expected=12.0,
        p_blank=0.0,
        p_haul=1.0,
    )
    mid = _captain_candidate(
        2,
        position="MID",
        pmf={"2": 1.0},
        expected=2.0,
        p_blank=1.0,
        p_haul=0.0,
    )
    result = decide_captain_vice(
        [gk, mid],
        baseline_captain_id=2,
        baseline_vice_id=1,
    )
    assert result["classification"] == "CLEAR"
    assert result["captain"]["element_id"] == 1
    assert result["captain"]["position"] == "GK"
    assert result["captain"]["p_blank"] == 0.0
    assert result["captain"]["p_haul"] == 1.0
    assert result["captain"]["p_ge_10"] == 1.0
    assert result["captain"]["football_evidence_complete"] is True


def test_captain_uses_canonical_blank_and_haul_semantics_over_pmf_rederivation() -> None:
    candidate = _captain_candidate(
        1,
        position="MID",
        pmf={"0": 0.5, "10": 0.5},
        expected=5.0,
        p_blank=0.17,
        p_haul=0.73,
    )
    other = _captain_candidate(
        2,
        position="FWD",
        pmf={"1": 0.5, "9": 0.5},
        expected=5.0,
        p_blank=0.40,
        p_haul=0.10,
    )
    result = decide_captain_vice(
        [candidate, other],
        baseline_captain_id=1,
        baseline_vice_id=2,
    )
    profile = next(row for row in result["profiles"] if row["element_id"] == 1)
    assert profile["p_blank"] == 0.17
    assert profile["p_haul"] == 0.73
    assert profile["p_ge_10"] == 0.73


def test_captain_missing_pmf_remains_fragile_and_preserves_p17_baseline() -> None:
    baseline = _captain_candidate(
        1,
        position="MID",
        pmf=None,
        expected=6.0,
        p_blank=None,
        p_haul=None,
    )
    challenger = _captain_candidate(
        2,
        position="FWD",
        pmf={"10": 1.0},
        expected=10.0,
        p_blank=0.0,
        p_haul=1.0,
    )
    result = decide_captain_vice(
        [baseline, challenger],
        baseline_captain_id=1,
        baseline_vice_id=2,
    )
    assert result["classification"] == "FRAGILE"
    assert result["captain"]["element_id"] == 1
    assert result["captain"]["pmf_available"] is False
    assert result["captain"]["p_blank"] is None
    assert result["captain"]["p_haul"] is None


def _predictor_row(element: int) -> dict:
    return {
        "element_id": str(element),
        "web_name": f"P{element}",
        "now_cost": 50 + element,
        "price_change_percent": "72.5",
        "price_change_hourly_rate": 3.0,
        "price_change_projections": [
            {"offset": 0, "projected_percent": 72.5, "likelihood": 3},
            {"offset": 1, "projected_percent": 80.0, "likelihood": 3},
            {"offset": 2, "projected_percent": 90.0, "likelihood": 3},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }


def test_price_all15_binds_by_canonical_element_id_and_exposes_visible_contract() -> None:
    owned = [
        {"element_id": element, "name": f"P{element}", "current_price": 50 + element}
        for element in range(1, 16)
    ]
    artifact = {
        "health": "GREEN",
        "checked_at": "2026-10-04T14:29:00+00:00",
        "data": {"players": [_predictor_row(element) for element in range(1, 16)]},
    }
    result = build_actionable_price_radar(
        owned15=owned,
        predictor_artifact=artifact,
        report_timestamp="2026-10-04T21:30:00+07:00",
    )
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 15
    assert result["predictor_supported_count"] == 15
    assert result["predictor_complete_count"] == 15
    assert result["semantic_binding_failures"] == []
    assert all(row["predictor_binding_state"] == "BOUND" for row in result["rows"])
    assert all(row["direction"] == "RISE" for row in result["rows"])
    assert all(row["official_or_provider_progress"] == "72.5" for row in result["rows"])


def test_price_genuine_predictor_absence_stays_unavailable_and_degrades_truthfully() -> None:
    owned = [
        {"element_id": element, "name": f"P{element}", "current_price": 50 + element}
        for element in range(1, 16)
    ]
    result = build_actionable_price_radar(
        owned15=owned,
        predictor_artifact=None,
        report_timestamp="2026-10-04T21:30:00+07:00",
    )
    assert result["state"] == "DEGRADED"
    assert len(result["genuine_predictor_unavailable"]) == 15
    assert all(row["direction"] == "UNAVAILABLE" for row in result["rows"])
    assert all(
        row["official_or_provider_progress"] == "UNAVAILABLE"
        for row in result["rows"]
    )
    assert all(row["predictor_projected_percent"] == "UNAVAILABLE" for row in result["rows"])


def _watch_row(element: int, position: str, rank: int, *, admitted: bool = True) -> dict:
    features = {
        key: 1.0
        for key in WATCHLIST_POSITION_FORMULAE[position]["features"]
    }
    return {
        "element_id": element,
        "name": f"P{element}",
        "position": position,
        "eligible": True,
        "canonical_evaluation_complete": True,
        "canonical_rank": rank,
        "football_score": 80.0 - rank,
        "xmins": 80.0 if admitted else 50.0,
        "p_start": 0.90 if admitted else 0.50,
        "p_available": 0.95 if admitted else 0.60,
        "p_dnp": 0.05 if admitted else 0.40,
        "stage2_lineage": {"lineage_complete": True},
        "position_specific_evidence": features,
    }


def test_watchlist_adapter_binds_score_admission_evidence_without_recomputation() -> None:
    rows = []
    element = 1
    for position in ("GK", "DEF", "MID", "FWD"):
        for rank in range(1, 6):
            rows.append(
                _watch_row(
                    element,
                    position,
                    rank,
                    admitted=not (position == "FWD" and rank == 5),
                )
            )
            element += 1
    result = build_watchlist20(
        evaluated_universe=rows,
        owned_element_ids=[],
        universe_authority="FULL",
    )
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    assert result["position_counts"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
    assert result["semantic_binding_failures"] == []
    assert result["actionable_admission_consistent"] is True
    assert len(result["actionable_watchlist"]) == 19
    for row in result["rows"]:
        assert row["score"] == row["football_score"]
        assert row["admit"] is row["admission_gate"]["admitted"]
        assert row["evidence"] != "UNAVAILABLE"
        assert row["presentation_binding"]["recomputed_score"] is False
        assert row["presentation_binding"]["recomputed_admission"] is False


def test_stage3_math_proof_propagates_native_p13_event_and_point_distribution() -> None:
    event_probabilities = {
        "p_goal_return": 0.31,
        "p_assist_return": 0.24,
        "p_attacking_return": 0.48,
        "p_total_ga_ge_2": 0.11,
        "p_no_attacking_return": 0.52,
    }
    point_distribution = {
        "probabilities": {"2": 0.4, "6": 0.4, "10": 0.2},
        "p_fpl_blank": 0.40,
        "p_haul_10_plus": 0.20,
        "expected_points": 5.2,
        "variance": 8.4,
        "std": 2.9,
        "quantiles": {"Q10": 2, "Q50": 6, "Q90": 10},
        "tails": {"ge_10": 0.20},
    }
    projections = {
        "players": [
            {
                "element": 10,
                "xmins": {
                    "availability": 0.96,
                    "start_probability": 0.91,
                    "bench_probability": 0.05,
                    "cameo_probability": 0.03,
                    "late_cameo_probability": 0.01,
                    "dnp_probability": 0.04,
                    "xmins_distribution": {"START": 0.91, "ZERO_MINUTES": 0.04},
                },
                "posterior_rates": {"goal": {"posterior_rate90": 0.4}},
                "horizons": {
                    "1": {
                        "event_probabilities": event_probabilities,
                        "point_distribution": point_distribution,
                    },
                    "3": {"point_distribution": point_distribution},
                    "5": {"point_distribution": point_distribution},
                },
                "xpts_by_gw": [
                    {
                        "gw": 7,
                        "fixtures": [
                            {
                                "fixture": 7001,
                                "event_probabilities": event_probabilities,
                                "point_distribution": point_distribution,
                                "complete_player_distribution": {
                                    "P_available": 0.96,
                                    "P_start": 0.91,
                                    "P_cameo": 0.03,
                                    "P_DNP": 0.04,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    package_utility = {
        "routes": [
            {
                "route_id": "HOLD",
                "players_in": [],
                "football_route_utility": {"per_gw": [{"captain": 10}]},
            }
        ]
    }
    stage3_decision = {
        "selected_route_id": "HOLD",
        "routes": [{"route_id": "HOLD", "expected_regret": 0.3}],
    }
    proof = _stage3_math_proof(
        projections=projections,
        package_utility=package_utility,
        stage3_decision=stage3_decision,
        monte_carlo={"execution_state": "PASS", "actual_paths": 500000},
    )
    pp = proof["posterior_predictive"]
    assert pp["source_owner"] == "V12_PLAYER_EVENTS"
    assert pp["source_contract"] == "P1.3/P1.3B_POSTERIOR_PREDICTIVE"
    assert pp["event_probabilities"] == event_probabilities
    assert pp["point_distribution"] == point_distribution
    assert pp["recomputed"] is False
    stack = build_visible_mathematical_decision_stack(proof)
    assert stack["event_probabilities"]["p_goal"] == 0.31
    assert stack["event_probabilities"]["p_assist"] == 0.24
    assert stack["event_probabilities"]["p_return"] == 0.48
    assert stack["event_probabilities"]["p_haul"] == 0.20
    assert stack["event_probabilities"]["p_blank"] == 0.40


def _section(section_id: str, state: str, content: dict) -> dict:
    return {"section_id": section_id, "state": state, "content": content}


def test_semantic_gate_rejects_s10_cross_section_predictor_binding_loss() -> None:
    report = {
        "sections": [
            _section(
                "S10",
                "COMPLETE",
                {
                    "rows": [
                        {
                            "element_id": 42,
                            "predictor_binding_state": "BOUND",
                            "direction": "UNAVAILABLE",
                            "official_or_provider_progress": "UNAVAILABLE",
                        }
                    ],
                    "semantic_binding_failures": [],
                    "genuine_predictor_unavailable": [],
                },
            ),
            _section(
                "S12",
                "COMPLETE",
                {
                    "rows": [
                        {
                            "element_id": 42,
                            "projected_percent": 88.0,
                        }
                    ]
                },
            ),
        ]
    }
    failures = _deep_semantic_population_failures(report, "")
    assert "S10_AVAILABLE_PREDICTOR_DROPPED=42" in failures
    assert "S10_S12_S13_CROSS_SECTION_BINDING_LOSS=42" in failures


def test_semantic_gate_rejects_complete_watchlist_masking_required_binding_loss() -> None:
    report = {
        "sections": [
            _section(
                "S11",
                "COMPLETE",
                {
                    "rows": [
                        {
                            "element_id": 77,
                            "football_score": 72.5,
                            "score": "UNAVAILABLE",
                            "admission_gate": {
                                "admitted": True,
                                "checks": {"p_start_secure": True},
                            },
                            "admit": "UNAVAILABLE",
                            "evidence": "UNAVAILABLE",
                        }
                    ],
                    "actionable_watchlist": [{"element_id": 77}],
                    "semantic_binding_failures": [77],
                },
            )
        ]
    }
    failures = _deep_semantic_population_failures(report, "")
    assert "S11_PRESENTATION_BINDING_FAILURE=77" in failures
    assert "S11_AVAILABLE_SCORE_DROPPED=77" in failures
    assert "S11_ADMISSION_BINDING_LOSS=77" in failures
    assert "S11_EVIDENCE_BINDING_LOSS=77" in failures
    assert "S11_COMPLETE_MASKS_REQUIRED_UNAVAILABLE" in failures


def test_semantic_gate_allows_truthful_degraded_optional_or_genuine_unavailable() -> None:
    report = {
        "sections": [
            _section(
                "S10",
                "DEGRADED",
                {
                    "rows": [
                        {
                            "element_id": 42,
                            "predictor_binding_state": "UNAVAILABLE",
                            "direction": "UNAVAILABLE",
                            "official_or_provider_progress": "UNAVAILABLE",
                        }
                    ],
                    "semantic_binding_failures": [],
                    "genuine_predictor_unavailable": [
                        {"element_id": 42, "reason": "NO_PLAYER_PREDICTOR_EVIDENCE"}
                    ],
                },
            ),
            _section(
                "S16",
                "DEGRADED",
                {
                    "rows": [
                        {
                            "element_id": 42,
                            "probabilities": {
                                "p_goal": "UNAVAILABLE",
                                "p_assist": "UNAVAILABLE",
                                "p_return": "UNAVAILABLE",
                                "p_haul": "UNAVAILABLE",
                                "p_blank": "UNAVAILABLE",
                            },
                            "probability_evidence": {
                                "event_probabilities_available": False,
                                "point_distribution_available": False,
                                "binding_failures": [],
                                "unsupported_fields": [
                                    "p_goal", "p_assist", "p_return", "p_haul", "p_blank"
                                ],
                            },
                        }
                    ],
                    "semantic_binding_failures": [],
                    "genuine_probability_unavailable": [
                        {
                            "element_id": 42,
                            "fields": [
                                "p_goal", "p_assist", "p_return", "p_haul", "p_blank"
                            ],
                        }
                    ],
                },
            ),
        ]
    }
    assert _deep_semantic_population_failures(report, "") == []
