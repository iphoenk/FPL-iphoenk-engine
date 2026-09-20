from __future__ import annotations

import math
from typing import Any, Mapping

from src.engines.v12_contextual_dynamics import (
    build_contextual_dynamics,
    enrich_match_rows,
    evaluate_linkup,
)
from src.engines.v12_player_events import (
    aggregate_gameweek,
    build_posterior_rates,
    load_event_config,
    project_player_fixture,
)
from src.engines.v12_player_minutes import estimate_xmins
from src.rules import ELEMENT_TYPE_TO_POSITION, RULESET_ID


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def build(
    bootstrap: dict[str, Any],
    strength: dict[str, Any],
    planning_gw: int,
    prior_payload: dict[str, Any],
    horizon: int | None = None,
    player_features_payload: dict[str, Any] | None = None,
    player_match_rows: list[Mapping[str, Any]] | None = None,
    player_connection_rows: list[Mapping[str, Any]] | None = None,
    *,
    calibration_summary: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_event_config()
    published_horizons = [
        int(value) for value in cfg.get("published_horizons") or []
    ]
    if not published_horizons or any(value <= 0 for value in published_horizons):
        raise RuntimeError(
            "player_events published_horizons must be configured as positive integers"
        )
    horizon = int(horizon or max(published_horizons))
    if horizon < max(published_horizons):
        raise RuntimeError(
            "projection runtime horizon cannot be shorter than published horizons"
        )

    feature_payload = player_features_payload or {}
    feature_map = feature_payload.get("players") or {}
    tactical_policy = feature_payload.get("tactical_role_policy") or {}
    if (
        tactical_policy
        and tactical_policy.get("decision_influence") != "ADVISORY_ONLY"
    ):
        raise RuntimeError(
            "P1.3 forbids P1.6 tactical scoring; tactical evidence must remain advisory-only"
        )

    teams = {
        int(team["id"]): team.get("name")
        for team in bootstrap.get("teams") or []
    }
    positions = dict(ELEMENT_TYPE_TO_POSITION)
    team_rows = {
        int(team["team_id"]): team for team in strength.get("teams") or []
    }
    historical_map = prior_payload.get("players") or {}
    player_team = {
        int(row.get("id") or -1): int(row.get("team") or -1)
        for row in bootstrap.get("elements") or []
        if int(row.get("id") or -1) > 0
    }
    match_rows = enrich_match_rows(
        [
            dict(row)
            for row in (player_match_rows or [])
            if isinstance(row, Mapping)
        ],
        player_team=player_team,
    )
    connection_rows = [
        dict(row)
        for row in (player_connection_rows or [])
        if isinstance(row, Mapping)
    ]
    latest_completed_gw = max(
        [
            int(row.get("gw") or row.get("event") or 0)
            for row in match_rows
            if _f(row.get("minutes_played"), _f(row.get("minutes"))) > 0
        ]
        or [max(1, planning_gw - 1)]
    )
    matchups_by_team: dict[int, list[dict[str, Any]]] = {}
    for matchup in strength.get("matchups") or []:
        for team_id in (int(matchup["team_h"]), int(matchup["team_a"])):
            matchups_by_team.setdefault(team_id, []).append(matchup)
    for rows in matchups_by_team.values():
        rows.sort(
            key=lambda row: (
                int(row.get("event") or 999),
                row.get("kickoff_time") or "",
            )
        )

    position_priors = cfg.get("position_priors") or {}
    players = []
    historical_used = 0
    advanced_dc_used = 0
    tactical_role_used = 0
    system_context_used = 0
    robust_winsorized_players = 0

    for player in bootstrap.get("elements") or []:
        element = int(player["id"])
        element_type = int(player.get("element_type") or 0)
        position = positions.get(element_type)
        if not position:
            raise RuntimeError(
                f"unsupported Official element_type: {element_type}"
            )
        base = position_priors.get(position)
        if not isinstance(base, dict):
            raise RuntimeError(f"event prior missing for position {position}")

        historical = historical_map.get(str(element)) or {}
        historical_used += int(bool(historical))
        feature = feature_map.get(str(element)) or {}
        tactical_role = feature.get("tactical_role") or {
            "profile": "UNASSESSED",
            "confidence": "NONE",
            "decision_influence": "ADVISORY_ONLY",
        }
        system_context = feature.get("system_context") or {
            "label": "FPL_POSITION_SHAPE",
            "dominant_shape": None,
            "confidence": "NONE",
            "decision_influence": "ADVISORY_ONLY",
        }
        tactical_role_used += int(
            tactical_role.get("profile") not in {None, "UNASSESSED"}
        )
        system_context_used += int(bool(system_context.get("dominant_shape")))

        rates = build_posterior_rates(
            player,
            position_prior=base,
            historical=historical,
            feature=feature,
        )
        robust_winsorized_players += int(
            bool((rates.get("goal") or {}).get("winsorized"))
            or bool((rates.get("assist") or {}).get("winsorized"))
        )
        advanced_dc_used += int(
            _f((rates.get("defcon") or {}).get("evidence_minutes")) > 0
        )

        team_id = int(player.get("team") or -1)
        matches_played = int(
            (team_rows.get(team_id) or {}).get("matches_played") or 0
        )
        context: dict[str, Any] = {"team_matches_played": matches_played}
        if historical:
            context.update(
                {
                    "prior_start_probability": historical.get(
                        "start_probability"
                    ),
                    "starter_minutes_prior": historical.get(
                        "avg_minutes_when_start"
                    ),
                    "prior_evidence_minutes": historical.get("minutes"),
                    "prior_source": historical.get("source"),
                    "prior_identity_match": historical.get("identity_match"),
                }
            )
        xmins = estimate_xmins(
            player,
            context,
            calibration_summary=calibration_summary,
            model_evidence_binding=model_evidence_binding,
        )
        xmins.setdefault("governance", {}).update(
            {
                "tactical_role_evidence_available": tactical_role.get(
                    "profile"
                )
                not in {None, "UNASSESSED"},
                "team_system_context_available": bool(
                    system_context.get("dominant_shape")
                ),
                "rec41_tactical_adjustment_applied": False,
                "reason": "P1.3 fixture adjustment excludes P1.6 tactical scorer",
            }
        )

        fixtures = [
            matchup
            for matchup in matchups_by_team.get(team_id, [])
            if planning_gw
            <= int(matchup.get("event") or -1)
            < planning_gw + horizon
        ]

        teammate_links: list[dict[str, Any]] = []
        teammate_start_probabilities: dict[int, float] = {}
        if match_rows:
            target_role = tactical_role.get("profile")
            for teammate in bootstrap.get("elements") or []:
                teammate_id = int(teammate.get("id") or -1)
                if teammate_id <= 0 or teammate_id == element:
                    continue
                if int(teammate.get("team") or -2) != team_id:
                    continue
                teammate_feature = feature_map.get(str(teammate_id)) or {}
                teammate_role = (
                    teammate_feature.get("tactical_role") or {}
                ).get("profile")
                link = evaluate_linkup(
                    match_rows,
                    match_rows,
                    target_player_id=element,
                    teammate_player_id=teammate_id,
                    target_role=target_role,
                    teammate_role=teammate_role,
                    connection_rows=connection_rows,
                )
                if (
                    _f(link.get("confidence")) > 0.0
                    and int(link.get("shared_matches") or 0) > 0
                ):
                    link["target_role"] = target_role
                    link["teammate_role"] = teammate_role
                    teammate_links.append(link)
                teammate_matches = int(
                    (team_rows.get(team_id) or {}).get("matches_played") or 0
                )
                teammate_historical = historical_map.get(str(teammate_id)) or {}
                teammate_context: dict[str, Any] = {
                    "team_matches_played": teammate_matches
                }
                if teammate_historical:
                    teammate_context.update(
                        {
                            "prior_start_probability": teammate_historical.get(
                                "start_probability"
                            ),
                            "starter_minutes_prior": teammate_historical.get(
                                "avg_minutes_when_start"
                            ),
                            "prior_evidence_minutes": teammate_historical.get(
                                "minutes"
                            ),
                        }
                    )
                teammate_xmins = estimate_xmins(
                    teammate,
                    teammate_context,
                    calibration_summary=calibration_summary,
                    model_evidence_binding=model_evidence_binding,
                )
                teammate_start_probabilities[teammate_id] = _f(
                    teammate_xmins.get("start_probability")
                )
            teammate_links.sort(
                key=lambda row: (
                    _f(row.get("confidence")),
                    _f(row.get("dependency_strength")),
                ),
                reverse=True,
            )
            teammate_links = teammate_links[:5]

        def fixture_key(matchup: Mapping[str, Any]) -> str:
            gw_value = int(matchup.get("event") or matchup.get("gw") or 0)
            return str(
                matchup.get("fixture")
                or matchup.get("id")
                or (
                    f"gw{gw_value}:{matchup.get('team_h')}:"
                    f"{matchup.get('team_a')}:"
                    f"{matchup.get('kickoff_time') or 'unknown'}"
                )
            )

        contextual_by_fixture: dict[str, dict[str, Any]] = {}
        if match_rows:
            for matchup in fixtures:
                opponent_id = (
                    int(matchup.get("team_a") or -1)
                    if int(matchup.get("team_h") or -1) == team_id
                    else int(matchup.get("team_h") or -1)
                )
                current_context = {
                    "manager_id": matchup.get("opponent_manager_id"),
                    "formation": matchup.get("opponent_formation"),
                    "block_height": matchup.get("opponent_block_height"),
                    "pressing_style": matchup.get("opponent_pressing_style"),
                    "cb_personnel": matchup.get("opponent_cb_personnel"),
                    "fb_personnel": matchup.get("opponent_fb_personnel"),
                    "midfield_structure": matchup.get(
                        "opponent_midfield_structure"
                    ),
                    "player_role": tactical_role.get("profile"),
                }
                contextual_by_fixture[fixture_key(matchup)] = (
                    build_contextual_dynamics(
                        match_rows,
                        player_id=element,
                        current_gw=latest_completed_gw,
                        opponent_team_id=opponent_id,
                        current_context=current_context,
                        linkups=teammate_links,
                        teammate_start_probabilities=(
                            teammate_start_probabilities
                        ),
                    )
                )

        by_gw = []
        for gw in range(planning_gw, planning_gw + horizon):
            details = [
                project_player_fixture(
                    player,
                    xmins,
                    matchup,
                    home=int(matchup["team_h"]) == team_id,
                    rates=rates,
                    league_baseline=strength.get("baseline") or {},
                    calibration_summary=calibration_summary,
                    model_evidence_binding=model_evidence_binding,
                    contextual_dynamics=contextual_by_fixture.get(
                        fixture_key(matchup)
                    ),
                )
                for matchup in fixtures
                if int(matchup.get("event") or -1) == gw
            ]
            by_gw.append(aggregate_gameweek(details, gw=gw))

        horizons = {}
        for published in published_horizons:
            subset = by_gw[:published]
            mean = sum(_f(row.get("mean")) for row in subset)
            variance = sum(
                _f(row.get("points_variance"), _f(row.get("std")) ** 2)
                for row in subset
            )
            exact_distribution = None
            exact_events = None
            if published == 1 and len(subset) == 1:
                exact_distribution = dict(
                    subset[0].get("point_distribution") or {}
                )
                exact_events = dict(
                    subset[0].get("event_probabilities") or {}
                )
            horizons[str(published)] = {
                "mean": round(mean, 3),
                "std": round(math.sqrt(max(0.0, variance)), 3),
                "event_probabilities": exact_events,
                "point_distribution": exact_distribution,
                "distribution_aggregation_status": (
                    "EXACT_GW1_SINGLE_FIXTURE"
                    if exact_distribution
                    else "PARTIAL_CROSS_GW_COVARIANCE_NOT_MODELLED"
                ),
                "tail_aggregation_status": (
                    "AVAILABLE_GW1_SINGLE_FIXTURE"
                    if exact_distribution
                    else "PARTIAL_NOT_AGGREGATED"
                ),
                "dependency_assumption": "ZERO_CROSS_GW_COVARIANCE_NOT_MODELLED_YET",
            }

        defcon = dict(rates.get("defcon") or {})
        players.append(
            {
                "element": element,
                "name": player.get("web_name"),
                "team_id": team_id,
                "team": teams.get(team_id),
                "position": position,
                "element_type": element_type,
                "now_cost": int(player.get("now_cost") or 0),
                "status": player.get("status"),
                "ownership_pct": _f(player.get("selected_by_percent")),
                "current_season": {
                    "starts": int(player.get("starts") or 0),
                    "minutes": int(player.get("minutes") or 0),
                },
                "historical_prior": historical or None,
                "tactical_role": tactical_role,
                "system_context": system_context,
                "xmins": xmins,
                "rates": {
                    "xg90": round(
                        _f((rates.get("goal") or {}).get("posterior_rate90")),
                        4,
                    ),
                    "xa90": round(
                        _f((rates.get("assist") or {}).get("posterior_rate90")),
                        4,
                    ),
                    "bonus90": round(
                        _f((rates.get("bonus") or {}).get("posterior_rate90")),
                        4,
                    ),
                    "saves90": round(
                        _f((rates.get("saves") or {}).get("posterior_rate90")),
                        4,
                    ),
                    "dc90": round(_f(defcon.get("expected_points90")), 4),
                    "dc_count90": round(
                        _f(defcon.get("posterior_count_rate90")), 4
                    ),
                    "dc_threshold": defcon.get("threshold"),
                    "dc_points": defcon.get("points"),
                    "dc_evidence_minutes": round(
                        _f(defcon.get("evidence_minutes")), 1
                    ),
                    "dc_sample_quality": defcon.get("sample_quality"),
                    "robust_rate_diagnostics": {
                        "xg90": rates.get("goal"),
                        "xa90": rates.get("assist"),
                    },
                    "sources": {
                        "xg90": (rates.get("goal") or {}).get("provenance"),
                        "xa90": (rates.get("assist") or {}).get("provenance"),
                        "bonus90": (rates.get("bonus") or {}).get("provenance"),
                        "saves90": (rates.get("saves") or {}).get("provenance"),
                        "dc90": defcon.get("source"),
                    },
                    "historical_attacking_prior_weight": rates.get(
                        "historical_attacking_prior_weight"
                    ),
                },
                "posterior_rates": rates,
                "xpts_by_gw": by_gw,
                "horizons": horizons,
                "projection_confidence": xmins.get("confidence"),
                "contextual_dynamics": {
                    "status": (
                        "AVAILABLE"
                        if contextual_by_fixture
                        else "UNAVAILABLE"
                    ),
                    "latest_completed_gw": latest_completed_gw,
                    "fixture_contexts": [
                        {
                            "fixture": key,
                            "trajectory_classification": (
                                (value.get("trajectory") or {}).get(
                                    "trajectory_classification"
                                )
                            ),
                            "latest_match_evidence": (
                                (value.get("trajectory") or {}).get(
                                    "latest_match_evidence"
                                )
                            ),
                            "matchup": value.get(
                                "opponent_specific_matchup"
                            ),
                            "linkup_network": value.get("linkup_network"),
                            "event_multipliers": value.get(
                                "event_multipliers"
                            ),
                        }
                        for key, value in contextual_by_fixture.items()
                    ],
                },
            }
        )

    return {
        "model": cfg.get("historical_projection_model_id"),
        "event_model": cfg.get("model_id"),
        "event_model_owner": cfg.get("model_owner"),
        "ruleset_id": RULESET_ID,
        "planning_gw": planning_gw,
        "horizon_gws": horizon,
        "published_horizons": published_horizons,
        "historical_prior_model": prior_payload.get("model"),
        "historical_prior_season": prior_payload.get("season"),
        "historical_prior_players_used": historical_used,
        "player_feature_contract": feature_payload.get("contract"),
        "player_feature_model_opt_in": feature_payload.get("model_opt_in"),
        "defensive_contribution_model": "poisson_threshold_shrunk_rate_v12",
        "advanced_defensive_evidence_players_used": advanced_dc_used,
        "tactical_role_contract": tactical_policy.get("contract"),
        "tactical_role_model": tactical_policy.get("model_id"),
        "tactical_role_decision_influence": tactical_policy.get(
            "decision_influence"
        )
        or "ADVISORY_ONLY",
        "tactical_role_players_observed": tactical_role_used,
        "team_system_players_with_observed_shape": system_context_used,
        "rec41_tactical_adjustment_applied": False,
        "robust_winsorized_players": robust_winsorized_players,
        "players": players,
        "governance": {
            "v12_native_event_engine": True,
            "p1_1_minutes_owner": "src/engines/v12_player_minutes.py",
            "p1_3_event_owner": "src/engines/v12_player_events.py",
            "contextual_dynamics_owner": (
                "src/engines/v12_contextual_dynamics.py"
            ),
            "contextual_dynamics_reuses_existing_v6_player_match_rows": True,
            "legacy_projection_components_migration_oracle_only": True,
            "multi_fixture_dependency_assumption": "ZERO_CROSS_FIXTURE_COVARIANCE_NOT_MODELLED_YET",
            "p1_3b_joint_event_distribution": True,
            "multi_gw_tail_aggregation": "PARTIAL_UNTIL_CROSS_FIXTURE_DEPENDENCE_MODELLED",
            "p1_6_tactical_scorer_applied": False,
            "p1_7_started": False,
            "package_optimizer_started_by_p1_3b": False,
            "mini_league_overlay_started_by_p1_3b": False,
            "monte_carlo_applied": False,
            "methodology_weights_20_25_30_25_unchanged": True,
        },
    }
