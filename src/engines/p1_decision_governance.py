from __future__ import annotations

from collections import Counter
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _bounded(value: float, limit: float) -> float:
    limit = max(0.0, float(limit))
    return max(-limit, min(limit, float(value)))


def uncertainty_fields(gw_row: dict[str, Any], xmins: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    cfg = policy.get("uncertainty") or {}
    z = _f(cfg.get("z_value"), 1.2815515655)
    mean = _f(gw_row.get("mean"))
    std = max(0.0, _f(gw_row.get("std")))
    lower = mean - z * std
    upper = mean + z * std
    return {
        "lower80": round(lower, 3),
        "upper80": round(upper, 3),
        "interval_width": round(upper - lower, 3),
        "dnp_probability": round(_f(xmins.get("dnp_probability")), 4),
        "bench_probability": round(_f(xmins.get("bench_probability")), 4),
        "cameo_probability": round(_f(xmins.get("cameo_probability")), 4),
        "late_cameo_probability": round(_f(xmins.get("late_cameo_probability")), 4),
        "availability": round(_f(xmins.get("availability", xmins.get("overall_availability", 1.0)), 1.0), 4),
        "xmins_distribution": dict(xmins.get("xmins_distribution") or {}),
    }


def attack_context(proj: dict[str, Any], gw_row: dict[str, Any]) -> dict[str, Any]:
    attack = 0.0
    appearance = 0.0
    for fixture in gw_row.get("fixtures") or []:
        components = fixture.get("components") or {}
        attack += _f(components.get("attack"))
        appearance += _f(components.get("appearance"))
    mean = max(0.0, _f(gw_row.get("mean")))
    focality = attack / mean if mean > 1e-9 else 0.0
    penalty_role = proj.get("penalty_role")
    set_piece_role = proj.get("set_piece_role")
    return {
        "attack_ceiling_proxy": round(max(0.0, attack), 4),
        "appearance_component": round(max(0.0, appearance), 4),
        "focality_proxy": round(max(0.0, min(1.0, focality)), 4),
        "penalty_role_evidence": penalty_role,
        "set_piece_role_evidence": set_piece_role,
        "governance": {
            "attack_ceiling_is_projection_component_proxy": True,
            "missing_penalty_or_set_piece_evidence_is_neutral": True,
        },
    }


def decision_scores(
    proj: dict[str, Any],
    gw_row: dict[str, Any],
    xmins: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    mean = _f(gw_row.get("mean"))
    std = max(0.0, _f(gw_row.get("std")))
    dnp = _f(xmins.get("dnp_probability"))
    start = _f(xmins.get("start_probability"))
    selection = policy.get("selection") or {}
    captaincy = policy.get("captaincy") or {}
    bench_cfg = policy.get("bench") or {}
    context = attack_context(proj, gw_row)

    selection_score = mean - _f(selection.get("risk_aversion_std")) * std - _f(selection.get("dnp_penalty_points")) * dnp
    captain_score = mean - _f(captaincy.get("risk_aversion_std")) * std - _f(captaincy.get("dnp_penalty_points")) * dnp

    vice_delta = (
        _f(captaincy.get("vice_attack_ceiling_weight")) * _f(context.get("attack_ceiling_proxy"))
        + _f(captaincy.get("vice_focality_weight")) * _f(context.get("focality_proxy"))
    )
    if context.get("penalty_role_evidence"):
        vice_delta += _f(captaincy.get("vice_penalty_role_bonus"))
    if context.get("set_piece_role_evidence"):
        vice_delta += _f(captaincy.get("vice_set_piece_role_bonus"))
    vice_delta = _bounded(vice_delta, _f(captaincy.get("maximum_vice_context_adjustment"), 0.35))
    vice_score = captain_score + vice_delta

    bench_base = mean - _f(bench_cfg.get("risk_aversion_std")) * std - _f(bench_cfg.get("dnp_penalty_points")) * dnp
    bench_delta = (
        _f(bench_cfg.get("start_probability_weight")) * start
        + _f(bench_cfg.get("ceiling_weight")) * _f(context.get("attack_ceiling_proxy"))
    )
    bench_delta = _bounded(bench_delta, _f(bench_cfg.get("maximum_context_adjustment"), 0.25))
    bench_score = bench_base + bench_delta

    return {
        "selection_score": round(selection_score, 4),
        "captain_score": round(captain_score, 4),
        "vice_score": round(vice_score, 4),
        "bench_score": round(bench_score, 4),
        "score_decomposition": {
            "raw_xpts": round(mean, 4),
            "uncertainty_penalty_selection": round(_f(selection.get("risk_aversion_std")) * std, 4),
            "dnp_penalty_selection": round(_f(selection.get("dnp_penalty_points")) * dnp, 4),
            "captain_uncertainty_penalty": round(_f(captaincy.get("risk_aversion_std")) * std, 4),
            "captain_dnp_penalty": round(_f(captaincy.get("dnp_penalty_points")) * dnp, 4),
            "vice_context_adjustment": round(vice_delta, 4),
            "bench_context_adjustment": round(bench_delta, 4),
        },
        "attack_context": context,
    }


def state_conditional_slot_utility(
    starter: dict[str, Any],
    *,
    legal_auto_sub_value: float,
) -> dict[str, Any]:
    """V12 lineup utility: cameo blocks auto-sub while DNP preserves it.

    Conditional point values are transparent minutes-scaled proxies used only
    for close-lineup robustness. They do not mutate the machine xPts baseline.
    """
    mean = max(0.0, _f(starter.get("xpts_mean")))
    expected_minutes = max(0.0, _f(starter.get("expected_minutes")))
    start = max(0.0, _f(starter.get("start_probability")))
    cameo = max(0.0, _f(starter.get("cameo_probability")))
    late = max(0.0, min(cameo, _f(starter.get("late_cameo_probability"))))
    dnp = max(0.0, _f(starter.get("dnp_probability")))
    regular_cameo = max(0.0, cameo - late)

    distribution = starter.get("xmins_distribution") or {}
    state_minutes = {
        str(row.get("state") or ""): _f(row.get("minutes_mean"))
        for row in distribution.get("states") or []
        if isinstance(row, dict)
    }
    start_minutes = state_minutes.get(
        "START", _f(starter.get("starter_minutes_if_start"), 70.0)
    )
    cameo_minutes = state_minutes.get(
        "CAMEO", _f(starter.get("cameo_minutes_if_used"), 18.0)
    )
    late_minutes = state_minutes.get(
        "LATE_CAMEO", _f(starter.get("late_cameo_minutes_if_used"), 8.0)
    )
    points_per_minute_proxy = mean / max(1.0, expected_minutes)
    start_points = points_per_minute_proxy * start_minutes
    cameo_points = points_per_minute_proxy * cameo_minutes
    late_points = points_per_minute_proxy * late_minutes
    auto_sub = max(0.0, float(legal_auto_sub_value))
    expected = (
        start * start_points
        + regular_cameo * cameo_points
        + late * late_points
        + dnp * auto_sub
    )
    return {
        "expected_utility": round(expected, 4),
        "start_state_utility": round(start * start_points, 4),
        "cameo_state_utility": round(
            regular_cameo * cameo_points + late * late_points, 4
        ),
        "dnp_auto_sub_utility": round(dnp * auto_sub, 4),
        "legal_auto_sub_value": round(auto_sub, 4),
        "cameo_auto_sub_blocking_cost": round(cameo * auto_sub, 4),
        "auto_sub_preservation_value": round(dnp * auto_sub, 4),
        "conditional_points_proxy": {
            "start": round(start_points, 4),
            "cameo": round(cameo_points, 4),
            "late_cameo": round(late_points, 4),
        },
        "governance": {
            "cameo_is_not_dnp": True,
            "dnp_may_preserve_legal_auto_sub": True,
            "cameo_blocks_auto_sub": True,
            "raw_xpts_unchanged": True,
            "minutes_scaled_conditional_points_are_robustness_proxy_only": True,
        },
    }


def lineup_risk_adjustment(
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    cfg = policy.get("selection") or {}
    defensive = [row for row in starters if row.get("position") in {"GK", "DEF"}]
    team_counts = Counter(int(row.get("team_id") or -1) for row in defensive if int(row.get("team_id") or -1) > 0)
    clustered_extras = sum(max(0, count - 1) for count in team_counts.values())
    cluster_penalty = clustered_extras * _f(cfg.get("same_team_defensive_cluster_penalty"), 0.08)

    defensive_route_points = sum(max(0.0, _f(row.get("defensive_route_proxy"))) for row in starters)
    total_points = sum(max(0.0, _f(row.get("xpts_mean"))) for row in starters)
    route_share = defensive_route_points / total_points if total_points > 1e-9 else 0.0
    concentration_penalty = max(0.0, route_share - 0.50) * _f(cfg.get("defensive_route_concentration_penalty"), 0.06)

    usable_bench = [row for row in bench_rows if row.get("position") != "GK"]
    bench_utility = sum(max(0.0, _f(row.get("bench_score"))) for row in usable_bench[:3]) / max(1, len(usable_bench[:3]))
    bench_bonus = min(0.12, _f(cfg.get("bench_utility_weight"), 0.03) * bench_utility / 5.0)

    raw_adjustment = -cluster_penalty - concentration_penalty + bench_bonus
    adjustment = _bounded(raw_adjustment, _f(cfg.get("maximum_close_call_adjustment"), 0.30))
    return {
        "adjustment": round(adjustment, 4),
        "defensive_cluster_penalty": round(cluster_penalty, 4),
        "defensive_route_concentration_penalty": round(concentration_penalty, 4),
        "bench_utility_bonus": round(bench_bonus, 4),
        "same_team_defensive_cluster_extras": clustered_extras,
        "defensive_route_share": round(route_share, 4),
        "bench_utility_proxy": round(bench_utility, 4),
        "governance": {
            "bounded_decision_adjustment_only": True,
            "raw_xpts_unchanged": True,
            "no_attacking_formation_bonus": True,
        },
    }


def choose_close_call_lineup(candidates: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank all legal XI by current distributional robustness semantics.

    The legacy fixed gap is retained only as presentation metadata. It does not
    decide which candidate may win the canonical V12 ranking.
    """
    if not candidates:
        return []
    base_sorted = sorted(
        candidates,
        key=lambda row: (_f(row.get("base_score")), _f(row.get("xpts_mean"))),
        reverse=True,
    )
    anchor = _f(base_sorted[0].get("base_score"))
    ui_gap = _f(
        (policy.get("selection") or {}).get("close_call_rerank_gap"), 0.75
    )
    for row in candidates:
        row["legacy_ui_close_candidate"] = (
            anchor - _f(row.get("base_score")) <= ui_gap + 1e-9
        )
        row["legacy_close_gap_is_decision_authority"] = False

    if all(row.get("v12_expected_utility") is not None for row in candidates):
        return sorted(
            candidates,
            key=lambda row: (
                _f(row.get("v12_expected_utility")),
                _f(row.get("conditional_floor"), -1e9),
                -_f(row.get("expected_regret"), 0.0),
                _f(row.get("decision_score")),
                _f(row.get("xpts_mean")),
            ),
            reverse=True,
        )

    # Compatibility only for isolated legacy unit fixtures that do not carry
    # V12 robustness evidence. Production lineup candidates always do.
    close = [
        row
        for row in base_sorted
        if anchor - _f(row.get("base_score")) <= ui_gap + 1e-9
    ]
    distant = [row for row in base_sorted if row not in close]
    close.sort(
        key=lambda row: (
            _f(row.get("decision_score")),
            _f(row.get("base_score")),
            _f(row.get("xpts_mean")),
        ),
        reverse=True,
    )
    return close + distant


def vice_rank(starters: list[dict[str, Any]], captain_element: int, policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [row for row in starters if int(row.get("element") or -1) != int(captain_element)]
    candidates.sort(key=lambda row: (_f(row.get("vice_score")), _f(row.get("captain_score"))), reverse=True)
    guard = _f((policy.get("captaincy") or {}).get("vice_defender_small_edge_guard"), 0.30)
    if not candidates:
        return []
    top = candidates[0]
    if top.get("position") in {"GK", "DEF"}:
        attackers = [row for row in candidates if row.get("position") in {"MID", "FWD"}]
        if attackers:
            attacker = attackers[0]
            if _f(top.get("vice_score")) - _f(attacker.get("vice_score")) <= guard + 1e-9:
                if _f(attacker.get("attack_ceiling_proxy")) > _f(top.get("attack_ceiling_proxy")):
                    candidates.remove(attacker)
                    candidates.insert(0, attacker)
    return candidates


def bench_battles(outfield: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = _f((policy.get("bench") or {}).get("close_battle_threshold"), 0.35)
    rows = sorted(outfield, key=lambda row: (_f(row.get("bench_score")), _f(row.get("xpts_mean"))), reverse=True)
    battles: list[dict[str, Any]] = []
    for first, second in zip(rows, rows[1:]):
        margin = _f(first.get("bench_score")) - _f(second.get("bench_score"))
        if margin <= threshold + 1e-9:
            battles.append({
                "higher": {"element": first.get("element"), "name": first.get("name"), "bench_score": first.get("bench_score")},
                "lower": {"element": second.get("element"), "name": second.get("name"), "bench_score": second.get("bench_score")},
                "margin": round(margin, 4),
                "status": "CLOSE",
            })
    return battles
