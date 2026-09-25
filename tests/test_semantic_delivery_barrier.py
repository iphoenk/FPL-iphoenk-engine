from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as runner
from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_report_orchestration import (
    _render_deep_visible_contract_lines,
    build_price20,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "v12_run_36126675342_semantic_regression.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _report(*sections: dict) -> dict:
    return {"sections": list(sections)}


def _section(section_id: str, content: dict, state: str = "COMPLETE") -> dict:
    return {
        "section_id": section_id,
        "state": state,
        "content": content,
    }


def test_36126675342_auth_false_pass_is_rejected():
    evidence = _fixture()
    failures = validate_deep_decision_content_delivery(
        _report(
            _section(
                "S17",
                {
                    "source_health": {
                        "authenticated_personal_scope": evidence["s17"][
                            "prior_visible_authenticated_personal_scope"
                        ],
                    },
                    "bound_authoritative_health": {
                        "auth_state": evidence["s17"]["bound_auth_state"],
                        "personal_status": evidence["s17"][
                            "bound_personal_status"
                        ],
                    },
                },
            )
        ),
        "## 17. SOURCE HEALTH / FRESHNESS / LINEAGE",
    )
    assert (
        "S17_AUTH_CONTRADICTION=HEALTHY!=AUTH_EXPIRED"
        in failures
    )


def test_36126675342_unknown_ft_cannot_claim_save_or_roll():
    evidence = _fixture()
    failures = validate_deep_decision_content_delivery(
        _report(
            _section(
                "S14B",
                {
                    "ft_authority": {
                        "known": False,
                        "free_transfers": evidence["s14b"][
                            "free_transfers"
                        ],
                    },
                    "ft_saving_plan": evidence["s14b"][
                        "prior_ft_saving_plan"
                    ],
                    "order_of_transfers": evidence["s14b"][
                        "prior_planned_move"
                    ],
                    "staging_rows": [
                        {
                            "planned_move": evidence["s14b"][
                                "prior_planned_move"
                            ],
                        }
                    ],
                },
            )
        ),
        "## 14B. 3-GW SQUAD STAGING",
    )
    assert "FT_UNKNOWN_BUT_SAVE_OR_ROLL_CLAIMED" in failures


def test_stage_a_staging_uses_no_transfer_now_when_ft_unknown():
    staging = runner._three_gw_staging(
        planning_gw=6,
        action="WAIT",
        stage3_decision={
            "selected_route_id": "HOLD",
            "reason": "NO_POSITIVE_ROUTE",
        },
        stage3_visible={
            "package_routes": [
                {
                    "route": "HOLD",
                    "moves": {"out": [], "in": []},
                    "three_gw": 0.0,
                }
            ]
        },
        all15_rows=[],
        lineup={"formation": "5-4-1", "starting_xi": []},
        finance={
            "free_transfers": None,
            "free_transfers_authoritative": False,
            "free_transfers_status": "NOT_SUPPORTED",
            "bank": None,
            "bank_status": "UNAVAILABLE",
            "sell_value_status": "UNAVAILABLE",
        },
    )
    assert staging["ft_saving_plan"] == "FT STATE UNAVAILABLE"
    assert staging["order_of_transfers"] == "NO TRANSFER NOW"
    assert staging["ft_authority"]["known"] is False
    assert all(
        "SAVE FT" not in str(row.get("planned_move") or "").upper()
        and "ROLL FT" not in str(row.get("planned_move") or "").upper()
        for row in staging["staging_rows"]
    )


def test_36126675342_score_semantics_are_distinct_and_reconcile():
    evidence = _fixture()["s06"]
    lineup = {
        "formation": evidence["selected_formation"],
        "starting_xi": list(range(1, 12)),
        "bench": {"gk": 12, "order": [13, 14, 15]},
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "lineup_score": {
            "xpts_mean": evidence["xi_base_xpts"],
            "captain_multiplier_value": evidence[
                "captain_multiplier_value"
            ],
            "vice_fallback_value": evidence["vice_fallback_value"],
        },
        "formation_comparison": [
            {
                "formation": evidence["selected_formation"],
                "expected_fpl_points_with_captain_vice": evidence[
                    "selected_captain_adjusted_xpts"
                ],
                "route_utility": evidence[
                    "selected_lineup_route_utility"
                ],
                "selected": True,
            }
        ],
    }
    content = runner._lineup_content(lineup)
    semantics = content["score_semantics"]
    assert semantics["xi_base_xpts"] == pytest.approx(49.777897)
    assert semantics["captain_adjusted_xpts"] == pytest.approx(
        55.012527
    )
    assert semantics["lineup_route_utility"] == pytest.approx(
        54.817245
    )
    assert semantics["derived_captain_adjusted_xpts"] == pytest.approx(
        semantics["captain_adjusted_xpts"]
    )

    visible, _ = _render_deep_visible_contract_lines(
        section_id="S06",
        content=content,
        owned_ids=set(range(1, 16)),
        owned_names={index: f"P{index}" for index in range(1, 16)},
    )
    body = "\n".join(visible)
    assert "XI_BASE_XPTS: 49.777897" in body
    assert "CAPTAIN_ADJUSTED_XPTS: 55.012527" in body
    assert "LINEUP_ROUTE_UTILITY: 54.817245" in body
    assert "PROJECTED XI SCORE:" not in body


def test_s06_missing_semantic_split_cannot_false_pass():
    failures = validate_deep_decision_content_delivery(
        _report(
            _section(
                "S06",
                {
                    "formation": "5-4-1",
                    "starting_xi": list(range(1, 12)),
                    "bench": {"gk": 12, "order": [13, 14, 15]},
                    "lineup_score": {"xpts_mean": 49.777897},
                    "formation_comparison": [
                        {
                            "formation": "5-4-1",
                            "expected_fpl_points_with_captain_vice": 55.012527,
                            "route_utility": 54.817245,
                            "selected": True,
                        }
                    ],
                },
            )
        ),
        (
            "FORMATION: 5-4-1\n"
            "XI: P1\n"
            "BENCH: P12\n"
            "PROJECTED XI SCORE: 49.777897\n"
            "CAPTAIN AUTHORITY: P1"
        ),
    )
    assert "S06_SCORE_SEMANTICS_INCOMPLETE" in failures
    assert any(
        item.startswith("S06_SCORE_SEMANTICS_NOT_VISIBLE=")
        for item in failures
    )


def test_36126675342_unresolved_finance_route_is_not_executable():
    evidence = _fixture()["s14"]
    failures = validate_deep_decision_content_delivery(
        _report(
            _section(
                "S14",
                {
                    "football_frontier_status": "COMPLETE",
                    "execution_economics_status": "DEGRADED",
                    "package_routes": [
                        {
                            "route": evidence["sample_non_hold_route"],
                            "execution_economics_status": "DEGRADED",
                            "executable": True,
                            "action_verdict": "ACT",
                        }
                    ],
                    "frontier": [{}],
                },
            )
        ),
        "OUT → IN 1GW 2GW 3GW 5GW P>HOLD Q10 Q90 BANK BEFORE BANK AFTER BEST ALTERNATIVE",
    )
    assert (
        "S14_DEGRADED_ECONOMICS_MARKED_EXECUTABLE="
        + evidence["sample_non_hold_route"]
        in failures
    )
    assert (
        "S14_NONEXECUTABLE_ROUTE_MARKED_ACT="
        + evidence["sample_non_hold_route"]
        not in failures
    )


def test_stale_price_predictor_cannot_be_complete():
    evidence = _fixture()["price"]
    rows = [
        {
            "element_id": 1000 + index,
            "name": f"P{index}",
            "direction": "RISE",
            "rank": index,
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
        }
        for index in range(1, 21)
    ]
    result = build_price20(
        predictor_artifact={
            "health": "GREEN",
            "checked_at": evidence["predictor_checked_at"],
            "rows": rows,
        },
        direction="RISE",
        as_of=evidence["report_slot"],
    )
    assert result["freshness_state"] == "STALE"
    assert result["source_age_seconds"] > result[
        "freshness_threshold_seconds"
    ]
    assert result["state"] == "DEGRADED"
    assert "stale" in result["degradation_reason"].lower()
