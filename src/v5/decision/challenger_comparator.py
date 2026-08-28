from __future__ import annotations

import math
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_challenger_comparator_registry.json"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if data.get("contract") != "V5_OWNED_CHALLENGER_COMPARATOR_V1":
        raise RuntimeError("invalid V5 challenger comparator contract")
    return data


def _position(player: dict[str, Any]) -> str:
    raw = str(player.get("position") or "").upper()
    return {"1": "GK", "2": "DEF", "3": "MID", "4": "FWD", "GKP": "GK"}.get(raw, raw)


def _prediction_index(prediction: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["element"]): row
        for row in prediction.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _owned_ids(team: dict[str, Any]) -> set[int]:
    return {
        int(row["element"])
        for row in team.get("squad") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _finance_index(team: dict[str, Any]) -> dict[int, dict[str, Any]]:
    finance = _dict(team.get("finance"))
    return {
        int(row["element"]): row
        for row in finance.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _watchlist_rows(watchlist: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, items in _dict(watchlist.get("positions")).items():
        for item in items or []:
            if isinstance(item, dict) and item.get("element") is not None:
                rows.append({**item, "position": str(item.get("position") or position)})
    return rows


def _lineup_context(decision: dict[str, Any]) -> dict[str, Any]:
    lineup = _dict(decision.get("lineup"))
    bench = {
        int(row["element"])
        for row in lineup.get("bench") or []
        if isinstance(row, dict) and row.get("element") is not None
    }
    captain = _dict(lineup.get("captain")).get("element")
    vice = _dict(lineup.get("vice_captain")).get("element")
    core = {
        int(value)
        for value in (captain, vice)
        if value is not None
    }
    return {"bench": bench, "core": core}


def _gw_rows(player: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in player.get("xpts_by_gw") or [] if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("gw") or 999))


def _horizon(player: dict[str, Any], count: int) -> dict[str, Any]:
    subset = _gw_rows(player)[: max(0, int(count))]
    mean = sum(_f(row.get("mean")) for row in subset)
    std = math.sqrt(sum(_f(row.get("std")) ** 2 for row in subset))
    xmins = _dict(player.get("xmins"))
    minutes_per_fixture = max(0.0, _f(xmins.get("expected_minutes")))
    fixture_count = sum(len(row.get("fixtures") or []) for row in subset)
    return {
        "mean": round(mean, 3),
        "std": round(std, 3),
        "lower80": round(max(0.0, mean - 1.28 * std), 3),
        "upper80": round(mean + 1.28 * std, 3),
        "expected_minutes": round(minutes_per_fixture * fixture_count, 1),
        "fixture_count": fixture_count,
    }


def _congestion_by_gw(player: dict[str, Any]) -> dict[int, dict[str, Any]]:
    overlay = _dict(player.get("fixture_congestion_overlay"))
    rows: dict[int, dict[str, Any]] = {}
    for item in overlay.get("fixtures") or []:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        if event is None:
            continue
        rows[int(event)] = item
    return rows


def _route_to_points(player: dict[str, Any], fixture: dict[str, Any] | None = None) -> list[str]:
    role = _dict(player.get("role"))
    rates = _dict(player.get("rates"))
    dc = _dict(player.get("defensive_contribution"))
    routes: list[str] = []
    if _f(role.get("penalty_share")) > 0:
        routes.append("PENALTY_ROLE")
    if _f(role.get("set_piece_share")) > 0:
        routes.append("SET_PIECE_ROLE")
    if _f(rates.get("xg90")) > 0.15:
        routes.append("GOAL_THREAT")
    if _f(rates.get("xa90")) > 0.12:
        routes.append("ASSIST_THREAT")
    if _f(dc.get("expected_points90")) > 0.35:
        routes.append("DEFCON_ROUTE")
    if fixture and _position(player) in {"GK", "DEF"} and _f(fixture.get("clean_sheet_probability")) > 0.25:
        routes.append("CLEAN_SHEET_ROUTE")
    return routes or ["APPEARANCE_BASE"]


def _tactical_proxy(player: dict[str, Any], fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _cfg().get("tactical_evidence") or {}
    return {
        "status": str(cfg.get("current_native_level") or "PROXY_ONLY"),
        "current_coach_evidence": "UNAVAILABLE",
        "historical_team_dna": "NOT_USED_AS_CURRENT_FACT",
        "route_to_points": _route_to_points(player, fixture),
        "matchup_edge": "UNVERIFIED_TACTICAL",
        "matchup_risk": ["CURRENT_COACH_OPPONENT_STRUCTURE_NOT_CANONICALLY_RESOLVED"],
        "floor_effect": "UNVERIFIED",
        "ceiling_effect": "UNVERIFIED",
        "matchup_confidence": "LOW",
        "governance": {
            "specific_press_block_or_vulnerability_inferred": False,
            "proxy_is_not_manager_confirmed_tactical_evidence": True,
        },
    }


def _fixture_side(player: dict[str, Any], gw_row: dict[str, Any], congestion: dict[int, dict[str, Any]]) -> dict[str, Any]:
    fixtures = [row for row in gw_row.get("fixtures") or [] if isinstance(row, dict)]
    tactical = [_tactical_proxy(player, row) for row in fixtures] or [_tactical_proxy(player, None)]
    opponents = [row.get("opponent") for row in fixtures]
    home_away = ["H" if bool(row.get("home")) else "A" for row in fixtures]
    gw = int(gw_row.get("gw") or 0)
    rest = congestion.get(gw)
    xmins = _dict(player.get("xmins"))
    return {
        "opponents": opponents,
        "home_away": home_away,
        "venue": ["HOME" if value == "H" else "AWAY" for value in home_away],
        "xpts": round(_f(gw_row.get("mean")), 3),
        "uncertainty": round(_f(gw_row.get("std")), 3),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "probability_60_plus": xmins.get("probability_60_plus") or xmins.get("p60"),
        "dnp_probability": xmins.get("dnp_probability"),
        "tactical_matchup": tactical,
        "rest_congestion": rest if isinstance(rest, dict) else {
            "status": "UNAVAILABLE",
            "application_mode": _dict(player.get("fixture_congestion_overlay")).get("application_mode"),
        },
    }


def _performance_signal(player: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg().get("emerging_screening") or {}
    xmins = _dict(player.get("xmins"))
    role = _dict(player.get("role"))
    rates = _dict(player.get("rates"))
    dc = _dict(player.get("defensive_contribution"))
    start_p = _f(xmins.get("start_probability"))
    dnp = _f(xmins.get("dnp_probability"), max(0.0, 1.0 - start_p))
    exp_mins = _f(xmins.get("expected_minutes"))
    attack_rate = _f(rates.get("xg90")) + _f(rates.get("xa90"))
    triggers: list[dict[str, Any]] = []

    if start_p >= _f(cfg.get("minimum_start_probability"), 0.55) and dnp <= _f(cfg.get("maximum_dnp_probability"), 0.35) and exp_mins >= _f(cfg.get("minimum_expected_minutes"), 50.0):
        triggers.append({"type": "XMINS_SECURITY", "value": round(start_p, 4), "source": "canonical_prediction.xmins"})
    if _f(player.get("xpts_5")) >= _f(cfg.get("minimum_xpts_5"), 16.0):
        triggers.append({"type": "MULTI_GW_PROJECTION", "value": round(_f(player.get("xpts_5")), 3), "source": "canonical_prediction.xpts_5"})
    if attack_rate >= _f(cfg.get("minimum_attack_rate90"), 0.42):
        triggers.append({"type": "ATTACKING_PROCESS", "value": round(attack_rate, 4), "source": "canonical_prediction.robust_rates"})
    if _f(role.get("penalty_share")) >= _f(cfg.get("minimum_penalty_share"), 0.5):
        triggers.append({"type": "PENALTY_ROLE", "value": round(_f(role.get("penalty_share")), 4), "source": "canonical_prediction.role"})
    elif _f(role.get("set_piece_share")) >= _f(cfg.get("minimum_set_piece_share"), 0.5):
        triggers.append({"type": "SET_PIECE_ROLE", "value": round(_f(role.get("set_piece_share")), 4), "source": "canonical_prediction.role"})
    if _f(dc.get("expected_points90")) >= _f(cfg.get("minimum_defcon_points90"), 0.55):
        triggers.append({"type": "DEFCON_ROUTE", "value": round(_f(dc.get("expected_points90")), 4), "source": "canonical_prediction.defcon"})

    count = len(triggers)
    sustainable = max(1, int(cfg.get("sustainable_minimum_trigger_count") or 3))
    strong = max(1, int(cfg.get("strong_minimum_trigger_count") or 2))
    if count >= sustainable and start_p >= _f(cfg.get("minimum_start_probability"), 0.55):
        label = "SUSTAINABLE_CANDIDATE"
    elif count >= strong:
        label = "STRONG"
    elif count >= 1:
        label = str(cfg.get("single_signal_label") or "INTERESTING")
    else:
        label = "NOISE"
    return {
        "label": label,
        "trigger_count": count,
        "triggers": triggers,
        "result_signal_used": False,
        "process_signal_used": any(row["type"] in {"ATTACKING_PROCESS", "XMINS_SECURITY", "MULTI_GW_PROJECTION", "DEFCON_ROUTE"} for row in triggers),
        "sustainability_gate_passed": label == "SUSTAINABLE_CANDIDATE",
        "governance": {
            "one_match_haul_alone_is_not_sufficient": True,
            "no_recent_result_is_fabricated_when_not_present": True,
        },
    }


def _club_counts(team: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in team.get("squad") or []:
        if not isinstance(row, dict) or row.get("team_id") is None:
            continue
        tid = int(row["team_id"])
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def _affordability(owned: dict[str, Any], challenger: dict[str, Any], team: dict[str, Any], finance: dict[int, dict[str, Any]]) -> dict[str, Any]:
    bank = _dict(team.get("finance")).get("bank")
    owned_finance = finance.get(int(owned["element"]), {})
    sell_cost = owned_finance.get("sell_cost")
    challenger_cost = challenger.get("now_cost")
    if sell_cost is None or challenger_cost is None or bank is None:
        affordable = None
        remaining = None
    else:
        remaining = int(sell_cost) + int(bank) - int(challenger_cost)
        affordable = remaining >= 0
    return {
        "affordable": affordable,
        "bank_tenths": int(bank) if bank is not None else None,
        "owned_sell_cost_tenths": int(sell_cost) if sell_cost is not None else None,
        "challenger_purchase_cost_tenths": int(challenger_cost) if challenger_cost is not None else None,
        "remaining_bank_tenths": remaining,
        "finance_source": owned_finance.get("finance_source"),
        "finance_exact": bool(owned_finance.get("finance_exact")) if owned_finance else False,
    }


def _club_legality(owned: dict[str, Any], challenger: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    counts = _club_counts(team)
    out_team = int(owned.get("team_id") or -1)
    in_team = int(challenger.get("team_id") or -1)
    if out_team in counts:
        counts[out_team] = max(0, counts[out_team] - 1)
    counts[in_team] = counts.get(in_team, 0) + 1
    limit = int((_cfg().get("transfer_value") or {}).get("club_limit") or 3)
    legal = max(counts.values(), default=0) <= limit
    return {"legal": legal, "club_limit": limit, "post_swap_club_counts": dict(sorted(counts.items()))}


def _target_rank(challenger: dict[str, Any], owned: dict[str, Any], team: dict[str, Any], decision: dict[str, Any], finance: dict[int, dict[str, Any]]) -> dict[str, Any]:
    cfg = _cfg().get("target_selection") or {}
    weights = {str(key): _f(value) for key, value in _dict(cfg.get("weights")).items()}
    lineup = _lineup_context(decision)
    affordability = _affordability(owned, challenger, team, finance)
    affordable_value = 1.0 if affordability["affordable"] is True else (0.5 if affordability["affordable"] is None else 0.0)
    band = max(1.0, _f(cfg.get("similar_price_band_tenths"), 20.0))
    price_similarity = 1.0 - min(1.0, abs(_f(challenger.get("now_cost")) - _f(owned.get("now_cost"))) / band)
    challenger_x5 = _f(challenger.get("xpts_5"))
    owned_x5 = _f(owned.get("xpts_5"))
    xpts_weakness = _clip((challenger_x5 - owned_x5) / max(1.0, challenger_x5))
    challenger_start = _f(_dict(challenger.get("xmins")).get("start_probability"))
    owned_start = _f(_dict(owned.get("xmins")).get("start_probability"))
    xmins_weakness = _clip(challenger_start - owned_start)
    owned_id = int(owned["element"])
    bench_replaceability = 1.0 if owned_id in lineup["bench"] else 0.25
    premium = _f(owned.get("now_cost")) >= _f(cfg.get("premium_core_price_tenths"), 90.0)
    core = owned_id in lineup["core"] or premium
    non_core_replaceability = 0.0 if core else 1.0
    dimensions = {
        "affordability": affordable_value,
        "price_similarity": price_similarity,
        "xpts_5_weakness": xpts_weakness,
        "xmins_weakness": xmins_weakness,
        "bench_replaceability": bench_replaceability,
        "non_core_replaceability": non_core_replaceability,
    }
    total_weight = sum(weights.values()) or 1.0
    score = sum(weights.get(key, 0.0) * value for key, value in dimensions.items()) / total_weight
    return {
        "score": round(score, 4),
        "dimensions": {key: round(value, 4) for key, value in dimensions.items()},
        "premium_or_core_safeguard": core,
        "affordability": affordability,
        "reason": [
            "same_position",
            "direct_swap_affordability_checked",
            "multi_gw_projection_gap_checked",
            "xmins_security_gap_checked",
            "bench_and_core_structure_checked",
        ],
    }


def _confidence(owned: dict[str, Any], challenger: dict[str, Any], affordability: dict[str, Any]) -> dict[str, Any]:
    level = {"HIGH": 1.0, "MEDIUM_HIGH": 0.85, "MEDIUM": 0.72, "MEDIUM_LOW": 0.58, "LOW": 0.45, "UNKNOWN": 0.4}
    owned_score = level.get(str(owned.get("projection_confidence") or "UNKNOWN").upper(), 0.4)
    challenger_score = level.get(str(challenger.get("projection_confidence") or "UNKNOWN").upper(), 0.4)
    finance_score = 1.0 if affordability.get("finance_exact") else (0.7 if affordability.get("owned_sell_cost_tenths") is not None else 0.4)
    tactical_score = 0.35
    score = (owned_score + challenger_score + finance_score + tactical_score) / 4.0
    label = "HIGH" if score >= 0.8 else ("MEDIUM" if score >= 0.6 else "LOW")
    return {
        "label": label,
        "score": round(score, 4),
        "components": {
            "owned_projection": round(owned_score, 4),
            "challenger_projection": round(challenger_score, 4),
            "finance": round(finance_score, 4),
            "tactical": tactical_score,
        },
        "tactical_cap_applied": True,
    }


def _reversal_triggers() -> list[str]:
    return [
        "challenger_fails_to_start",
        "challenger_xmins_falls_materially",
        "positional_competitor_returns",
        "challenger_role_becomes_deeper_or_less_attacking",
        "owned_player_role_or_xmins_improves",
        "injury_or_suspension",
        "new_european_domestic_cup_or_international_workload",
        "fixture_rearrangement",
        "current_coach_tactical_structure_changes",
        "price_move_breaks_affordability",
        "new_reliable_team_news",
        "underlying_process_regresses",
    ]


def _decision(
    *,
    owned: dict[str, Any],
    challenger: dict[str, Any],
    challenger_type: str,
    performance_signal: dict[str, Any],
    affordability: dict[str, Any],
    club_legality: dict[str, Any],
    raw_gain_5: float,
    net_transfer_value: float | None,
    pair_uncertainty_5: float,
    confidence: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    cfg = _cfg().get("decision_governance") or {}
    reasons: list[str] = []
    risks: list[str] = []
    if affordability.get("affordable") is False:
        return "HOLD_OWNED", ["direct swap is not affordable"], ["requires secondary funding transfer"]
    if not club_legality.get("legal"):
        return "HOLD_OWNED", ["swap violates club limit"], ["squad legality"]
    if challenger_type == "EMERGING_CHALLENGER" and performance_signal.get("label") != "SUSTAINABLE_CANDIDATE":
        return "WATCH_CHALLENGER", ["emerging signal has not passed sustainability gate"], ["recent signal may regress"]
    if raw_gain_5 <= 0:
        return "HOLD_OWNED", ["owned player retains non-negative 5GW projection edge"], []

    uncertainty = max(0.01, pair_uncertainty_5)
    signal_ratio = raw_gain_5 / uncertainty
    review_gain = _f(cfg.get("minimum_gain_for_review_5gw"), 1.5)
    lean_gain = _f(cfg.get("minimum_gain_for_lean_5gw"), 3.5)
    strong_gain = _f(cfg.get("minimum_gain_for_strong_5gw"), 6.0)
    review_ratio = _f(cfg.get("minimum_signal_to_uncertainty_for_review"), 0.35)
    lean_ratio = _f(cfg.get("minimum_signal_to_uncertainty_for_lean"), 0.75)
    strong_ratio = _f(cfg.get("minimum_signal_to_uncertainty_for_strong"), 1.25)

    reasons.extend([f"5GW projected edge={raw_gain_5:.2f}", f"edge/uncertainty={signal_ratio:.2f}"])
    if affordability.get("affordable") is None:
        risks.append("owned sell value or bank is unresolved")
    risks.append("current coach tactical matchup evidence is proxy-only")

    if raw_gain_5 < review_gain or signal_ratio < review_ratio:
        return "WATCH_CHALLENGER", reasons, risks
    if raw_gain_5 >= strong_gain and signal_ratio >= strong_ratio and confidence.get("label") == "HIGH" and not bool(cfg.get("strong_transfer_requires_non_proxy_tactical_evidence", True)):
        return "STRONG_TRANSFER", reasons, risks
    if raw_gain_5 >= lean_gain and signal_ratio >= lean_ratio and confidence.get("label") != "LOW":
        if affordability.get("affordable") is None and bool((_cfg().get("transfer_value") or {}).get("unknown_finance_blocks_lean_or_strong", True)):
            return "REVIEW", reasons, risks
        return "LEAN_TRANSFER", reasons, risks
    if net_transfer_value is not None and net_transfer_value <= 0:
        risks.append("structural and opportunity costs erase raw edge")
    return "REVIEW", reasons, risks


def _pair(
    owned: dict[str, Any],
    challenger: dict[str, Any],
    *,
    challenger_type: str,
    performance_signal: dict[str, Any],
    team: dict[str, Any],
    decision: dict[str, Any],
    finance: dict[int, dict[str, Any]],
    planning_gw: int,
) -> dict[str, Any]:
    cfg = _cfg()
    horizons = [int(value) for value in cfg.get("horizons") or [1, 2, 3, 5]]
    owned_h = {count: _horizon(owned, count) for count in horizons}
    challenger_h = {count: _horizon(challenger, count) for count in horizons}
    affordability = _affordability(owned, challenger, team, finance)
    club_legality = _club_legality(owned, challenger, team)
    confidence = _confidence(owned, challenger, affordability)
    active_chip = str(_dict(_dict(decision.get("lineup")).get("chip_context")).get("active_chip") or _dict(team.get("chip_state")).get("active_chip") or "").lower()
    value_cfg = cfg.get("transfer_value") or {}
    opportunity_cost = _f(value_cfg.get("wildcard_opportunity_cost_points"), 0.0) if active_chip == "wildcard" else _f(value_cfg.get("normal_transfer_opportunity_cost_points"), 1.0)
    structural_cost = _f(value_cfg.get("base_structural_change_cost_points"), 0.5)
    target = _target_rank(challenger, owned, team, decision, finance)
    if target.get("premium_or_core_safeguard"):
        structural_cost += _f(value_cfg.get("premium_core_change_cost_points"), 1.5)

    gains = {count: round(challenger_h[count]["mean"] - owned_h[count]["mean"], 3) for count in horizons}
    raw5 = gains.get(5, 0.0)
    pair_uncertainty_5 = math.sqrt(owned_h.get(5, {}).get("std", 0.0) ** 2 + challenger_h.get(5, {}).get("std", 0.0) ** 2)
    net = None
    if affordability.get("affordable") is not None and club_legality.get("legal"):
        net = round(raw5 - structural_cost - opportunity_cost, 3)

    owned_rows = {int(row.get("gw") or 0): row for row in _gw_rows(owned)[:5]}
    challenger_rows = {int(row.get("gw") or 0): row for row in _gw_rows(challenger)[:5]}
    owned_congestion = _congestion_by_gw(owned)
    challenger_congestion = _congestion_by_gw(challenger)
    fixture_by_fixture = []
    for gw in range(int(planning_gw), int(planning_gw) + 5):
        o_row = owned_rows.get(gw, {"gw": gw, "mean": 0.0, "std": 0.0, "fixtures": []})
        c_row = challenger_rows.get(gw, {"gw": gw, "mean": 0.0, "std": 0.0, "fixtures": []})
        edge = round(_f(c_row.get("mean")) - _f(o_row.get("mean")), 3)
        fixture_by_fixture.append({
            "gw": gw,
            "owned": _fixture_side(owned, o_row, owned_congestion),
            "challenger": _fixture_side(challenger, c_row, challenger_congestion),
            "projected_edge": edge,
            "confidence": confidence["label"],
            "key_reason": "canonical_xpts_difference; tactical evidence remains proxy-only",
        })

    classification, reasons, risks = _decision(
        owned=owned,
        challenger=challenger,
        challenger_type=challenger_type,
        performance_signal=performance_signal,
        affordability=affordability,
        club_legality=club_legality,
        raw_gain_5=raw5,
        net_transfer_value=net,
        pair_uncertainty_5=pair_uncertainty_5,
        confidence=confidence,
    )
    role_sustainability = {
        "start_probability": _dict(challenger.get("xmins")).get("start_probability"),
        "expected_minutes": _dict(challenger.get("xmins")).get("expected_minutes"),
        "rotation_risk": _dict(challenger.get("role")).get("rotation_risk"),
        "set_piece_share": _dict(challenger.get("role")).get("set_piece_share"),
        "penalty_share": _dict(challenger.get("role")).get("penalty_share"),
        "xg90": _dict(challenger.get("rates")).get("xg90"),
        "xa90": _dict(challenger.get("rates")).get("xa90"),
        "defcon_points90": _dict(challenger.get("defensive_contribution")).get("expected_points90"),
        "evidence_level": "CANONICAL_MODEL_FIELDS",
    }
    return {
        "player_out": {"element": owned.get("element"), "name": owned.get("name"), "position": _position(owned), "team_id": owned.get("team_id"), "now_cost": owned.get("now_cost")},
        "player_in": {"element": challenger.get("element"), "name": challenger.get("name"), "position": _position(challenger), "team_id": challenger.get("team_id"), "now_cost": challenger.get("now_cost")},
        "challenger_type": challenger_type,
        "comparison_timestamp": None,
        "planning_gw": int(planning_gw),
        "horizon_1gw": challenger_h.get(1),
        "horizon_2gw": challenger_h.get(2),
        "horizon_3gw": challenger_h.get(3),
        "horizon_5gw": challenger_h.get(5),
        "owned_horizons": {str(key): value for key, value in owned_h.items()},
        "challenger_horizons": {str(key): value for key, value in challenger_h.items()},
        "fixture_by_fixture": fixture_by_fixture,
        "xpts_by_gw": {
            "owned": [round(_f(row.get("mean")), 3) for row in _gw_rows(owned)[:5]],
            "challenger": [round(_f(row.get("mean")), 3) for row in _gw_rows(challenger)[:5]],
        },
        "xmins_by_gw": {
            "owned": [_dict(owned.get("xmins")).get("expected_minutes") for _ in _gw_rows(owned)[:5]],
            "challenger": [_dict(challenger.get("xmins")).get("expected_minutes") for _ in _gw_rows(challenger)[:5]],
        },
        "start_probability_by_gw": {
            "owned": [_dict(owned.get("xmins")).get("start_probability") for _ in _gw_rows(owned)[:5]],
            "challenger": [_dict(challenger.get("xmins")).get("start_probability") for _ in _gw_rows(challenger)[:5]],
        },
        "tactical_matchup_by_gw": [
            {"gw": row["gw"], "owned": row["owned"]["tactical_matchup"], "challenger": row["challenger"]["tactical_matchup"]}
            for row in fixture_by_fixture
        ],
        "rest_congestion_by_gw": [
            {"gw": row["gw"], "owned": row["owned"]["rest_congestion"], "challenger": row["challenger"]["rest_congestion"]}
            for row in fixture_by_fixture
        ],
        "midweek_schedule": {
            "status": "CANONICAL_CONGESTION_OVERLAY_ONLY",
            "detail": "specific unexposed midweek opponent/date remains TBD/UNVERIFIED; no fixture is fabricated",
        },
        "international_context": {
            "status": "UNAVAILABLE_AT_PLAYER_LEVEL",
            "detail": "player call-up/minutes/travel are not inferred without canonical evidence",
        },
        "role_sustainability": role_sustainability,
        "performance_signal": performance_signal,
        "raw_gain_2gw": gains.get(2),
        "raw_gain_3gw": gains.get(3),
        "raw_gain_5gw": gains.get(5),
        "structural_cost": round(structural_cost, 3),
        "opportunity_cost": round(opportunity_cost, 3),
        "net_transfer_value": net,
        "affordability": affordability,
        "club_legality": club_legality,
        "target_selection": target,
        "confidence": confidence,
        "decision": classification,
        "decision_reasons": reasons,
        "decision_risks": risks,
        "reversal_triggers": _reversal_triggers(),
        "data_quality": {
            "owned_projection_confidence": owned.get("projection_confidence"),
            "challenger_projection_confidence": challenger.get("projection_confidence"),
            "finance_resolved": affordability.get("owned_sell_cost_tenths") is not None,
            "tactical_evidence": "PROXY_ONLY",
            "congestion_evidence": "SHADOW_OR_UNAVAILABLE",
            "external_player_consensus": "UNAVAILABLE_NOT_FABRICATED",
        },
        "evidence_classes": {
            "FACT": ["FPL position", "price", "club membership", "owned sell value when resolved"],
            "MODEL": ["canonical xPts", "canonical xMins", "uncertainty", "role/DefCon model fields"],
            "TACTICAL_EVIDENCE": "PROXY_ONLY",
            "CONGESTION_EVIDENCE": "canonical fixture-specific shadow overlay when available",
            "MARKET_CONTEXT": "price/affordability context only",
            "COMMUNITY_SIGNAL": "NOT_USED_AS_FACT",
            "DECISION": classification,
        },
        "external_consensus": {
            "state": "NEUTRAL",
            "status": "NO_PLAYER_LEVEL_EXTERNAL_CONSENSUS_IN_CANONICAL_INPUT",
            "majority_vote_used": False,
        },
        "watchlist_governance_suggestion": (
            "PROMOTE_TO_WATCHLIST"
            if challenger_type == "EMERGING_CHALLENGER" and classification in {"REVIEW", "LEAN_TRANSFER", "STRONG_TRANSFER"}
            else ("KEEP" if challenger_type == "GOVERNED_WATCHLIST" else "NO_CHANGE")
        ),
        "governance": {
            "advisory_only": True,
            "canonical_transfer_recommendation_overwritten": False,
            "watchlist_mutated": False,
            "positive_edge_alone_forces_transfer": False,
        },
    }


def build_comparator(
    prediction: dict[str, Any],
    truth: dict[str, Any],
    watchlist: dict[str, Any],
    decision: dict[str, Any],
    price: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    team = _dict(truth.get("team"))
    if not prediction or not team:
        raise ValueError("challenger comparator requires canonical prediction and truth team")
    pmap = _prediction_index(prediction)
    owned_ids = _owned_ids(team)
    finance = _finance_index(team)
    owned_players = [pmap[eid] for eid in sorted(owned_ids) if eid in pmap]
    watch_rows = _watchlist_rows(watchlist)
    governed_ids = {int(row["element"]) for row in watch_rows if int(row["element"]) in pmap}
    governed = [pmap[eid] for eid in sorted(governed_ids)]

    screening_cfg = cfg.get("emerging_screening") or {}
    allowed_statuses = {str(value) for value in screening_cfg.get("allowed_player_statuses") or ["a", "d"]}
    emerging_screening: list[dict[str, Any]] = []
    eligible_by_position: dict[str, list[dict[str, Any]]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for player in pmap.values():
        eid = int(player["element"])
        if eid in owned_ids or eid in governed_ids or str(player.get("status") or "a") not in allowed_statuses:
            continue
        signal = _performance_signal(player)
        row = {
            "element": eid,
            "name": player.get("name"),
            "position": _position(player),
            "signal": signal,
            "full_comparison_eligible": signal.get("label") == "SUSTAINABLE_CANDIDATE",
        }
        emerging_screening.append(row)
        if row["full_comparison_eligible"] and row["position"] in eligible_by_position:
            eligible_by_position[row["position"]].append(player)

    emerging: list[dict[str, Any]] = []
    per_position = int((cfg.get("limits") or {}).get("max_emerging_per_position") or 3)
    for position, rows in eligible_by_position.items():
        rows.sort(
            key=lambda player: (
                -_f(player.get("xpts_5")),
                -_f(_dict(player.get("xmins")).get("start_probability")),
                int(player.get("element") or 0),
            )
        )
        emerging.extend(rows[:per_position])

    planning_gw = int(prediction.get("planning_gw") or _dict(truth.get("context")).get("planning_gw") or 1)
    max_targets = int((cfg.get("limits") or {}).get("max_owned_targets_per_challenger") or 3)
    max_pairs = int((cfg.get("limits") or {}).get("max_comparisons") or 48)
    comparisons: list[dict[str, Any]] = []
    challenger_summaries: list[dict[str, Any]] = []

    challenger_entries = [(player, "GOVERNED_WATCHLIST") for player in governed] + [(player, "EMERGING_CHALLENGER") for player in emerging]
    for challenger, challenger_type in challenger_entries:
        same_position = [player for player in owned_players if _position(player) == _position(challenger)]
        ranked = sorted(
            same_position,
            key=lambda owned: (
                -_f(_target_rank(challenger, owned, team, decision, finance).get("score")),
                int(owned.get("element") or 0),
            ),
        )[:max_targets]
        signal = _performance_signal(challenger)
        pair_rows = []
        for owned in ranked:
            if len(comparisons) >= max_pairs:
                break
            pair = _pair(
                owned,
                challenger,
                challenger_type=challenger_type,
                performance_signal=signal,
                team=team,
                decision=decision,
                finance=finance,
                planning_gw=planning_gw,
            )
            pair["comparison_timestamp"] = prediction.get("generated_at")
            comparisons.append(pair)
            pair_rows.append(pair)
        best = max(pair_rows, key=lambda row: _f(row.get("raw_gain_5gw"), -999.0), default=None)
        challenger_summaries.append({
            "element": challenger.get("element"),
            "name": challenger.get("name"),
            "position": _position(challenger),
            "challenger_type": challenger_type,
            "performance_signal": signal,
            "candidate_out_rank": [
                {
                    "rank": index + 1,
                    "element": owned.get("element"),
                    "name": owned.get("name"),
                    "target_selection": _target_rank(challenger, owned, team, decision, finance),
                }
                for index, owned in enumerate(ranked)
            ],
            "best_pair_decision": best.get("decision") if isinstance(best, dict) else None,
            "best_pair_raw_gain_5gw": best.get("raw_gain_5gw") if isinstance(best, dict) else None,
            "watchlist_governance_suggestion": best.get("watchlist_governance_suggestion") if isinstance(best, dict) else None,
        })
        if len(comparisons) >= max_pairs:
            break

    decision_counts: dict[str, int] = {}
    for row in comparisons:
        key = str(row.get("decision") or "UNKNOWN")
        decision_counts[key] = decision_counts.get(key, 0) + 1

    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "contract": cfg.get("contract"),
        "model": cfg.get("model_id"),
        "status": "READY",
        "operating_status": cfg.get("status"),
        "comparison_timestamp": prediction.get("generated_at"),
        "planning_gw": planning_gw,
        "horizons": list(cfg.get("horizons") or [1, 2, 3, 5]),
        "governed_watchlist_challengers": len(governed),
        "emerging_screened": len(emerging_screening),
        "emerging_full_comparison_eligible": len(emerging),
        "comparison_count": len(comparisons),
        "decision_counts": decision_counts,
        "challenger_summaries": challenger_summaries,
        "emerging_screening": emerging_screening,
        "comparisons": comparisons,
        "canonical_inputs_reused": [
            "prediction.xpts_by_gw",
            "prediction.xmins",
            "prediction.role",
            "prediction.defensive_contribution",
            "prediction.fixture_congestion_overlay",
            "truth.team.finance.players.sell_cost",
            "truth.team.finance.bank",
            "watchlist.positions",
            "decision.lineup",
        ],
        "known_limitations": [
            "current coach/opponent tactical structure is proxy-only until a canonical tactical evidence layer exists",
            "player-level international workload is unavailable unless canonical evidence is supplied",
            "specific future midweek opponent/date is not fabricated when not exposed by canonical congestion evidence",
            "external model consensus is neutral when no player-level challenger payload is available",
            "decision thresholds are provisional and uncalibrated",
        ],
        "governance": {
            **(_dict(cfg.get("governance"))),
            "watchlist_governance": _dict(cfg.get("watchlist_governance")),
            "decision_governance": _dict(cfg.get("decision_governance")),
            "advisory_only": True,
            "canonical_decision_mutated": False,
            "production_authority": False,
        },
    }
