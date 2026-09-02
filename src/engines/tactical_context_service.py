from __future__ import annotations

import json
from typing import Any

from src.models.observed_tactical_context import (
    build_current_recent_rows,
    load_config as load_observed_config,
    merge_recent_history,
    player_return_routes,
    summarize_team_history,
)
from src.utils import DATA, atomic_json, iso_now, read_json

TEAM_OUT = DATA / "tactical_team_profiles.json"
ROLE_OUT = DATA / "player_role_profiles.json"
RECENT_OUT = DATA / "recent_tactical_form.json"


def _team_names(official: dict[str, Any]) -> dict[int, str]:
    bootstrap = official.get("bootstrap") or {}
    out: dict[int, str] = {}
    for row in bootstrap.get("teams") or []:
        try:
            team_id = int(row.get("id") or -1)
        except (TypeError, ValueError):
            continue
        if team_id > 0:
            out[team_id] = str(row.get("name") or row.get("short_name") or team_id)
    return out


def build() -> dict[str, dict[str, Any]]:
    official = read_json(DATA / "official_snapshot.json", {})
    bootstrap = official.get("bootstrap") or {}
    elements = bootstrap.get("elements") or []
    features = read_json(DATA / "player_features.json", {})
    if features.get("contract") != "PLAYER_FEATURE_CONTRACT_V1":
        raise RuntimeError("tactical context requires canonical PLAYER_FEATURE_CONTRACT_V1")

    names = _team_names(official)
    systems = features.get("team_system_context") or {}
    players = features.get("players") or {}
    match_payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    shots_payload = read_json(DATA / "stats" / "shots_current.json", {})
    observed_cfg = load_observed_config()
    previous_recent = read_json(RECENT_OUT, {})
    current_recent = build_current_recent_rows(elements, match_payload, shots_payload, systems, observed_cfg)
    recent_teams = merge_recent_history(previous_recent, current_recent, sorted(names), observed_cfg)
    generated_at = iso_now()

    team_rows: dict[str, Any] = {}
    teams_with_recent = 0
    for team_id, name in sorted(names.items()):
        system = systems.get(str(team_id)) or {}
        history = recent_teams.get(str(team_id)) or []
        history_summary = summarize_team_history(history, observed_cfg)
        teams_with_recent += int(bool(history))
        base_shape = history_summary.get("dominant_shape") or system.get("dominant_shape")
        variants = history_summary.get("formation_variants") or ([system.get("dominant_shape")] if system.get("dominant_shape") else [])
        strengths = history_summary.get("strengths") or []
        vulnerabilities = history_summary.get("vulnerabilities") or []
        style_proxies = history_summary.get("observed_style_proxies") or []
        team_rows[str(team_id)] = {
            "team_id": team_id,
            "team_name": name,
            "coach": None,
            "base_formation": base_shape,
            "formation_variants": variants,
            "build_up": None,
            "pressing": None,
            "defensive_line": None,
            "width": None,
            "transition": None,
            "set_piece_profile": "OBSERVED_HIGH_SET_PIECE_ACTIVITY" if "set_piece_activity" in strengths else None,
            "vulnerabilities": vulnerabilities,
            "strengths": strengths,
            "observed_style_proxies": style_proxies,
            "recent_match_count": int(history_summary.get("matches") or 0),
            "evidence": {
                "class": "OBSERVED_SHAPE_PLUS_MATCH_EVENTS" if history else "OBSERVED_FPL_POSITION_SHAPE",
                "confidence": history_summary.get("confidence") if history else (system.get("confidence") or "NONE"),
                "valid_matches": int(system.get("valid_matches") or 0),
                "observed_matches": int(system.get("observed_matches") or 0),
                "recent_match_events": int(history_summary.get("matches") or 0),
                "shape_consistency": float(system.get("shape_consistency") or 0.0),
                "not_true_tactical_formation": True,
                "true_pressing_not_inferred": True,
                "true_build_up_not_inferred": True,
                "source": "PLAYER_FEATURE_CONTRACT_V1 + TACTICAL_OBSERVED_CONTEXT_V1",
            },
        }

    role_rows: dict[str, Any] = {}
    assessed = 0
    routes_covered = 0
    for key, player in players.items():
        role = player.get("tactical_role") or {}
        profile = role.get("profile")
        route_evidence = player_return_routes(player)
        if profile and profile != "UNASSESSED":
            assessed += 1
        if route_evidence.get("return_routes"):
            routes_covered += 1
        role_rows[str(key)] = {
            "element": int(player.get("element") or key),
            "name": player.get("name"),
            "team_id": int(player.get("team_id") or -1),
            "position": player.get("position"),
            "role": profile if profile and profile != "UNASSESSED" else None,
            "zones": route_evidence.get("zones") or [],
            "set_pieces": route_evidence.get("set_pieces"),
            "penalties": route_evidence.get("penalties"),
            "progression_route": route_evidence.get("progression_route"),
            "return_routes": route_evidence.get("return_routes") or [],
            "confidence": role.get("confidence") or "NONE",
            "sample_quality": role.get("sample_quality"),
            "evidence_minutes": role.get("evidence_minutes"),
            "metrics": role.get("metrics") or {},
            "reason": role.get("reason"),
            "evidence": {
                "class": "OBSERVED_ADVANCED_ROLE_PROFILE" if profile and profile != "UNASSESSED" else "NO_ADVANCED_ROLE_EVIDENCE",
                "return_route_class": "OBSERVED_PLAYER_EVENTS" if route_evidence.get("return_routes") else "NO_OBSERVED_RETURN_ROUTE",
                "decision_influence": "ADVISORY_ONLY",
                "source": ((player.get("provenance") or {}).get("tactical_role")),
            },
        }

    team_profiles = {
        "schema_version": 2,
        "contract": "TACTICAL_TEAM_PROFILES_V1",
        "generated_at": generated_at,
        "status": "OBSERVED_ENRICHMENT_EVIDENCE" if teams_with_recent else "PARTIAL_INTERNAL_EVIDENCE",
        "teams": team_rows,
        "governance": {
            "coach_style_not_inferred": True,
            "pressing_not_inferred_from_defensive_activity_proxy": True,
            "fpl_position_shape_not_claimed_as_true_tactical_formation": True,
            "observed_strengths_and_vulnerabilities_require_match_event_evidence": True,
            "external_verified_tactical_enrichment_may_extend_but_not_overwrite_canonical_identity": True,
        },
    }
    player_roles = {
        "schema_version": 2,
        "contract": "TACTICAL_PLAYER_ROLE_PROFILES_V1",
        "generated_at": generated_at,
        "status": "OBSERVED_ENRICHMENT_EVIDENCE",
        "players": role_rows,
        "assessed_players": assessed,
        "return_route_players": routes_covered,
        "total_players": len(role_rows),
        "governance": {
            "role_profiles_are_observed_evidence_not_manager_declared_roles": True,
            "return_routes_require_observed_player_events": True,
            "zero_observed_event_does_not_prove_absence_of_role": True,
            "advisory_only": True,
        },
    }
    recent_form = {
        "schema_version": 2,
        "contract": "RECENT_TACTICAL_FORM_V1",
        "generated_at": generated_at,
        "status": "OBSERVED_RECENT_MATCH_EVENTS" if teams_with_recent else "NO_OBSERVED_RECENT_MATCH_EVENT_ARTIFACT",
        "source_contract": observed_cfg.get("contract"),
        "teams": recent_teams,
        "governance": {
            "rolling_window_gws": int(observed_cfg.get("recent_gw_window") or 5),
            "history_deduplicated_by_gw_match_team": True,
            "match_ids_are_source_observed_not_guessed": True,
            "true_pressing_or_possession_is_never_fabricated": True,
            "shot_and_concession_zones_are_observed_event_locations": True,
        },
    }
    return {
        "team_profiles": team_profiles,
        "player_roles": player_roles,
        "recent_form": recent_form,
        "summary": {
            "generated_at": generated_at,
            "team_profiles": len(team_rows),
            "player_profiles": len(role_rows),
            "assessed_player_roles": assessed,
            "player_return_routes": routes_covered,
            "observed_recent_tactical_teams": teams_with_recent,
            "current_gw": match_payload.get("gw"),
            "status": "OBSERVED_ENRICHMENT_EVIDENCE" if teams_with_recent else "PARTIAL_INTERNAL_EVIDENCE",
        },
    }


def run() -> dict[str, Any]:
    out = build()
    atomic_json(TEAM_OUT, out["team_profiles"])
    atomic_json(ROLE_OUT, out["player_roles"])
    atomic_json(RECENT_OUT, out["recent_form"])

    # Understat is an extension of this capability, not a second executable
    # owner. Run and reconcile it inside the same bounded tactical_context
    # process after canonical artifacts exist so it can enrich them in place.
    from src.engines.understat_tactical_context import run as run_understat_tactical_context
    from src.intelligence.understat_runtime_reconcile import reconcile as reconcile_understat_runtime

    understat_out = reconcile_understat_runtime(run_understat_tactical_context())
    health = understat_out.get("health") or {}
    out["summary"]["understat_tactical"] = {
        "status": health.get("status") or "UNAVAILABLE",
        "production_parity_status": health.get("production_parity_status") or "REVIEW_REQUIRED",
        "optional_enrichment": True,
        "canonical_merge": health.get("canonical_merge") or {},
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
    }
    print(json.dumps(out["summary"], ensure_ascii=False))
    return out["summary"]


if __name__ == "__main__":
    run()
