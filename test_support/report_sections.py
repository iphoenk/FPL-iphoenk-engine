from __future__ import annotations

from typing import Mapping, Sequence, Any


def _element_ids(our15_rows: Sequence[Mapping[str, Any]]) -> list[int | str]:
    ids: list[int | str] = []
    for row in our15_rows:
        for key in ("element_id", "player_id", "id"):
            if row.get(key) is not None:
                ids.append(row[key])
                break
    return ids


def r4_section_payloads(our15_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    owned_ids = _element_ids(our15_rows)
    tactical_rows = [
        {
            "element_id": identity,
            "opponent_h_a": "AAA (H)",
            "next_gw_fdr": 3,
            "own_team_shape": "4-3-3",
            "opponent_shape": "4-2-3-1",
            "role_archetype": "STARTER",
            "direct_opponent_zone_channel": "left half-space",
            "player_style_fit": "NEUTRAL",
            "coach_system_interaction": "STABLE",
            "set_piece_penalty_relevance": "NONE",
            "rest_weather": "NO MATERIAL IMPACT",
            "p_start": 0.9,
            "xmins": 82,
            "gw_plus_1_xpts": 4.5,
            "matchup_grade": "B",
            "decision_implication": "KEEP",
        }
        for identity in owned_ids
    ]
    price_rows = [
        {
            "element_id": identity,
            "current_price": 7.0,
            "direction": "STABLE",
            "urgency": "LOW",
            "affordability_impact": "NONE",
            "decision_impact": "WAIT",
        }
        for identity in owned_ids
    ]
    return {
        "WEATHER": {
            "content_state": "PASS",
            "rows": [
                {
                    "fixture": "AAA vs BBB",
                    "venue_kickoff": "AAA Stadium | 2026-09-19T15:00:00+01:00",
                    "forecast_time": "2026-09-19T15:00:00+01:00",
                    "temperature": 18.0,
                    "precipitation": "20%",
                    "wind_gust": "18 km/h",
                    "severity": "NORMAL",
                    "fpl_impact": "NO MATERIAL IMPACT",
                }
            ],
        },
        "ICON14B": {
            "content_state": "PASS",
            "current_rank": 4,
            "total_points": 250,
            "gap_to_first": 18,
            "nearest_above": {"manager_id": 10, "gap": 3},
            "nearest_below": {"manager_id": 12, "gap": 2},
            "ownership_share": {"coverage": "COMPLETE"},
            "starter_share": {"coverage": "COMPLETE"},
            "captain_exposure": {"coverage": "COMPLETE"},
            "vice_captain_exposure": {"coverage": "COMPLETE"},
            "chip_exposure": {"coverage": "COMPLETE"},
            "eo": {"coverage": "COMPLETE"},
            "shared_core": [],
            "shields": [],
            "positive_differentials": [],
            "dangers": [],
            "direct_rival_equation": "current rival equation",
            "rank_leverage": {},
            "remaining_ammunition": {"ours": "AVAILABLE"},
            "rival_divergences": [],
            "support_oppose_by_match": [],
            "scenario_paths": [],
            "strategic_implication": "No forced move from mini-league context.",
        },
        "ALL15_TACTICAL": tactical_rows,
        "OPTIMIZER": {
            "content_state": "PASS",
            "routes": [
                {
                    "route_id": "HOLD",
                    "category": "HOLD",
                    "outs": [],
                    "ins": [],
                    "transfer_count": 0,
                    "hit": 0,
                    "resulting_itb": 0.5,
                    "legality": "PASS",
                    "resulting_formation": "3-5-2",
                    "xi_changes": [],
                    "bench_changes": [],
                    "gross_projected_gain": 0.0,
                    "net_projected_gain": 0.0,
                    "xpts3_delta": 0.0,
                    "xpts5_delta": 0.0,
                    "uncertainty": "MEDIUM",
                    "price_impact": "NONE",
                    "optionality_impact": "PRESERVED",
                    "break_even_gw": "N/A",
                }
            ],
        },
        "TRANSFER_STAGE": {
            "stage": "WAIT",
            "route": "HOLD",
            "trigger": "Reassess after team news.",
            "information_value": "Waiting retains material information value.",
            "reversal_conditions": ["Major injury or role change."],
        },
        "PRICE_RISK": {
            "owned_rows": price_rows,
            "candidate_rows": [
                {
                    "element_id": 10001,
                    "current_price": 6.5,
                    "direction": "RISE",
                    "urgency": "WATCH",
                    "affordability_impact": "BUFFER_OK",
                    "decision_impact": "NO CHANGE",
                }
            ],
            "package_affordability": "SAFE",
            "price_optionality": "PRESERVED",
            "source_freshness": "CURRENT",
        },
    }
