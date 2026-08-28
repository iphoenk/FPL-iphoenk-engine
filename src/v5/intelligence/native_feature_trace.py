from __future__ import annotations

from typing import Any

from src.v5.intelligence.feature_bundle import FeatureBundle

TRACE_MODEL = "native_projection_feature_use_v1"
EMPIRICAL_DC_SOURCE = "player_cbit_cbirt_shrunk_to_position_prior"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_any_value(value: dict[str, Any]) -> bool:
    return any(item is not None for item in value.values())


def _declare_player_features(
    player: dict[str, Any],
    enrichment: dict[str, Any],
) -> FeatureBundle:
    bundle = FeatureBundle()
    element = str(int(player.get("element") or 0))
    team_id = str(int(player.get("team_id") or 0))

    current = _dict(player.get("current_season"))
    current_evidence = current if current else None
    bundle.declare(
        "current_season_official",
        current_evidence,
        reason=None if current_evidence else "official current-season row unavailable",
        provenance="official_fpl_bootstrap",
    )
    if current_evidence:
        bundle.consume(
            "current_season_official",
            "native_projection",
            effect_scope="AUTHORITATIVE_XMINS",
            contribution={"starts": current.get("starts"), "minutes": current.get("minutes")},
        )
        bundle.consume(
            "current_season_official",
            "native_projection",
            effect_scope="AUTHORITATIVE_XPTS",
            contribution={"attack_rates": "official cumulative xG/xA + bonus/saves are robustly shrunk"},
        )

    historical = _dict(player.get("historical_prior"))
    bundle.declare(
        "historical_prior",
        historical or None,
        reason=None if historical else "player historical prior unavailable",
        provenance=historical.get("source") if historical else None,
    )
    xmins = _dict(player.get("xmins"))
    historical_xmins = _dict(xmins.get("historical_prior"))
    if historical and bool(historical_xmins.get("available")):
        bundle.consume(
            "historical_prior",
            "native_projection",
            effect_scope="AUTHORITATIVE_XMINS",
            contribution={
                "start_probability": historical_xmins.get("start_probability"),
                "starter_minutes_prior": historical_xmins.get("starter_minutes_prior"),
                "evidence_minutes": historical_xmins.get("evidence_minutes"),
            },
        )
    rates = _dict(player.get("rates"))
    historical_weight = rates.get("historical_attacking_prior_weight")
    if historical and historical_weight is not None and float(historical_weight or 0.0) > 0.0:
        bundle.consume(
            "historical_prior",
            "native_projection",
            effect_scope="AUTHORITATIVE_XPTS",
            contribution={"historical_attacking_prior_weight": historical_weight},
        )

    role = _dict(player.get("role"))
    role_evidence = role if role and _has_any_value(role) else None
    bundle.declare(
        "role_intelligence",
        role_evidence,
        reason=None if role_evidence else "player role evidence unavailable",
        provenance=role.get("set_piece_source") if role else None,
    )
    if role_evidence and (
        role.get("role_start_probability") is not None or role.get("rotation_risk") is not None
    ):
        bundle.consume(
            "role_intelligence",
            "native_projection",
            effect_scope="AUTHORITATIVE_XMINS",
            contribution={
                "role_start_probability": role.get("role_start_probability"),
                "rotation_risk": role.get("rotation_risk"),
            },
        )
    if role_evidence and (
        role.get("set_piece_share") is not None or role.get("penalty_share") is not None
    ):
        bundle.consume(
            "role_intelligence",
            "native_projection",
            effect_scope="AUTHORITATIVE_XPTS",
            contribution={
                "set_piece_share": role.get("set_piece_share"),
                "penalty_share": role.get("penalty_share"),
            },
        )

    fixtures = player.get("fixtures") if isinstance(player.get("fixtures"), list) else []
    bundle.declare(
        "team_strength_fixture_context",
        {"fixture_rows": len(fixtures), "team_id": int(team_id)} if fixtures else None,
        reason=None if fixtures else "no projected fixture row in horizon",
        provenance="native_team_strength+official_fpl_fixtures",
    )
    if fixtures:
        bundle.consume(
            "team_strength_fixture_context",
            "native_projection",
            effect_scope="AUTHORITATIVE_XPTS",
            contribution={"fixture_rows": len(fixtures), "uses_attack_multiplier_and_clean_sheet_probability": True},
        )

    advanced_stats = _dict(enrichment.get("advanced_stats"))
    advanced_players = _dict(advanced_stats.get("players"))
    advanced_player = _dict(advanced_players.get(element))
    attacking_keys = (
        "shots",
        "shot_xg",
        "shots_on_target",
        "box_touches",
        "chances_created",
        "xg",
        "xa",
    )
    attacking_evidence = {
        key: advanced_player.get(key)
        for key in attacking_keys
        if advanced_player.get(key) is not None
    }
    bundle.declare(
        "advanced_attacking_stats",
        attacking_evidence or None,
        reason=None if attacking_evidence else "player advanced attacking evidence unavailable",
        provenance=advanced_stats.get("source"),
    )

    defensive = _dict(player.get("defensive_contribution"))
    defensive_source = str(defensive.get("source") or "")
    defensive_evidence = advanced_player if advanced_player else None
    bundle.declare(
        "advanced_defensive_contribution",
        defensive_evidence,
        reason=None if defensive_evidence else "player defensive evidence unavailable",
        provenance=advanced_stats.get("source"),
    )
    if defensive_evidence and defensive_source == EMPIRICAL_DC_SOURCE:
        bundle.consume(
            "advanced_defensive_contribution",
            "native_projection",
            effect_scope="AUTHORITATIVE_XPTS",
            contribution={
                "source": defensive_source,
                "expected_points90": defensive.get("expected_points90"),
                "evidence_minutes": defensive.get("evidence_minutes"),
            },
        )

    current_form = _dict(enrichment.get("current_form"))
    current_form_players = _dict(current_form.get("players"))
    current_form_player = _dict(current_form_players.get(element))
    bundle.declare(
        "current_form_enrichment",
        current_form_player or None,
        reason=None if current_form_player else "current-form enrichment unavailable for player",
        provenance=current_form.get("source"),
    )

    schedule = _dict(enrichment.get("schedule"))
    league_rest = _dict(_dict(schedule.get("league_rest_days")).get(team_id))
    cross_rest = _dict(_dict(schedule.get("cross_competition_rest_days")).get(team_id))
    rest_evidence = {
        "league": league_rest or None,
        "cross_competition": cross_rest or None,
    }
    if not league_rest and not cross_rest:
        rest_evidence = {}
    bundle.declare(
        "rest_congestion",
        rest_evidence or None,
        reason=None if rest_evidence else "rest/congestion evidence unavailable for team",
        provenance="official_fpl+api_football" if rest_evidence else None,
    )

    preseason = _dict(enrichment.get("preseason"))
    preseason_available = str(preseason.get("evidence_status") or "") == "AVAILABLE"
    bundle.declare(
        "preseason_player_evidence",
        None,
        reason=(
            "global preseason evidence exists but current enrichment has no player attribution"
            if preseason_available
            else "preseason evidence unavailable"
        ),
        provenance="full_core_enrichment",
    )
    return bundle


def _aggregate_feature_bundles(
    player_snapshots: dict[str, dict[str, Any]],
    enrichment: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    names: set[str] = set()
    for snapshot in player_snapshots.values():
        names.update((_dict(snapshot.get("states"))).keys())

    aggregate = FeatureBundle()
    unintegrated: list[str] = []
    for name in sorted(names):
        states = [
            _dict(_dict(snapshot.get("states")).get(name))
            for snapshot in player_snapshots.values()
        ]
        available = sum(1 for state in states if state.get("state") in {"AVAILABLE", "ACTIVE"})
        active = sum(1 for state in states if state.get("state") == "ACTIVE")
        authoritative = sum(1 for state in states if bool(state.get("authoritative_effect")))
        scopes = sorted(
            {
                str(scope)
                for state in states
                for scope in (state.get("effect_scopes") or [])
            }
        )
        evidence = {
            "players_total": len(states),
            "players_available": available,
            "players_active": active,
            "players_authoritative": authoritative,
        }
        aggregate.declare(
            name,
            evidence if available else None,
            reason=None if available else "feature unavailable across all projected players",
            provenance="native_feature_trace_aggregation",
        )
        if available:
            for scope in scopes:
                aggregate.consume(
                    name,
                    "native_projection",
                    effect_scope=scope,
                    contribution={"players_authoritative": authoritative, "players_active": active},
                )
            if authoritative == 0:
                unintegrated.append(name)

    preseason = _dict(enrichment.get("preseason"))
    if str(preseason.get("evidence_status") or "") == "AVAILABLE":
        name = "preseason_player_evidence"
        row = aggregate.get(name)
        if row is None or row.state == "UNAVAILABLE":
            aggregate.declare(
                name,
                {
                    "global_evidence_available": True,
                    "player_attribution_available": False,
                    "row_count": preseason.get("row_count"),
                    "friendly_fixture_count": preseason.get("friendly_fixture_count"),
                },
                provenance="full_core_enrichment",
            )
        if name not in unintegrated:
            unintegrated.append(name)

    return aggregate.snapshot(), sorted(set(unintegrated))


def build_native_feature_trace(
    prediction: dict[str, Any],
    full_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enrichment = full_enrichment if isinstance(full_enrichment, dict) else {}
    players: dict[str, dict[str, Any]] = {}
    for player in prediction.get("players") or []:
        if not isinstance(player, dict) or player.get("element") is None:
            continue
        bundle = _declare_player_features(player, enrichment)
        players[str(int(player["element"]))] = bundle.snapshot()

    aggregate, unintegrated = _aggregate_feature_bundles(players, enrichment)
    return {
        "schema_version": 1,
        "model": TRACE_MODEL,
        "players": players,
        "aggregate_feature_bundle": aggregate,
        "unintegrated_features": unintegrated,
        "governance": {
            "active_means_consumed_not_merely_fetched": True,
            "authoritative_effect_requires_explicit_xmins_xpts_or_decision_scope": True,
            "available_but_unintegrated_features_must_not_be_claimed_as_model_inputs": True,
            "telemetry_does_not_change_prediction_values": True,
        },
    }
