from __future__ import annotations

from copy import deepcopy

from src.engines.tactical_decision_consumption import (
    apply_lineup_overlay,
    apply_watchlist_overlay,
    compact_tactical,
    decorate_report_payload,
    tactical_key,
)


def _tactical(*, ready: bool = False, overlap: bool = False, confidence: str = "LOW") -> dict:
    vulnerabilities = ["box_pressure"] if overlap else ["wide_delivery"]
    routes = ["box_pressure"] if overlap else ["shot_volume"]
    return {
        "status": "READY" if ready else "PARTIAL",
        "evidence_confidence": confidence,
        "opponent_team_id": 99,
        "opponent_observed_style_proxies": ["chance_creation"],
        "opponent_strengths": ["chance_creation"],
        "opponent_vulnerabilities": vulnerabilities,
        "player_role": "ATTACKING_PROFILE",
        "player_return_routes": routes,
        "highlights": ["rute pemain bertemu area lawan yang baru tertekan: tekanan di kotak"] if overlap else [],
        "opponent_coach": None,
        "opponent_shape": "4-5-1",
        "opponent_shape_evidence": "OBSERVED_FPL_POSITION_SHAPE",
        "xpts_mutated": False,
    }


def _projection(element: int, *, edge: bool = False, captain_edge: bool = False) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "tactical_matchup": _tactical(ready=edge or captain_edge, overlap=edge or captain_edge, confidence="MEDIUM"),
        "xpts_by_gw": [{"gw": 2, "mean": 5.0, "std": 2.0, "fixtures": [{"opponent": 99}]}],
    }


def _squad_row(element: int, position: str, *, captain_score: float = 5.0) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "selection_score": 4.0,
        "captain_score": captain_score,
        "bench_score": 4.0,
        "start_probability": 0.90,
        "dnp_probability": 0.02,
    }


def test_tactical_key_is_neutral_without_ready_positive_matchup():
    partial = {"tactical_matchup": _tactical(ready=False, overlap=True)}
    ready_no_overlap = {"tactical_matchup": _tactical(ready=True, overlap=False)}
    ready_overlap = {"tactical_matchup": _tactical(ready=True, overlap=True, confidence="HIGH")}
    assert tactical_key(partial) == (0, 0, 0)
    assert tactical_key(ready_no_overlap) == (0, 0, 0)
    assert tactical_key(ready_overlap) > (0, 0, 0)
    compact = compact_tactical(ready_overlap)
    assert compact["evidence_state"] == "CUKUP"
    assert compact["route_vulnerability_overlap"] == ["box_pressure"]


def test_lineup_and_captain_close_calls_use_tactical_without_mutating_projection_xpts():
    positions = {
        1: "GK", 15: "GK",
        2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF",
        7: "MID", 8: "MID", 9: "MID", 10: "MID", 11: "MID",
        12: "FWD", 13: "FWD", 14: "FWD",
    }
    squad = [_squad_row(e, positions[e], captain_score=(10.0 if e == 12 else 9.8 if e == 13 else 5.0)) for e in range(1, 16)]
    base_ids = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    alt_ids = [1, 2, 3, 5, 7, 8, 9, 10, 12, 13, 14]
    lineup = {
        "formation": "3-4-3",
        "squad_rows": squad,
        "starting_xi": [next(row for row in squad if row["element"] == e) for e in base_ids],
        "captain": {"element": 12, "name": "P12"},
        "vice_captain": {"element": 13, "name": "P13"},
        "captain_safe_pool": [],
        "bench": {"gk": {"element": 15}, "order": [{"element": 5}, {"element": 6}, {"element": 11}]},
        "lineup_score": {"robust": 50.0, "xpts_mean": 55.0, "xpts_std": 8.0},
        "alternatives": [
            {"formation": "3-4-3", "score": 50.0, "xpts_mean": 55.0, "xpts_std": 8.0, "element_ids": base_ids},
            {"formation": "3-4-3", "score": 49.95, "xpts_mean": 54.95, "xpts_std": 8.0, "element_ids": alt_ids},
        ],
        "main_starting_xi_battle": {"status": "CLOSE", "margin": 0.05},
        "chip_context": {"single_chip_rule_respected": True},
        "governance": {},
    }
    projections = {"players": [_projection(e, edge=(e == 5), captain_edge=(e == 13)) for e in range(1, 16)]}
    before = deepcopy(projections)
    result = apply_lineup_overlay(lineup, projections, persist=False)
    selected = {int(row["element"]) for row in result["starting_xi"]}
    assert 5 in selected and 4 not in selected
    assert result["captain"]["element"] == 13
    assert result["governance"]["tactical_xi_tiebreak_applied"] is True
    assert result["governance"]["tactical_captain_tiebreak_applied"] is True
    assert result["governance"]["tactical_direct_xpts_mutation"] is False
    assert projections == before


def test_watchlist_tactical_rerank_preserves_membership():
    payload = {
        "positions": {
            "MID": [
                {"element": 1, "name": "P1", "position": "MID", "dss_score": 90.0, "reasons": ["base"]},
                {"element": 2, "name": "P2", "position": "MID", "dss_score": 89.5, "reasons": ["base"]},
                {"element": 3, "name": "P3", "position": "MID", "dss_score": 85.0, "reasons": ["base"]},
            ]
        }
    }
    projections = {"players": [_projection(1), _projection(2, edge=True), _projection(3)]}
    result = apply_watchlist_overlay(payload, projections)
    rows = result["positions"]["MID"]
    assert [row["element"] for row in rows][:2] == [2, 1]
    assert {row["element"] for row in rows} == {1, 2, 3}
    assert result["governance"]["tactical_membership_promotion_forbidden"] is True
    assert rows[0]["tactical_matchup"]["evidence_state"] == "CUKUP"


def test_report_decoration_covers_owned_watchlist_battle_and_captain():
    projections = {"players": [_projection(1, edge=True), _projection(2), _projection(3, edge=True)]}
    payload = {
        "owned_squad": {"facts": [{"element": 1, "name": "P1"}]},
        "external_watchlist": {"positions": {"MID": [{"element": 2, "name": "P2", "position": "MID"}]}},
        "starting_xi": {"model": {"battle": {"leader_metrics": {"element": 1, "name": "P1"}, "challenger_metrics": {"element": 2, "name": "P2"}}}},
        "captaincy": {"model": {"captain": {"element": 1, "name": "P1"}, "vice": {"element": 3, "name": "P3"}}},
    }
    lineup = {"main_starting_xi_battle": {"tactical_tiebreak": {"eligible": True}}, "governance": {"tactical_xi_tiebreak_applied": True, "tactical_captain_tiebreak_applied": False, "tactical_vice_tiebreak_applied": False}}
    result = decorate_report_payload(payload, projections, lineup)
    assert result["owned_squad"]["facts"][0]["tactical_matchup"]["evidence_state"] == "CUKUP"
    assert result["external_watchlist"]["positions"]["MID"][0]["tactical_matchup"]["evidence_state"] == "TERBATAS"
    assert result["starting_xi"]["model"]["battle"]["leader_metrics"]["tactical_matchup"]
    assert result["captaincy"]["model"]["captain"]["tactical_matchup"]
    assert result["tactical_context"]["decision_usage"]["direct_xpts_mutation"] is False


def test_p17_formation_comparison_reconciles_by_xi_identity_not_row_index():
    positions = {
        1: "GK", 15: "GK",
        2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF",
        7: "MID", 8: "MID", 9: "MID", 10: "MID", 11: "MID",
        12: "FWD", 13: "FWD", 14: "FWD",
    }
    squad = [_squad_row(e, positions[e]) for e in range(1, 16)]
    selected_ids = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    other_formation_ids = [1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13]
    lineup = {
        "formation": "3-4-3",
        "squad_rows": squad,
        "starting_xi": [
            next(row for row in squad if row["element"] == e)
            for e in selected_ids
        ],
        "captain": {"element": 12, "name": "P12"},
        "vice_captain": {"element": 13, "name": "P13"},
        "captain_safe_pool": [],
        "bench": {
            "gk": {"element": 15},
            "order": [{"element": 5}, {"element": 6}, {"element": 11}],
        },
        "lineup_score": {"robust": 50.0, "xpts_mean": 55.0, "xpts_std": 8.0},
        "alternatives": [
            {
                "formation": "3-4-3",
                "score": 50.0,
                "route_utility": 50.0,
                "element_ids": selected_ids,
            },
            {
                "formation": "4-5-1",
                "score": 49.0,
                "route_utility": 49.0,
                "element_ids": other_formation_ids,
            },
        ],
        # Formation rows are intentionally sorted independently from
        # alternatives, matching the P1.7 contract that exposed the CI bug.
        "formation_comparison": [
            {
                "formation": "4-5-1",
                "element_ids": other_formation_ids,
                "route_utility": 49.0,
                "selected": False,
            },
            {
                "formation": "3-4-3",
                "element_ids": selected_ids,
                "route_utility": 50.0,
                "selected": True,
            },
        ],
        "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0},
        "chip_context": {"single_chip_rule_respected": True},
        "governance": {},
    }
    projections = {"players": [_projection(e) for e in range(1, 16)]}
    result = apply_lineup_overlay(lineup, projections, persist=False)
    selected_rows = [
        row
        for row in result["formation_comparison"]
        if row.get("selected") is True
    ]
    assert len(selected_rows) == 1
    assert selected_rows[0]["formation"] == result["formation"] == "3-4-3"
    assert set(selected_rows[0]["element_ids"]) == set(selected_ids)


def test_p17_tactical_overlay_can_reconcile_same_formation_alternative_route():
    positions = {
        1: "GK", 15: "GK",
        2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF",
        7: "MID", 8: "MID", 9: "MID", 10: "MID", 11: "MID",
        12: "FWD", 13: "FWD", 14: "FWD",
    }
    squad = [_squad_row(e, positions[e]) for e in range(1, 16)]
    base_ids = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    alt_ids = [1, 2, 3, 5, 7, 8, 9, 10, 12, 13, 14]
    lineup = {
        "formation": "3-4-3",
        "squad_rows": squad,
        "starting_xi": [
            next(row for row in squad if row["element"] == e)
            for e in base_ids
        ],
        "captain": {"element": 12, "name": "P12"},
        "vice_captain": {"element": 13, "name": "P13"},
        "captain_safe_pool": [],
        "bench": {
            "gk": {"element": 15},
            "order": [{"element": 5}, {"element": 6}, {"element": 11}],
        },
        "lineup_score": {"robust": 50.0, "xpts_mean": 55.0, "xpts_std": 8.0},
        "alternatives": [
            {
                "formation": "3-4-3",
                "score": 50.0,
                "route_utility": 50.0,
                "xpts_mean": 55.0,
                "xpts_std": 8.0,
                "element_ids": base_ids,
            },
            {
                "formation": "3-4-3",
                "score": 49.95,
                "route_utility": 49.95,
                "xpts_mean": 54.95,
                "xpts_std": 8.0,
                "element_ids": alt_ids,
            },
        ],
        "formation_comparison": [
            {
                "formation": "3-4-3",
                "element_ids": base_ids,
                "route_utility": 50.0,
                "selected": True,
            }
        ],
        "main_starting_xi_battle": {"status": "CLOSE", "margin": 0.05},
        "chip_context": {"single_chip_rule_respected": True},
        "governance": {},
    }
    projections = {
        "players": [
            _projection(e, edge=(e == 5))
            for e in range(1, 16)
        ]
    }
    result = apply_lineup_overlay(lineup, projections, persist=False)
    selected_ids = {
        int(row["element"]) for row in result["starting_xi"]
    }
    assert selected_ids == set(alt_ids)
    selected_row = next(
        row
        for row in result["formation_comparison"]
        if row.get("selected") is True
    )
    assert selected_row["formation"] == "3-4-3"
    assert set(selected_row["element_ids"]) == set(alt_ids)
    assert selected_row["selected_route_reconciled_after_tactical_overlay"] is True


def test_p17_native_tactical_overlay_preserves_distributional_owner_decisions():
    positions = {
        1: "GK", 15: "GK",
        2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF",
        7: "MID", 8: "MID", 9: "MID", 10: "MID", 11: "MID",
        12: "FWD", 13: "FWD", 14: "FWD",
    }
    squad = [_squad_row(e, positions[e]) for e in range(1, 16)]
    for row in squad:
        row["selection_score"] = 4.0
    xi_ids = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    lineup = {
        "model": "governed_lineup_v2",
        "native_model": "v12_distributional_lineup_optimizer",
        "formation": "3-4-3",
        "squad_rows": squad,
        "starting_xi": [
            next(row for row in squad if row["element"] == e)
            for e in xi_ids
        ],
        "captain": {"element": 12, "name": "P12"},
        "vice_captain": {"element": 13, "name": "P13"},
        "captain_safe_pool": [
            {"element": 12, "captain_score": 9.0},
            {"element": 13, "captain_score": 8.0},
        ],
        "bench": {
            "gk": {"element": 15, "name": "P15", "position": "GK"},
            "order": [
                {"element": 5, "name": "P5", "position": "DEF"},
                {"element": 6, "name": "P6", "position": "DEF"},
                {"element": 11, "name": "P11", "position": "MID"},
            ],
            "distributional_evaluation": {"bench_order_utility": 3.2},
            "close_battles": [],
        },
        "lineup_score": {
            "robust": 60.0,
            "base_robust": 55.0,
            "xpts_mean": 54.0,
            "xpts_std": 7.0,
            "risk_adjustment": {"method": "P1_7_DISTRIBUTIONAL_UTILITY"},
        },
        "formation_comparison": [
            {
                "formation": "3-4-3",
                "element_ids": xi_ids,
                "route_utility": 60.0,
                "selected": True,
            }
        ],
        "main_starting_xi_battle": {"status": "CLOSE", "margin": 0.1},
        "chip_context": {"single_chip_rule_respected": True},
        "governance": {
            "production_owner": "V12_LINEUP_OPTIMIZER",
            "team_state_authority_consumed": True,
            "legacy_lock_fixture_fallback": False,
        },
    }
    projections = {
        "players": [
            _projection(e, edge=(e == 5), captain_edge=(e == 14))
            for e in range(1, 16)
        ]
    }
    before = deepcopy({
        "starting_xi": lineup["starting_xi"],
        "bench": lineup["bench"],
        "captain": lineup["captain"],
        "vice_captain": lineup["vice_captain"],
        "formation": lineup["formation"],
        "lineup_score": lineup["lineup_score"],
    })
    result = apply_lineup_overlay(lineup, projections, persist=False)
    after = {
        "starting_xi": result["starting_xi"],
        "bench": result["bench"],
        "captain": result["captain"],
        "vice_captain": result["vice_captain"],
        "formation": result["formation"],
        "lineup_score": result["lineup_score"],
    }
    assert after == before
    assert result["governance"]["tactical_overlay_mode"] == "P1_7_NATIVE_OWNER_PRESERVE"
    assert result["governance"]["p1_7_post_owner_decision_mutation"] is False
    assert result["governance"]["tactical_xi_tiebreak_applied"] is False
    assert result["governance"]["tactical_captain_tiebreak_applied"] is False
    assert result["governance"]["tactical_vice_tiebreak_applied"] is False
