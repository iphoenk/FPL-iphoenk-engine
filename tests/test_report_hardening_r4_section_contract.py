from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.section_contract import validate_report_sections
from src.runtime_v6.domains.report_plane.report_compute import build_report_compute_contract
from test_support.report_rank20 import rank20_rows


def _our15() -> list[dict]:
    rows = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _xi() -> list[int]:
    return [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]


def _bench() -> list[int]:
    return [2, 7, 12, 15]


def _watchlist20() -> list[dict]:
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _weather() -> dict:
    return {
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
    }


def _icon14b() -> dict:
    return {
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
    }


def _all15_tactical() -> list[dict]:
    rows = []
    for row in _our15():
        rows.append(
            {
                "element_id": row["element_id"],
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
        )
    return rows


def _optimizer() -> dict:
    return {
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
    }


def _transfer_stage() -> dict:
    return {
        "stage": "WAIT",
        "route": "HOLD",
        "trigger": "Reassess after team news.",
        "information_value": "Waiting retains material information value.",
        "reversal_conditions": ["Major injury or role change."],
    }


def _price_risk() -> dict:
    owned_rows = []
    for player_id in range(1, 16):
        owned_rows.append(
            {
                "element_id": player_id,
                "current_price": 7.0,
                "direction": "STABLE",
                "urgency": "LOW",
                "affordability_impact": "NONE",
                "decision_impact": "WAIT",
            }
        )
    return {
        "owned_rows": owned_rows,
        "candidate_rows": [
            {
                "element_id": 101,
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
    }


def _full_sections() -> dict:
    return {
        "OUR15": _our15(),
        "XI_BENCH": {"starting_xi_ids": _xi(), "bench_ids": _bench()},
        "WATCHLIST20": _watchlist20(),
        "RISE20": rank20_rows(201, "RISE"),
        "FALL20": rank20_rows(301, "FALL"),
        "WEATHER": _weather(),
        "ICON14B": _icon14b(),
        "ALL15_TACTICAL": _all15_tactical(),
        "OPTIMIZER": _optimizer(),
        "TRANSFER_STAGE": _transfer_stage(),
        "PRICE_RISK": _price_risk(),
    }


def _extra_sections() -> dict:
    full = _full_sections()
    return {
        key: full[key]
        for key in (
            "WEATHER",
            "ICON14B",
            "ALL15_TACTICAL",
            "OPTIMIZER",
            "TRANSFER_STAGE",
            "PRICE_RISK",
        )
    }


def _compute_kwargs() -> dict:
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": _our15(),
        "starting_xi_ids": _xi(),
        "bench_ids": _bench(),
        "watchlist_rows": _watchlist20(),
        "rise_rows": rank20_rows(201, "RISE"),
        "fall_rows": rank20_rows(301, "FALL"),
        "section_payloads": _extra_sections(),
        "facts": {"official_price": {"source": "OFFICIAL_FPL", "value": 7.5}},
        "models": {"price_signal": {"model": "PRICE_PREDICTOR", "value": 0.8}},
    }


def test_r4_complete_section_contract_passes_all_requested_sections():
    result = validate_report_sections(_full_sections())

    assert result["status"] == "PASS"
    assert result["section_contract_ready"] is True
    assert result["failures"] == []
    assert set(result["checks"]) == {
        "OUR15",
        "XI_BENCH",
        "WATCHLIST20",
        "RISE20",
        "FALL20",
        "WEATHER",
        "ICON14B",
        "ALL15_TACTICAL",
        "OPTIMIZER",
        "TRANSFER_STAGE",
        "PRICE_RISK",
    }


def test_r4_each_section_fails_closed_on_material_structural_gap():
    mutations = {
        "OUR15": lambda payload: payload["OUR15"].pop(),
        "XI_BENCH": lambda payload: payload["XI_BENCH"]["bench_ids"].pop(),
        "WATCHLIST20": lambda payload: payload["WATCHLIST20"].pop(),
        "RISE20": lambda payload: payload["RISE20"][0].pop("eta_human"),
        "FALL20": lambda payload: payload["FALL20"][0].pop("raw_payload_hash"),
        "WEATHER": lambda payload: payload["WEATHER"]["rows"][0].pop("fpl_impact"),
        "ICON14B": lambda payload: payload["ICON14B"].pop("direct_rival_equation"),
        "ALL15_TACTICAL": lambda payload: payload["ALL15_TACTICAL"][4].pop("coach_system_interaction"),
        "OPTIMIZER": lambda payload: payload["OPTIMIZER"]["routes"][0].pop("net_projected_gain"),
        "TRANSFER_STAGE": lambda payload: payload["TRANSFER_STAGE"].pop("reversal_conditions"),
        "PRICE_RISK": lambda payload: payload["PRICE_RISK"]["owned_rows"][3].pop("affordability_impact"),
    }

    for section, mutate in mutations.items():
        payload = _full_sections()
        mutate(payload)
        result = validate_report_sections(payload)
        assert result["status"] == "FAIL", section
        assert section in result["failures"], section
        assert result["checks"][section]["status"] == "FAIL", section


def test_r4_all15_tactical_must_cover_exact_authoritative_owned_ids_not_just_count_15():
    payload = _full_sections()
    payload["ALL15_TACTICAL"][-1]["element_id"] = 999

    result = validate_report_sections(payload)

    assert result["status"] == "FAIL"
    assert "OWNED_ID_SET_MISMATCH" in result["checks"]["ALL15_TACTICAL"]["failures"]


def test_r4_price_risk_must_cover_all15_owned_ids():
    payload = _full_sections()
    payload["PRICE_RISK"]["owned_rows"] = payload["PRICE_RISK"]["owned_rows"][:-1]

    result = validate_report_sections(payload)

    assert result["status"] == "FAIL"
    assert "OWNED_ID_SET_MISMATCH" in result["checks"]["PRICE_RISK"]["failures"]


def test_r4_weather_degraded_is_contract_valid_only_when_explicit_and_explained():
    payload = _full_sections()
    payload["WEATHER"] = {
        "content_state": "DEGRADED",
        "source_status": "DEGRADED",
        "degradation_reason": "Weather tool unavailable at report time.",
        "rows": [],
    }

    valid = validate_report_sections(payload)
    assert valid["status"] == "PASS"
    assert valid["checks"]["WEATHER"]["content_state"] == "DEGRADED"

    broken = deepcopy(payload)
    broken["WEATHER"].pop("degradation_reason")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"
    assert invalid["checks"]["WEATHER"]["status"] == "FAIL"


def test_r4_icon_partial_requires_full_shape_plus_explicit_degradation_metadata():
    payload = _full_sections()
    payload["ICON14B"]["content_state"] = "PARTIAL"
    payload["ICON14B"]["missing_fields"] = ["eo"]
    payload["ICON14B"]["degradation_reason"] = "One rival exposure is unavailable."
    payload["ICON14B"]["eo"] = "UNAVAILABLE"

    valid = validate_report_sections(payload)
    assert valid["status"] == "PASS"
    assert valid["checks"]["ICON14B"]["content_state"] == "PARTIAL"

    broken = deepcopy(payload)
    broken["ICON14B"].pop("eo")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"


def test_r4_optimizer_partial_must_be_truthful_and_cannot_claim_pass_with_broken_route():
    payload = _full_sections()
    payload["OPTIMIZER"] = {
        "content_state": "PARTIAL",
        "degradation_reason": "Exact frontier unavailable; no route is claimed as complete.",
        "routes": [],
    }
    assert validate_report_sections(payload)["status"] == "PASS"

    broken = _full_sections()
    broken["OPTIMIZER"]["routes"][0].pop("legality")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"
    assert invalid["checks"]["OPTIMIZER"]["status"] == "FAIL"


def test_r4_report_compute_cannot_pass_when_extra_section_contract_is_broken():
    kwargs = _compute_kwargs()
    kwargs["section_payloads"]["ALL15_TACTICAL"][0].pop("player_style_fit")

    result = build_report_compute_contract(**kwargs)

    assert result["status"] == "FAIL"
    assert result["compute_ready"] is False
    assert "SECTION_CONTRACT" in result["failures"]
    assert result["SECTION_CONTRACT"]["checks"]["ALL15_TACTICAL"]["status"] == "FAIL"


def test_r4_compute_fingerprint_changes_when_section_semantics_change():
    base = _compute_kwargs()
    changed = deepcopy(base)
    changed["section_payloads"]["TRANSFER_STAGE"]["trigger"] = "Act only if confirmed starter news arrives."

    result_a = build_report_compute_contract(**base)
    result_b = build_report_compute_contract(**changed)

    assert result_a["status"] == "PASS"
    assert result_b["status"] == "PASS"
    assert result_a["compute_fingerprint"] != result_b["compute_fingerprint"]
