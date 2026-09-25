from __future__ import annotations

import json
from pathlib import Path

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_integrated_report_runner import _build_squad_staging
from src.engines.v12_report_orchestration import _price_freshness


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "v12_regression_36126675342_stage_a.json"
)


def _load_regression() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _section(section_id: str, content: dict, state: str = "COMPLETE") -> dict:
    return {
        "section_id": section_id,
        "state": state,
        "content": content,
    }


def test_regression_36126675342_old_false_pass_is_now_rejected() -> None:
    fixture = _load_regression()
    old = fixture["old_visible"]
    bound = fixture["bound_authority"]
    route = fixture["finance_degraded_route"]

    report = {
        "sections": [
            _section(
                "S06",
                {
                    "starting_xi": [1],
                    "formation": old["s06_selected_formation"],
                    "bench": {"gk": 2, "order": [3, 4, 5]},
                    "lineup_score": {
                        "xpts_mean": old["s06_projected_xi_score"],
                        "captain_multiplier_value": old[
                            "s06_captain_multiplier_value"
                        ],
                        "vice_fallback_value": old[
                            "s06_vice_fallback_value"
                        ],
                    },
                    "formation_comparison": [
                        {
                            "formation": old["s06_selected_formation"],
                            "selected": True,
                            "expected_fpl_points_with_captain_vice": old[
                                "s06_selected_captain_adjusted_xpts"
                            ],
                        }
                    ],
                },
            ),
            _section(
                "S10",
                {
                    "rows": [
                        {
                            "element_id": 1,
                            "evidence_timestamp": old[
                                "price_evidence_timestamp"
                            ],
                        }
                    ],
                    "predictor_freshness": "FRESH",
                },
            ),
            _section(
                "S14",
                {
                    "package_routes": [
                        {
                            "route": route["route"],
                            "bank_before": route["bank_before"],
                            "affordability": route["old_affordability"],
                            "transfer_cost": {
                                "hit": route["hit"],
                                "ft_usage": {
                                    "free_transfers": route["free_transfers"]
                                },
                                "bank_after": route["bank_after"],
                            },
                            "moves": {
                                "out": [
                                    {
                                        "element": 426,
                                        "sell_value": route[
                                            "out_sell_value"
                                        ],
                                    }
                                ],
                                "in": [{"element": 52, "price": 70}],
                            },
                        }
                    ],
                },
            ),
            _section(
                "S14B",
                {
                    "ft_saving_plan": old["s14b_ft_saving_plan"],
                    "order_of_transfers": old[
                        "s14b_order_of_transfers"
                    ],
                    "budget_dependency": {
                        "bank": bound["bank"],
                        "sell_value_status": bound[
                            "selling_value_status"
                        ],
                    },
                    "staging_rows": [
                        {
                            "planned_move": old[
                                "s14b_order_of_transfers"
                            ]
                        }
                    ],
                },
            ),
            _section(
                "S17",
                {
                    "source_health": {
                        "authenticated_personal_scope": old[
                            "s17_authenticated_personal_scope"
                        ],
                    },
                    "bound_authority": {
                        "personal_auth_state": bound[
                            "private_auth_state"
                        ],
                    },
                },
            ),
        ]
    }
    old_body = (
        "FORMATION: 5-4-1\n"
        "XI: element:1\n"
        "BENCH: element:2, element:3, element:4, element:5\n"
        "PROJECTED XI SCORE: 49.777897\n"
        "CAPTAIN AUTHORITY: old-visible-contract\n"
    )

    failures = validate_deep_decision_content_delivery(report, old_body)

    assert fixture["occurrence"]["old_human_facing_status"] == "PASS"
    assert "AUTH_STATE_CONTRADICTION=HEALTHY!=AUTH_EXPIRED" in failures
    assert "FT_INFERENCE_WITHOUT_AUTHORITY" in failures
    assert "S06_XI_BASE_XPTS_NOT_VISIBLE" in failures
    assert "S06_CAPTAIN_ADJUSTED_XPTS_NOT_VISIBLE" in failures
    assert "FOOTBALL_FRONTIER_STATUS_MISSING" in failures
    assert "EXECUTION_ECONOMICS_STATUS_MISSING" in failures
    assert (
        "ROUTE_EXECUTION_ECONOMICS_STATUS_MISSING=1:426->52"
        in failures
    )
    assert "PRICE_FRESHNESS_MISSING=S10:1" in failures


def test_s06_score_semantics_accept_exact_base_plus_captain_and_vice() -> None:
    fixture = _load_regression()
    old = fixture["old_visible"]
    report = {
        "sections": [
            _section(
                "S06",
                {
                    "starting_xi": [1],
                    "formation": old["s06_selected_formation"],
                    "bench": {"gk": 2, "order": [3, 4, 5]},
                    "lineup_score": {
                        "xpts_mean": old["s06_projected_xi_score"],
                        "captain_multiplier_value": old[
                            "s06_captain_multiplier_value"
                        ],
                        "vice_fallback_value": old[
                            "s06_vice_fallback_value"
                        ],
                    },
                    "formation_comparison": [
                        {
                            "formation": old["s06_selected_formation"],
                            "selected": True,
                            "expected_fpl_points_with_captain_vice": old[
                                "s06_selected_captain_adjusted_xpts"
                            ],
                        }
                    ],
                    "authoritative_binding": {
                        "status": "BOUND",
                        "producer": "P1.7",
                        "payload_fingerprint": "fixture",
                    },
                },
            )
        ]
    }
    body = (
        "FORMATION: 5-4-1\n"
        "XI: element:1\n"
        "BENCH: element:2, element:3, element:4, element:5\n"
        "XI_BASE_XPTS: 49.777897\n"
        "CAPTAIN_ADJUSTED_XPTS: 55.012527\n"
        "CAPTAIN AUTHORITY: P1.7\n"
    )
    failures = validate_deep_decision_content_delivery(report, body)
    assert not [
        failure
        for failure in failures
        if failure.startswith("S06_")
    ]


def test_price_freshness_uses_existing_900_second_governance_boundary() -> None:
    assert _price_freshness(
        "2026-09-25T10:00:00+00:00",
        as_of="2026-09-25T10:15:00+00:00",
    ) == {
        "source_age_seconds": 900,
        "freshness": "FRESH",
        "freshness_threshold_seconds": 900,
    }
    assert _price_freshness(
        "2026-09-25T10:00:00+00:00",
        as_of="2026-09-25T10:15:01+00:00",
    )["freshness"] == "STALE"


def test_squad_staging_never_claims_save_ft_when_ft_authority_unknown() -> None:
    staging = _build_squad_staging(
        planning_gw=6,
        action="WAIT",
        stage3_decision={
            "selected_route_id": "HOLD",
            "reason": "fixture",
        },
        stage3_visible={
            "package_routes": [
                {
                    "route": "HOLD",
                    "moves": {"out": [], "in": []},
                    "three_gw": 0.0,
                }
            ],
        },
        all15_rows=[
            {"element_id": 1, "player": "Player One"},
        ],
        lineup={"starting_xi": [1], "formation": "4-4-2"},
        finance={
            "bank": None,
            "bank_status": "UNAVAILABLE",
            "sell_value_status": "UNAVAILABLE",
            "free_transfers": None,
            "free_transfers_status": "NOT_SUPPORTED",
            "personal_resolution_status": "CURRENT_VALID",
            "personal_evidence_stale": False,
        },
    )

    assert staging["ft_saving_plan"] == "FT STATE UNAVAILABLE"
    assert staging["order_of_transfers"] == "NO TRANSFER NOW"
    assert staging["budget_dependency"]["ft_authoritative"] is False
    assert all(
        "SAVE FT" not in str(row["planned_move"]).upper()
        and "ROLL FT" not in str(row["planned_move"]).upper()
        for row in staging["staging_rows"]
    )
